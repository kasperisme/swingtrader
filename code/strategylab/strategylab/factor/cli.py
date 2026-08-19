"""Replicate risk-managed momentum on its native object.

    python -m strategylab.factor.cli replicate [--limit N] [--sweep]

Builds a monthly-rebalanced WML decile portfolio, reports its unmanaged
statistics against the published ones, then applies the scaling variants.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from ..config import OUTPUT_ROOT, LabConfig, load_env
from ..data.prices import PriceStore
from ..data.universe import UniverseBuilder
from ..features import FeatureBank, benchmark_series
from . import wml as W

log = logging.getLogger(__name__)

# Barroso & Santa-Clara (2015), US 1927-2011, value-weighted WML.
PUBLISHED = {"sharpe_raw": 0.53, "sharpe_managed": 0.97,
             "excess_kurtosis_raw": 18.24, "excess_kurtosis_managed": 2.68,
             "skew_raw": -2.47, "skew_managed": -0.42}


def _row(name: str, st: dict, extra: str = "") -> str:
    return (f"{name:<30}{st.get('sharpe', 0):>8.2f}{st.get('annual_return', 0):>10.1%}"
            f"{st.get('annual_vol', 0):>8.1%}{st.get('max_drawdown', 0):>9.1%}"
            f"{st.get('skew', 0):>8.2f}{st.get('excess_kurtosis', 0):>9.1f}"
            f"{st.get('worst_month', 0):>10.1%}  {extra}")


def cmd_replicate(args) -> int:
    load_env()
    cfg = LabConfig(run_id="factor")
    ub, st = UniverseBuilder(), PriceStore()
    ordered = [r["symbol"] for r in ub.membership("nyse_nasdaq", True)]
    cached = set(st.cached_symbols())
    syms = [s for s in ordered if s in cached]
    if args.limit:
        syms = syms[: args.limit]
    panel = st.build_panel(syms, args.start, args.end, min_rows=400)
    print(f"panel: {panel.shape[0]} sessions x {panel.shape[1]} symbols "
          f"({panel.dates[0]} .. {panel.dates[-1]})\n")

    bench = benchmark_series(st, cfg.benchmark, panel.dates)
    bank = FeatureBank(panel, bench)
    mkt = np.zeros(len(bench))
    mkt[1:] = bench[1:] / np.where(bench[:-1] > 0, bench[:-1], np.nan) - 1.0
    mkt = np.nan_to_num(mkt, nan=0.0)

    signal = bank.get("momo_12m_1m")                       # the classic 12-1
    dv = bank.get("dollar_volume_20d")
    # Liquidity floor only — the point is to reproduce the ACADEMIC object, so no
    # trend gates, no stops, no position limits.
    eligible = np.isfinite(panel.close) & (panel.close > 5.0) & (dv > 5e6)
    cap_proxy = np.where(np.isfinite(dv), dv, np.nan)      # value-weight stand-in

    print(f"{'portfolio':<30}{'Sharpe':>8}{'return':>10}{'vol':>8}{'maxDD':>9}"
          f"{'skew':>8}{'exKurt':>9}{'worstMo':>10}")
    print("-" * 94)

    results = {}
    for wname, wts in (("equal-weight", None), ("dollar-volume-weight", cap_proxy)):
        res = W.build_wml(panel, signal, eligible, n_portfolios=args.deciles,
                          weights=wts, min_names=args.min_names,
                          label=f"WML {wname}")
        raw = res.stats()
        if not raw.get("n_days"):
            print(f"{wname}: insufficient data")
            continue
        print(_row(f"WML raw ({wname})", raw))
        results[f"raw_{wname}"] = raw

        # After costs, and the long leg alone — the two versions that decide
        # whether any of this is reachable from an actual account.
        costed = W.apply_costs(res, one_way_bps=args.cost_bps,
                               borrow_bps_annual=args.borrow_bps)
        print(_row("   after costs (raw)", costed.stats()))
        results[f"costed_{wname}"] = costed.stats()

        for vname, (scaled, w) in W.scale_variants(
                res, market_returns=mkt, target=args.target,
                lookback=args.lookback, cap=args.cap).items():
            sub = W.WMLResult(res.dates, scaled, res.long_returns, res.short_returns,
                              res.n_long, res.n_short, res.rebalance_idx, vname)
            s = sub.stats()
            fin = w[np.isfinite(w)]
            print(_row(f"   + {vname}", s,
                       f"avg leverage {fin.mean():.2f}x" if fin.size else ""))
            results[f"{vname}_{wname}"] = s | {"avg_leverage": float(fin.mean())
                                               if fin.size else None}
        # Scale the COSTED series too: scaling a frictionless series and then
        # claiming the Sharpe is the classic overstatement.
        sc, wc = W.scale_constant_vol(costed, args.target, args.lookback, args.cap)
        sub = W.WMLResult(res.dates, sc, res.long_returns, res.short_returns,
                          res.n_long, res.n_short, res.rebalance_idx, "costed+scaled")
        print(_row("   after costs + constant vol", sub.stats(),
                   f"avg leverage {wc[np.isfinite(wc)].mean():.2f}x"))
        results[f"costed_scaled_{wname}"] = sub.stats()

        leg = W.long_leg_only(res)
        print(_row("   long leg only (raw)", leg.stats()))
        sl, wl = W.scale_constant_vol(leg, args.target, args.lookback, args.cap)
        subl = W.WMLResult(res.dates, sl, res.long_returns, res.short_returns,
                           res.n_long, res.n_short, res.rebalance_idx, "long+scaled")
        print(_row("   long leg + constant vol", subl.stats(),
                   f"avg leverage {wl[np.isfinite(wl)].mean():.2f}x"))
        results[f"longleg_{wname}"] = leg.stats()
        results[f"longleg_scaled_{wname}"] = subl.stats()
        print()

    print("Published (Barroso & Santa-Clara, US 1927-2011, value-weighted):")
    print(f"   raw     Sharpe {PUBLISHED['sharpe_raw']:.2f}  skew "
          f"{PUBLISHED['skew_raw']:+.2f}  excess kurtosis {PUBLISHED['excess_kurtosis_raw']:.1f}")
    print(f"   managed Sharpe {PUBLISHED['sharpe_managed']:.2f}  skew "
          f"{PUBLISHED['skew_managed']:+.2f}  excess kurtosis "
          f"{PUBLISHED['excess_kurtosis_managed']:.1f}")

    out_dir = Path(args.out or (OUTPUT_ROOT / "factor"))
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "replication.json").write_text(json.dumps(
        {"published": PUBLISHED, "measured": results,
         "window": [str(panel.dates[0]), str(panel.dates[-1])],
         "symbols": int(panel.shape[1]), "target_vol": args.target,
         "lookback": args.lookback, "cap": args.cap}, indent=2, default=str))
    print(f"\n-> {out_dir / 'replication.json'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="strategylab.factor", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--log", default="WARNING")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("replicate", help="WML + volatility scaling")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--start", default="2013-01-01")
    p.add_argument("--end", default="2026-06-30")
    p.add_argument("--deciles", type=int, default=10)
    p.add_argument("--min-names", type=int, default=100)
    p.add_argument("--target", type=float, default=0.12)
    p.add_argument("--lookback", type=int, default=126)
    p.add_argument("--cap", type=float, default=2.0,
                   help="leverage cap on the scaling weight")
    p.add_argument("--cost-bps", type=float, default=13.0, help="one-way cost")
    p.add_argument("--borrow-bps", type=float, default=100.0)
    p.add_argument("--out", default=None)
    p.set_defaults(func=cmd_replicate)
    args = ap.parse_args(argv)
    logging.basicConfig(level=getattr(logging, args.log.upper(), logging.WARNING),
                        format="%(levelname)s %(name)s: %(message)s")
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
