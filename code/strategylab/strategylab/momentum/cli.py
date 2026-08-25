"""Momentum-universe CLI.

    python -m strategylab.momentum.cli pin              # build and fingerprint the universe
    python -m strategylab.momentum.cli ic [--horizon 21]  # IC + incremental IC for every signal

`pin` is the foundation everything downstream is measured on. `ic` answers the
only question that matters for stacking: which of these signals adds something
the momentum screen has not already given you.
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
from ..features import FeatureBank
from ..pairs.formation import drop_non_sessions
from . import hold as holdmod
from . import ic as icmod
from .signals import CONTROLS, REGISTRY, compute_all
from .universe import UniverseSpec, pin_universe

log = logging.getLogger(__name__)

PANEL_START = "2004-01-01"


def _load(limit: int | None, start: str, end: str):
    load_env()
    ub = UniverseBuilder()
    ordered = [r["symbol"] for r in ub.membership("nyse_nasdaq", include_delisted=True)]
    store = PriceStore()
    cached = set(store.cached_symbols())
    symbols = [s for s in ordered if s in cached]
    if limit:
        symbols = symbols[:limit]
    bench = "SPY" if "SPY" in cached else None
    if bench and bench not in symbols:
        symbols.append(bench)
    panel = store.build_panel(sorted(set(symbols)), start, end, min_rows=300)
    panel, dropped = drop_non_sessions(panel)
    if dropped:
        log.warning("dropped %d non-session row(s): %s", len(dropped), ", ".join(dropped[:5]))
    bclose = panel.close[:, panel.symbols.index(bench)] if bench in panel.symbols else None
    log.info("panel: %d sessions x %d symbols (%s .. %s)", panel.shape[0], panel.shape[1],
             panel.dates[0], panel.dates[-1])
    return panel, FeatureBank(panel, benchmark_close=bclose)


def _pin(args, cfg):
    panel, bank = _load(args.limit, PANEL_START, cfg.splits.dev_end
                        if args.dev_only else cfg.splits.vault_end)
    spec = UniverseSpec(screen=args.screen, rs_min=args.rs_min,
                        min_price=args.min_price, min_adv_usd=args.min_adv * 1e6)
    uni = pin_universe(panel, bank, spec)
    return panel, bank, uni


def cmd_pin(args) -> int:
    cfg = LabConfig()
    panel, bank, uni = _pin(args, cfg)
    out = Path(args.out or (OUTPUT_ROOT / "momentum"))
    path = uni.save(out)
    print("\n" + uni.summary())
    print(f"\npinned -> {path}")
    print(f"fingerprint {uni.fingerprint}")
    print("\nAny study that reports against a different fingerprint is not "
          "comparable to this one.\n")
    return 0


def cmd_ic(args) -> int:
    cfg = LabConfig()
    panel, bank, uni = _pin(args, cfg)
    out_dir = Path(args.out or (OUTPUT_ROOT / "momentum"))
    out_dir.mkdir(parents=True, exist_ok=True)
    uni.save(out_dir)
    log.info("universe pinned [%s]: median %d names/day", uni.fingerprint[:12],
             uni.stats()["median_names_per_day"])

    dev_lo = panel.date_index(cfg.splits.dev_start)
    dev_hi = min(panel.shape[0], panel.date_index(cfg.splits.dev_end) + 1)
    mask = uni.mask.copy()
    mask[:dev_lo] = False
    mask[dev_hi:] = False
    log.info("dev window %s .. %s: %d qualified name-days",
             cfg.splits.dev_start, cfg.splits.dev_end, int(mask.sum()))

    names = args.signals.split(",") if args.signals else list(REGISTRY)
    scores = compute_all(bank, names, mask=mask)
    log.info("computed %d signals", len(scores))

    H = args.horizon
    report = icmod.ic_report(scores, panel, mask, H, with_placebo=not args.no_placebo)
    inc = icmod.incremental_ic(scores, panel, mask, H, CONTROLS)
    corr = icmod.signal_correlations(scores, mask)

    decay = {}
    if not args.no_decay:
        for h in (5, 21, 63):
            fwd = icmod.forward_returns(panel, h)
            decay[f"H{h}"] = {k: icmod.ic_summary(icmod.daily_ic(s, fwd, mask), h)
                              .get("ic_mean") for k, s in scores.items()}

    payload = {
        "universe": uni.manifest() | {"symbols": len(uni.symbols)},
        "horizon": H,
        "dev": [cfg.splits.dev_start, cfg.splits.dev_end],
        "ic": report, "incremental": inc,
        "correlations": corr.round(3).to_dict(),
        "ic_decay": decay,
        "controls": CONTROLS,
    }
    (out_dir / f"ic_H{H}.json").write_text(json.dumps(payload, indent=2, default=str))
    corr.round(3).to_csv(out_dir / f"signal_correlations_H{H}.csv")
    _print(payload, corr)
    return 0


def _print(payload: dict, corr: pd.DataFrame) -> None:
    H = payload["horizon"]
    u = payload["universe"]
    print("\n" + "=" * 92)
    print(f"MOMENTUM UNIVERSE — signal information coefficients  (horizon {H}d)")
    print("=" * 92)
    s = u["stats"]
    print(f"universe '{u['spec']['screen']}' [{u['fingerprint'][:12]}]  "
          f"median {s['median_names_per_day']} names/day, "
          f"{s['ever_qualified']} names ever qualified")
    print(f"dev {payload['dev'][0]} .. {payload['dev'][1]}\n")

    ic, inc = payload["ic"], payload["incremental"]["coefficients"]
    print(f"{'signal':<24}{'family':<11}{'IC':>8}{'t(NW)':>8}{'IR':>7}{'hit':>7}"
          f"{'placebo t':>11}{'  incr bps/σ':>13}{'incr t':>8}")
    print("-" * 92)
    rows = sorted(ic, key=lambda k: -abs(inc.get(k, {}).get("t_newey_west") or 0))
    for k in rows:
        r, i = ic[k], inc.get(k, {})
        if not r.get("available"):
            continue
        fam = REGISTRY[k].family if k in REGISTRY else ""
        ctrl = " *" if k in payload["controls"] else "  "
        print(f"{k+ctrl:<24}{fam:<11}{r['ic_mean']:>+8.4f}{r['t_newey_west']:>+8.2f}"
              f"{(r['ir_annualised'] or 0):>7.2f}{r['hit_rate']:>7.1%}"
              f"{(r.get('placebo_t') or 0):>+11.2f}"
              f"{(i.get('mean_bps_per_sigma') or 0):>+13.1f}"
              f"{(i.get('t_newey_west') or 0):>+8.2f}")
    print("-" * 92)
    print("* = mandatory momentum control. 'incr' = Fama-MacBeth coefficient with every")
    print("  other signal in the same regression — the only column that says whether a")
    print("  signal adds anything the momentum screen has not already supplied.")

    ex = [k for k in rows if k not in payload["controls"]
          and abs(inc.get(k, {}).get("t_newey_west") or 0) >= 2.0]
    print(f"\nsignals with |incremental t| >= 2 after controls: "
          f"{', '.join(ex) if ex else 'NONE'}")

    naive = [r.get("overstatement_factor") for r in ic.values()
             if r.get("overstatement_factor")]
    if naive:
        print(f"overlap correction: a naive t-stat would have overstated significance "
              f"by {np.median(naive):.1f}x")

    arr = corr.to_numpy().astype(float).copy()
    np.fill_diagonal(arr, np.nan)
    c = pd.DataFrame(arr, index=corr.index, columns=corr.columns)
    pairs = c.abs().stack().sort_values(ascending=False)
    seen, top = set(), []
    for (a, b), v in pairs.items():
        if (b, a) in seen:
            continue
        seen.add((a, b))
        top.append((a, b, corr.loc[a, b]))
        if len(top) >= 5:
            break
    print("\nmost collinear signal pairs (breadth is only real where these are low):")
    for a, b, v in top:
        print(f"   {a:<24} {b:<24} {v:+.2f}")
    print("=" * 92 + "\n")


def cmd_hold(args) -> int:
    """Does owning the whole screen beat the market?"""
    cfg = LabConfig()
    panel, bank, uni = _pin(args, cfg)
    out_dir = Path(args.out or (OUTPUT_ROOT / "momentum"))
    out_dir.mkdir(parents=True, exist_ok=True)
    uni.save(out_dir)

    spec = holdmod.HoldSpec(rebalance=args.rebalance,
                            cost_bps_per_side=(cfg.costs.commission_bps
                                               + cfg.costs.slippage_bps
                                               + cfg.costs.spread_bps),
                            max_weight=args.max_weight, cash_annual=args.cash,
                            breadth_scaled=args.breadth_scaled)
    warm = panel.date_index("2005-01-03")
    port, diag = holdmod.run_hold(panel, uni.mask, spec, start=warm)
    spy = holdmod.buy_and_hold(panel, "SPY")

    spans = {"full 2005-2026": ("2005-01-03", cfg.splits.vault_end),
             "dev 2014-2023": (cfg.splits.dev_start, cfg.splits.dev_end),
             "vault 2024-2026": (cfg.splits.vault_start, cfg.splits.vault_end)}
    results = {}
    for name, (a, b) in spans.items():
        lo, hi = panel.date_index(a), min(len(port), panel.date_index(b) + 1)
        if hi - lo < 200:
            continue
        p_, s_ = port[lo:hi], spy[lo:hi]
        results[name] = {"screen": holdmod.stats_of(p_, s_),
                         "spy": holdmod.stats_of(s_)}

    variants = {}
    if not args.no_variants:
        for freq in ("W", "M", "Q"):
            v = holdmod.HoldSpec(rebalance=freq, cost_bps_per_side=spec.cost_bps_per_side,
                                 max_weight=spec.max_weight, cash_annual=spec.cash_annual)
            r, d = holdmod.run_hold(panel, uni.mask, v, start=warm)
            lo, hi = panel.date_index("2005-01-03"), len(r)
            variants[f"rebalance_{freq}"] = holdmod.stats_of(r[lo:hi], spy[lo:hi]) | {
                "annual_turnover": d["annual_turnover"]}
        for label, bs in (("breadth_scaled", True), ("always_invested", False)):
            v = holdmod.HoldSpec(rebalance=spec.rebalance,
                                 cost_bps_per_side=spec.cost_bps_per_side,
                                 max_weight=spec.max_weight,
                                 cash_annual=spec.cash_annual, breadth_scaled=bs)
            r, d = holdmod.run_hold(panel, uni.mask, v, start=warm)
            lo, hi = panel.date_index("2005-01-03"), len(r)
            variants[label] = holdmod.stats_of(r[lo:hi], spy[lo:hi]) | {
                "avg_exposure": d["avg_exposure"]}
        for cap in (0.05, 0.10):
            v = holdmod.HoldSpec(rebalance=spec.rebalance,
                                 cost_bps_per_side=spec.cost_bps_per_side,
                                 max_weight=cap, cash_annual=spec.cash_annual)
            r, d = holdmod.run_hold(panel, uni.mask, v, start=warm)
            lo, hi = panel.date_index("2005-01-03"), len(r)
            variants[f"max_weight_{cap:.0%}"] = holdmod.stats_of(r[lo:hi], spy[lo:hi]) | {
                "avg_exposure": d["avg_exposure"]}

    surv = holdmod.survivorship_report(panel, uni.mask)
    payload = {"universe": uni.manifest() | {"symbols": len(uni.symbols)},
               "spec": spec.__dict__, "diagnostics": diag,
               "results": results, "variants": variants, "survivorship": surv}
    (out_dir / f"hold_{args.rebalance}.json").write_text(json.dumps(payload, indent=2, default=str))
    _print_hold(payload)
    return 0


def _print_hold(payload: dict) -> None:
    d, u = payload["diagnostics"], payload["universe"]
    print("\n" + "=" * 92)
    print("HOLD THE SCREEN — equal weight, rebalanced, versus SPY")
    print("=" * 92)
    print(f"universe [{u['fingerprint'][:12]}] median {d['median_names']} names held, "
          f"avg exposure {d['avg_exposure']:.0%}, {d['annual_turnover']:.1f}x annual turnover")
    print(f"costs {payload['spec']['cost_bps_per_side']:.0f}bp/side, cash earns "
          f"{payload['spec']['cash_annual']:.1%}\n")
    print(f"{'span':<18}{'book':<9}{'CAGR':>8}{'vol':>7}{'Sharpe':>8}{'maxDD':>8}"
          f"{'total':>10}{'beta':>7}{'IR':>7}{'alpha t':>9}")
    for name, r in payload["results"].items():
        for label in ("screen", "spy"):
            s = r[label]
            print(f"{name if label == 'screen' else '':<18}{label:<9}"
                  f"{s['cagr']:>+7.1%}{s['vol']:>7.1%}{s['sharpe']:>8.2f}"
                  f"{s['max_drawdown']:>8.1%}{s['total_return']:>+10.0%}"
                  f"{s.get('beta', float('nan')):>7.2f}"
                  f"{s.get('information_ratio', float('nan')):>7.2f}"
                  f"{s.get('alpha_t', float('nan')):>9.2f}")
    if payload["variants"]:
        print(f"\n{'variant (full period)':<24}{'CAGR':>8}{'Sharpe':>8}{'maxDD':>8}"
              f"{'IR':>7}{'alpha t':>9}{'turnover/exposure':>20}")
        for k, v in payload["variants"].items():
            extra = v.get("annual_turnover")
            tag = f"{extra:.1f}x" if extra is not None else f"{v.get('avg_exposure', 0):.0%} invested"
            print(f"{k:<24}{v['cagr']:>+7.1%}{v['sharpe']:>8.2f}{v['max_drawdown']:>8.1%}"
                  f"{v['information_ratio']:>7.2f}{v['alpha_t']:>9.2f}{tag:>20}")
    s = payload["survivorship"]
    print(f"\nsurvivorship: {s['of_which_stop_trading']} of "
          f"{s['names_ever_qualified']} names held stop trading; "
          f"{s['share_of_holding_days_in_names_that_stop']:.1%} of holding-days.")
    print("The delisted feed is page-capped, so most failures are ABSENT rather than")
    print("present and losing — every return above is biased upward by an unknown amount.")
    print("=" * 92 + "\n")


def cmd_tilt(args) -> int:
    """Does tilting the book by a news signal change the P&L?

    Paired by construction: same universe, same rebalance dates, same costs,
    same period — only the weights differ. The difference series is far less
    noisy than either book alone, which is the only reason a fifteen-month
    window is worth testing at all.
    """
    from ..news.overlay import NEWS_SIGNALS, build_news_matrices, coverage_report
    from ..setups.study import _cluster

    cfg = LabConfig()
    panel, bank, uni = _pin(args, cfg)
    out_dir = Path(args.out or (OUTPUT_ROOT / "momentum"))
    out_dir.mkdir(parents=True, exist_ok=True)

    mats = build_news_matrices(panel, lookback=args.lookback)
    cov = coverage_report(panel, uni.mask, mats)
    lo = panel.date_index(cov["first_covered_session"])
    hi = panel.date_index(cov["last_covered_session"]) + 1
    log.info("news window %s .. %s (%d sessions), median %d names/day (%.0f%%)",
             cov["first_covered_session"], cov["last_covered_session"],
             cov["covered_sessions"], cov["median_universe_names_with_news"],
             100 * cov["median_share_of_universe_with_news"])

    cost = (cfg.costs.commission_bps + cfg.costs.slippage_bps + cfg.costs.spread_bps)
    base_spec = holdmod.HoldSpec(rebalance=args.rebalance, cost_bps_per_side=cost,
                                 breadth_scaled=True)
    base, bdiag = holdmod.run_hold(panel, uni.mask, base_spec, start=lo)
    spy = holdmod.buy_and_hold(panel, "SPY")
    # run_hold returns one row fewer than the panel (the last open has no
    # following open to price a return against).
    hi = min(hi, len(base), len(spy))

    rows = {}
    for name in NEWS_SIGNALS:
        for mode in ("top_half", "rank_weight"):
            spec = holdmod.HoldSpec(rebalance=args.rebalance, cost_bps_per_side=cost,
                                    breadth_scaled=True, tilt_mode=mode)
            r, d = holdmod.run_hold(panel, uni.mask, spec, start=lo,
                                    tilt_signal=mats[name])
            a, b = r[lo:hi], base[lo:hi]
            diff = a - b
            idx = pd.PeriodIndex(pd.DatetimeIndex(panel.dates[lo:hi]), freq="M")
            monthly = pd.Series(diff, index=idx).groupby(level=0).sum()
            c = _cluster(monthly.to_numpy())
            rows[f"{name}|{mode}"] = {
                "tilted": holdmod.stats_of(a, spy[lo:hi]),
                "delta_annualised": float(diff.mean() * 252),
                "delta_t": c.get("t"), "months": c.get("months"),
                "share_months_positive": c.get("share_months_positive"),
                "turnover": d["annual_turnover"],
                "tilt_effective_share": d.get("tilt_effective_share"),
                # A tilt that rarely changes the weights has not been tested.
                # `news_attention` is an integer count with heavy ties, so a
                # median split can select nothing at all.
                "degenerate": bool((d.get("tilt_effective_share") or 0) < 0.5),
            }

    payload = {"coverage": cov, "window": [cov["first_covered_session"],
                                           cov["last_covered_session"]],
               "base": holdmod.stats_of(base[lo:hi], spy[lo:hi]),
               "spy": holdmod.stats_of(spy[lo:hi]),
               "base_turnover": bdiag["annual_turnover"], "tilts": rows}
    (out_dir / "news_tilt.json").write_text(json.dumps(payload, indent=2, default=str))

    print("\n" + "=" * 96)
    print("NEWS TILT — does weighting the momentum book by a news signal change anything?")
    print("=" * 96)
    print(f"window {payload['window'][0]} .. {payload['window'][1]}  "
          f"({cov['covered_sessions']} sessions, "
          f"{cov['median_universe_names_with_news']:.0f} names/day with news = "
          f"{cov['median_share_of_universe_with_news']:.0%})")
    b, sp = payload["base"], payload["spy"]
    print(f"\nuntilted screen  CAGR {b['cagr']:+.1%}  Sharpe {b['sharpe']:.2f}  "
          f"maxDD {b['max_drawdown']:.1%}")
    print(f"SPY              CAGR {sp['cagr']:+.1%}  Sharpe {sp['sharpe']:.2f}  "
          f"maxDD {sp['max_drawdown']:.1%}\n")
    print(f"{'tilt':<34}{'CAGR':>8}{'Sharpe':>8}{'delta/yr':>10}{'t':>7}"
          f"{'+months':>9}{'bites':>7}")
    for k, v in sorted(rows.items(), key=lambda kv: -(kv[1]["delta_t"] or 0)):
        t = v["tilted"]
        if v.get("degenerate"):
            share = v.get("tilt_effective_share") or 0.0
            print(f"{k:<34}   NOT TESTABLE — the tilt changed the weights on only "
                  f"{share:.0%} of rebalances")
            continue
        print(f"{k:<34}{t['cagr']:>+7.1%}{t['sharpe']:>8.2f}"
              f"{v['delta_annualised']:>+10.2%}{(v['delta_t'] or 0):>+7.2f}"
              f"{(v['share_months_positive'] or 0):>8.0%}"
              f"{(v.get('tilt_effective_share') or 0):>7.0%}")
    print("   'bites' = share of rebalances where the tilt actually changed the "
          "weights.\n   A tilt that never bites produces a perfect null about the "
          "tilt, not the signal.")
    print(f"\n{rows and list(rows.values())[0]['months']} monthly observations. "
          "A fifteen-month paired test resolves only a very large difference;")
    print("read the sign and the consistency, not the magnitude.")
    print("=" * 96 + "\n")
    return 0


def cmd_rotate(args) -> int:
    """Hold only the best N names and rotate — does concentration pay?

    The question this settles is not really "is one stock better than 206". It is
    whether the RANKING has enough skill to survive giving up diversification.
    Grinold: IR ~ IC * sqrt(breadth). Holding one name sets breadth to 1, so the
    whole of the return has to come from the ranking. Every measurement in this
    project so far puts the incremental IC of every available score at zero,
    which predicts the concentration curve should fall monotonically in Sharpe.
    Worth checking rather than assuming.
    """
    cfg = LabConfig()
    panel, bank, uni = _pin(args, cfg)
    out_dir = Path(args.out or (OUTPUT_ROOT / "momentum"))
    out_dir.mkdir(parents=True, exist_ok=True)

    scores = compute_all(bank, args.scores.split(","), mask=uni.mask)
    cost = cfg.costs.commission_bps + cfg.costs.slippage_bps + cfg.costs.spread_bps
    warm = panel.date_index("2005-01-03")
    spy = holdmod.buy_and_hold(panel, "SPY")

    spans = {"full 2005-2026": ("2005-01-03", cfg.splits.vault_end),
             "dev 2014-2023": (cfg.splits.dev_start, cfg.splits.dev_end)}
    rows = {}
    for sname, smat in scores.items():
        for n in args.sizes:
            spec = holdmod.HoldSpec(rebalance=args.rebalance, cost_bps_per_side=cost,
                                    breadth_scaled=(n == 0), top_n=n,
                                    hysteresis_mult=args.hysteresis)
            r, d = holdmod.run_hold(panel, uni.mask, spec, start=warm, score=smat)
            for span, (a, b) in spans.items():
                lo = panel.date_index(a)
                hi = min(len(r), len(spy), panel.date_index(b) + 1)
                if hi - lo < 300:
                    continue
                st = holdmod.stats_of(r[lo:hi], spy[lo:hi])
                rows[(sname, n, span)] = st | {
                    "annual_turnover": d["annual_turnover"],
                    "worst_12m": d.get("worst_12m")}

    payload = {"universe": uni.fingerprint, "scores": list(scores),
               "sizes": list(args.sizes), "hysteresis": args.hysteresis,
               "rebalance": args.rebalance,
               "rows": {f"{k[0]}|top{k[1] or 'all'}|{k[2]}": v for k, v in rows.items()},
               "spy": {s: holdmod.stats_of(
                   spy[panel.date_index(a):min(len(spy), panel.date_index(b) + 1)])
                   for s, (a, b) in spans.items()}}
    (out_dir / "rotation.json").write_text(json.dumps(payload, indent=2, default=str))

    print("\n" + "=" * 100)
    print("CONCENTRATION — hold only the best N and rotate, versus holding the screen")
    print("=" * 100)
    print(f"rebalance {args.rebalance}, hysteresis {args.hysteresis}x, "
          f"costs {cost:.0f}bp/side\n")
    for span in spans:
        sp = payload["spy"][span]
        print(f"--- {span}   (SPY: CAGR {sp['cagr']:+.1%}, Sharpe {sp['sharpe']:.2f}, "
              f"maxDD {sp['max_drawdown']:.1%})")
        print(f"   {'score':<14}{'hold':>6}{'CAGR':>8}{'vol':>7}{'Sharpe':>8}"
              f"{'maxDD':>8}{'worst 12m':>11}{'turnover':>10}")
        for sname in scores:
            for n in args.sizes:
                v = rows.get((sname, n, span))
                if not v:
                    continue
                label = "all" if n == 0 else str(n)
                print(f"   {sname:<14}{label:>6}{v['cagr']:>+8.1%}{v['vol']:>7.1%}"
                      f"{v['sharpe']:>8.2f}{v['max_drawdown']:>8.1%}"
                      f"{(v.get('worst_12m') or 0):>+11.1%}"
                      f"{v['annual_turnover']:>9.1f}x")
        print()
    print("IR ~ IC x sqrt(breadth): concentrating to one name sets breadth to 1, so the")
    print("entire result has to come from the ranking. Read the Sharpe column.")
    print("=" * 100 + "\n")
    return 0


def cmd_switch(args) -> int:
    """Hold one name; reconsider on a schedule; switch when a better one appears.

    Two knobs decide this strategy and they trade against each other:

      * **How often you look.** Daily means the book switches the moment the
        ranking changes; quarterly means it lives with its choice.
      * **How much better the challenger must be.** Hysteresis of 1.0 switches
        to whatever is top today; 5.0 keeps the incumbent while it stays inside
        the top five.

    Looking more often only helps if the ranking's movement is information. If
    it is noise, each look is an invitation to pay 26bp on the whole account.
    """
    cfg = LabConfig()
    panel, bank, uni = _pin(args, cfg)
    out_dir = Path(args.out or (OUTPUT_ROOT / "momentum"))
    out_dir.mkdir(parents=True, exist_ok=True)
    smat = compute_all(bank, [args.score], mask=uni.mask)[args.score]
    cost = cfg.costs.commission_bps + cfg.costs.slippage_bps + cfg.costs.spread_bps
    warm = panel.date_index("2005-01-03")
    spy = holdmod.buy_and_hold(panel, "SPY")
    lo = warm
    hi = min(len(spy), panel.date_index(cfg.splits.vault_end) + 1)

    rows = {}
    for freq in args.frequencies:
        for hy in args.hysteresis:
            spec = holdmod.HoldSpec(rebalance=freq, cost_bps_per_side=cost,
                                    top_n=args.hold, hysteresis_mult=hy)
            r, d = holdmod.run_hold(panel, uni.mask, spec, start=warm, score=smat)
            h = min(hi, len(r))
            gross_spec = holdmod.HoldSpec(rebalance=freq, cost_bps_per_side=0.0,
                                          top_n=args.hold, hysteresis_mult=hy)
            g, _ = holdmod.run_hold(panel, uni.mask, gross_spec, start=warm, score=smat)
            rows[f"{freq}|hy{hy:g}"] = holdmod.stats_of(r[lo:h], spy[lo:h]) | {
                "switches_per_year": d["switches_per_year"],
                "median_hold_days": d["median_hold_days"],
                "annual_turnover": d["annual_turnover"],
                "gross_cagr": holdmod.stats_of(g[lo:h])["cagr"],
            }

    payload = {"universe": uni.fingerprint, "score": args.score, "hold": args.hold,
               "rows": rows, "spy": holdmod.stats_of(spy[lo:hi])}
    (out_dir / "switching.json").write_text(json.dumps(payload, indent=2, default=str))

    sp = payload["spy"]
    print("\n" + "=" * 100)
    print(f"SWITCHING — hold {args.hold} name(s) by {args.score}, reconsider and "
          f"reallocate when better")
    print("=" * 100)
    print(f"2005-2026.  SPY: CAGR {sp['cagr']:+.1%}, Sharpe {sp['sharpe']:.2f}, "
          f"maxDD {sp['max_drawdown']:.1%}\n")
    print(f"{'look | hysteresis':<22}{'switches/yr':>12}{'hold days':>11}"
          f"{'gross CAGR':>12}{'net CAGR':>10}{'cost drag':>11}{'Sharpe':>8}{'maxDD':>8}")
    for k, v in rows.items():
        drag = (v["gross_cagr"] or 0) - (v["cagr"] or 0)
        print(f"{k:<22}{(v['switches_per_year'] or 0):>12.1f}"
              f"{(v['median_hold_days'] or 0):>11.0f}"
              f"{(v['gross_cagr'] or 0):>+12.1%}{v['cagr']:>+10.1%}"
              f"{drag:>+11.1%}{v['sharpe']:>8.2f}{v['max_drawdown']:>8.1%}")
    print("\nLooking more often only pays if the ranking's movement is information.")
    print("'cost drag' is what each extra look costs: 26bp of the whole account per switch.")
    print("=" * 100 + "\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="strategylab.momentum")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--limit", type=int, default=None)
        p.add_argument("--screen", default="minervini",
                       choices=["minervini", "minervini_strict", "stage2"])
        p.add_argument("--rs-min", type=float, default=70.0)
        p.add_argument("--min-price", type=float, default=5.0)
        p.add_argument("--min-adv", type=float, default=5.0, help="in $M")
        p.add_argument("--dev-only", action="store_true")
        p.add_argument("--out", default=None)

    p = sub.add_parser("pin", help="build and fingerprint the momentum universe")
    common(p)
    p.set_defaults(func=cmd_pin)

    p = sub.add_parser("ic", help="IC and incremental IC for every registered signal")
    common(p)
    p.add_argument("--horizon", type=int, default=21)
    p.add_argument("--signals", default=None, help="comma-separated subset")
    p.add_argument("--no-placebo", action="store_true")
    p.add_argument("--no-decay", action="store_true")
    p.set_defaults(func=cmd_ic)

    p = sub.add_parser("hold", help="does owning the whole screen beat SPY?")
    common(p)
    p.add_argument("--rebalance", default="M", choices=["W", "M", "Q"])
    p.add_argument("--max-weight", type=float, default=1.0)
    p.add_argument("--cash", type=float, default=0.0)
    p.add_argument("--breadth-scaled", action="store_true",
                   help="scale exposure by qualifying count vs its trailing median")
    p.add_argument("--no-variants", action="store_true")
    p.set_defaults(func=cmd_hold)

    p = sub.add_parser("tilt", help="tilt the book by a news signal, paired vs untilted")
    common(p)
    p.add_argument("--rebalance", default="M", choices=["W", "M", "Q"])
    p.add_argument("--lookback", type=int, default=5)
    p.set_defaults(func=cmd_tilt)

    p = sub.add_parser("rotate", help="hold only the best N and rotate")
    common(p)
    p.add_argument("--rebalance", default="M", choices=["W", "M", "Q"])
    p.add_argument("--sizes", type=int, nargs="+", default=[1, 2, 3, 5, 10, 20, 50, 0])
    p.add_argument("--scores", default="rs_rank,mom_12_1,proximity_52w_high")
    p.add_argument("--hysteresis", type=float, default=2.0)
    p.set_defaults(func=cmd_rotate)

    p = sub.add_parser("switch", help="one name, reconsidered on a schedule")
    common(p)
    p.add_argument("--hold", type=int, default=1)
    p.add_argument("--score", default="rs_rank")
    p.add_argument("--frequencies", nargs="+", default=["D", "W", "M", "Q"])
    p.add_argument("--hysteresis", type=float, nargs="+", default=[1.0, 2.0, 5.0])
    p.set_defaults(func=cmd_switch)

    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
