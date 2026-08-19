"""Deployment — turn a validated genome into something that can actually trade.

A backtest is not a deliverable. What ships is:

  strategy.json        the frozen genome plus the exact protocol it was
                       validated under, so the result is reproducible
  strategy_card.md     the honest scorecard: dev AND vault numbers, the trial
                       count, DSR, PBO, the known limitations
  signals.py           a standalone daily signal generator — reads live prices,
                       applies the same rule set, and emits today's orders with
                       entry, stop, target and size
  nis_evolved.py       a drop-in screening script for the swingtrader
                       market_screenings registry

The signal generator imports the same `build_signals` the backtest used. That
is deliberate: a re-implementation of the rules for live trading is the most
reliable way to ship a strategy that does something other than what was tested.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from .config import LabConfig
from .genome import DEFAULTS, SPACE, Genome


def export(cfg: LabConfig, g: Genome, final: dict) -> Path:
    out = cfg.deploy_dir
    (out / "strategy.json").write_text(json.dumps({
        "created": datetime.now().isoformat(timespec="seconds"),
        "run_id": cfg.run_id,
        "protocol_version": cfg.protocol_version,
        "genome_hash": g.hash,
        "prefilter": cfg.prefilter,
        "genome": dict(g),
        "changes_vs_incumbent": g.describe_diff(Genome(DEFAULTS)),
        "protocol": cfg.to_dict(),
        "dev_metrics": final.get("dev_metrics", {}),
        "fold_metrics": final.get("fold_metrics", []),
        "vault_metrics": final.get("vault_metrics", {}),
        "n_trials": final.get("n_trials"),
        "pbo": final.get("pbo"),
        "dev_gate": final.get("dev_gate", {}),
        "final_gate": final.get("final_gate", {}),
        "deployable": final.get("deployable", False),
    }, indent=2, default=str))

    (out / "strategy_card.md").write_text(strategy_card(cfg, g, final))
    (out / "signals.py").write_text(_SIGNALS_SCRIPT)
    (out / "nis_evolved.py").write_text(_registry_script(g))
    return out


# ----------------------------------------------------------------------
def strategy_card(cfg: LabConfig, g: Genome, final: dict) -> str:
    dev = final.get("dev_metrics", {})
    vault = final.get("vault_metrics", {})
    gate = final.get("final_gate") or final.get("dev_gate") or {}
    checks = gate.get("checks", {})

    def row(k: str) -> str:
        c = checks.get(k)
        if not c:
            return f"| {k} | — | — | — |"
        mark = "PASS" if c["pass"] else "FAIL"
        return f"| {k} | {c['actual']:.3f} | {c['op']} {c['threshold']:.3f} | {mark} |"

    lines = [
        f"# Strategy card — `{g.hash}`",
        "",
        f"Run `{cfg.run_id}` · protocol `{cfg.protocol_version}` · "
        f"pre-filter `{cfg.prefilter}` · generated {date.today().isoformat()}",
        "",
        "## Verdict",
        "",
        ("**DEPLOYABLE** — cleared every gate including the sealed out-of-sample vault."
         if final.get("deployable") else
         "**NOT DEPLOYABLE** — see the failed checks below. Do not trade this."),
        "",
        "## Acceptance gates",
        "",
        "| check | actual | required | |",
        "|---|---|---|---|",
    ]
    lines += [row(k) for k in checks]
    lines += [
        "",
        f"Configurations evaluated during the search: **{final.get('n_trials', '?')}**. "
        f"The Deflated Sharpe below is computed against the expected best-of-N, so this "
        f"count is part of the result.",
        "",
        "## Performance",
        "",
        "| | dev (searched) | vault (sealed) |",
        "|---|---|---|",
    ]
    for label, key, fmt in [
        ("Sharpe", "sharpe", "{:.2f}"), ("Sortino", "sortino", "{:.2f}"),
        ("CAGR", "cagr", "{:.1%}"), ("Max drawdown", "max_drawdown", "{:.1%}"),
        ("Calmar", "calmar", "{:.2f}"), ("Volatility", "vol_annual", "{:.1%}"),
        ("Trades", "n_trades", "{:.0f}"), ("Hit rate", "hit_rate", "{:.1%}"),
        ("Expectancy (R)", "expectancy_r", "{:.2f}"),
        ("Profit factor", "profit_factor", "{:.2f}"),
        ("Avg hold (days)", "avg_hold_days", "{:.0f}"),
        ("Turnover (x/yr)", "turnover_annual", "{:.1f}"),
        ("Avg exposure", "avg_exposure", "{:.0%}"),
        ("Beta", "beta", "{:.2f}"), ("Alpha t-stat", "alpha_t", "{:.2f}"),
    ]:
        a = _fmt(dev.get(key), fmt)
        b = _fmt(vault.get(key), fmt)
        lines.append(f"| {label} | {a} | {b} |")

    lines += ["", "## Stability across folds", "",
              "| fold | period | Sharpe | return | max DD | trades |",
              "|---|---|---|---|---|---|"]
    for f in final.get("fold_metrics", []):
        lines.append(f"| {f['fold']} | {f['start']} → {f['end']} | {f['sharpe']:.2f} | "
                     f"{f['return']:.1%} | {f['max_drawdown']:.1%} | {f['n_trades']} |")

    pbo = final.get("pbo")
    lines += [
        "", "## Overfitting diagnostics", "",
        f"- **Deflated Sharpe**: {_fmt(gate.get('deflated_sharpe') or final.get('dev_gate', {}).get('deflated_sharpe'), '{:.3f}')} "
        "— probability the true Sharpe is positive given it won the search.",
        f"- **PBO**: {_fmt(pbo, '{:.3f}')} across {final.get('pbo_sample_size', 0)} configurations "
        "— share of CSCV splits where the in-sample winner lands in the bottom half out of sample. "
        "Near 0.5 means selection carries no information.",
        "",
        "## What changed versus the incumbent",
        "",
        "```",
        g.describe_diff(Genome(DEFAULTS)).replace("; ", "\n") or "(no changes)",
        "```",
        "",
        "## Rules, in full",
        "",
        "```json",
        json.dumps({k: g[k] for k in sorted(g.active_keys())}, indent=2),
        "```",
        "",
        "## Investigation findings on this configuration",
        "",
        "```",
        final.get("diagnostics", "(none)"),
        "```",
        "",
        "## Known limitations",
        "",
        ("- **Short sleeve is ON.** Borrow is modelled at a flat annual rate; real "
         "hard-to-borrow fees are far higher and can move daily, short interest is "
         "proxied by turnover rather than measured, and losses are unbounded. Paper-trade "
         "the short book separately before sizing it."
         if g.get("short.enabled") else
         "- Long-only. In a bear regime the strategy can only stand aside, which earns nothing."),
        "- Daily bars only. Intrabar sequencing is unknowable, so when one bar spans both "
        "the stop and the target the simulator books the loss — real fills may differ either way.",
        "- Delisted names are included, but historical index membership is not available on "
        "this data plan, so `universe.source = sp500` is survivorship-biased. Prefer `nyse_nasdaq`.",
        "- Sector labels are current, not point-in-time.",
        "- Costs are modelled (spread, slippage, commission, ADV-participation impact), not "
        "measured against real fills. Validate against a paper-traded period before sizing up.",
        "- The vault is a single out-of-sample period. It rejects overfitting; it does not "
        "prove the edge persists.",
        "",
        "## Before trading this",
        "",
        "1. Paper-trade `signals.py` for at least a full quarter and reconcile every fill "
        "against the assumed entry, stop and size.",
        "2. Re-run the vault evaluation once new data exists — decay is the expected outcome, "
        "the question is how fast.",
        "3. Size to the drawdown you can actually sit through, not the one in the table.",
    ]
    return "\n".join(lines)


def _fmt(v, fmt: str) -> str:
    try:
        f = float(v)
        return fmt.format(f) if np.isfinite(f) else "—"
    except (TypeError, ValueError):
        return "—"


# ----------------------------------------------------------------------
def live_signals(g: Genome, ctx, as_of: str | None = None, equity: float = 100_000.0,
                 top_n: int = 25) -> pd.DataFrame:
    """Today's orders from the deployed rule set.

    Uses the same signal construction as the backtest, evaluated at the most
    recent bar. Prices are the previous close; the order is a market-on-open for
    the next session, exactly as the simulator assumed.
    """
    from .strategy import build_signals

    # The pre-filter MUST come through here. Omitting it would let the live
    # signal generator trade names the backtested strategy could never have
    # touched — the deployed rules would not be the validated rules, and
    # nothing would raise. Same class of bug as emitting long-only orders from
    # a short-enabled genome.
    sig = build_signals(g, ctx.bank, ctx.sectors, ctx.bench_close,
                        prefilter=getattr(ctx, "prefilter", None))
    t = len(ctx.dates) - 1 if as_of is None else min(ctx.idx(as_of), len(ctx.dates) - 1)

    # Both sleeves. Emitting only longs when the deployed genome trades shorts
    # would be a silent live/backtest divergence — the deployed rules would not
    # be the rules that were validated.
    candidates: list[tuple[float, int, int]] = []
    if sig.regime_ok[t]:
        for j in np.flatnonzero(sig.trigger[t]):
            candidates.append((float(sig.score[t, j]), int(j), +1))
    if g["short.enabled"]:
        for j in np.flatnonzero(sig.short_trigger[t]):
            candidates.append((float(sig.short_score[t, j]), int(j), -1))

    if not candidates:
        note = (f"Regime filter is OFF as of {ctx.dates[t]} and no shorts triggered."
                if not sig.regime_ok[t] else "No entries today.")
        return pd.DataFrame([{"symbol": "-", "note": note}])

    candidates.sort(key=lambda x: -x[0])
    candidates = candidates[:top_n]

    close = ctx.panel.close[t]
    atr = sig.atr[t]
    rows = []
    for _score, j, side in candidates:
        px = float(close[j])
        a = float(atr[j])
        if side < 0:
            stop = px + g["short.stop_atr_mult"] * a
        elif g["exit.stop_type"] == "pct":
            stop = px * (1 - g["exit.stop_pct"] / 100.0)
        elif g["exit.stop_type"] == "ma":
            stop = float(sig.stop_ma[t, j])
        else:
            stop = px - g["exit.stop_atr_mult"] * a
        # The stop must sit on the losing side of the entry for this direction.
        if not np.isfinite(stop) or stop <= 0 or side * (px - stop) <= 0:
            continue
        risk_ps = side * (px - stop)
        if g["pf.sizing"] == "risk_atr":
            shares = equity * (g["pf.risk_pct"] / 100.0) / risk_ps
        elif g["pf.sizing"] == "equal_weight":
            shares = equity * min(g["pf.max_weight"],
                                  g["pf.max_gross_exposure"] / g["pf.max_positions"]) / px
        else:
            vol = a / px * np.sqrt(252.0)
            shares = equity * min(g["pf.max_weight"],
                                  g["pf.target_vol_annual"] / max(vol, 1e-6)) / px
        shares = min(shares, equity * g["pf.max_weight"] / px)
        target_r = g["short.target_r"] if side < 0 else g["exit.target_r"]
        rows.append({
            "symbol": ctx.panel.symbols[j],
            "side": "SHORT" if side < 0 else "LONG",
            "sector": ctx.sectors[j],
            "signal_date": str(ctx.dates[t]),
            "ref_close": round(px, 2),
            "entry": "market-on-open, next session",
            "stop": round(stop, 2),
            "target": round(px + side * target_r * risk_ps, 2) if target_r > 0 else None,
            "risk_per_share": round(abs(risk_ps), 2),
            "shares": int(max(0, shares)),
            "notional": round(shares * px, 0),
            "rank_score": round(float(_score), 4),
            "atr14": round(a, 2),
        })
    df = pd.DataFrame(rows)
    if not len(df):
        return df
    # Respect the per-side daily caps the backtest enforced.
    longs = df[df["side"] == "LONG"].head(int(g["pf.max_new_per_day"]))
    shorts = df[df["side"] == "SHORT"].head(int(g["short.max_positions"])
                                            if g["short.enabled"] else 0)
    return pd.concat([longs, shorts]).reset_index(drop=True)


# ----------------------------------------------------------------------
_SIGNALS_SCRIPT = '''"""Daily signal generator for the deployed strategy.

Run from the strategylab project root:

    python output/runs/<run_id>/deploy/signals.py --equity 100000

Reads the frozen genome next to this file, syncs recent prices, and prints the
orders for the next session. Uses the same signal code the backtest ran, so the
live rules cannot drift from the tested ones.
"""
import argparse
import json
import sys
from pathlib import Path

# .../<project>/output/runs/<run_id>/deploy/signals.py
#       parents[3]        [2]    [1]     [0]=HERE
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[3]))

from strategylab.config import LabConfig            # noqa: E402
from strategylab.data.prices import PriceStore      # noqa: E402
from strategylab.data.universe import UniverseBuilder  # noqa: E402
from strategylab.deploy import live_signals         # noqa: E402
from strategylab.genome import Genome               # noqa: E402
from strategylab.validation import build_context    # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--equity", type=float, default=100_000.0)
    ap.add_argument("--as-of", default=None, help="YYYY-MM-DD (default: latest bar)")
    ap.add_argument("--sync", action="store_true", help="refresh prices before running")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    spec = json.loads((HERE / "strategy.json").read_text())
    g = Genome(spec["genome"])
    cfg = LabConfig(run_id=spec["run_id"])
    # Restore the qualification screen the strategy was validated under.
    cfg.prefilter = spec.get("prefilter", "none")

    ub = UniverseBuilder()
    symbols = ub.symbols(g["universe.source"], include_delisted=False)
    store = PriceStore()
    cached = set(store.cached_symbols())
    symbols = [s for s in symbols if s in cached] or symbols[:800]
    if args.sync:
        store.sync(symbols + [cfg.benchmark], cfg.splits.warmup_start,
                   cfg.splits.vault_end, force=True)

    ctx = build_context(cfg, symbols, ub.sectors(symbols),
                        use_fundamentals=g["gates.use_fundamentals"],
                        use_news=g["gates.use_news"],
                        news_lookback=int(g["gates.news_lookback_days"]))
    df = live_signals(g, ctx, as_of=args.as_of, equity=args.equity)
    if args.json:
        print(df.to_json(orient="records", indent=2))
    elif df.empty:
        print("No entries today.")
    else:
        print(df.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


def _registry_script(g: Genome) -> str:
    """A market_screenings-compatible script for the swingtrader analytics app."""
    return f'''"""nis_evolved — strategy discovered by strategylab (genome {g.hash}).

Drop this into code/analytics/services/market_screenings/scripts/ and register
it in registry.py as "nis_evolved". It surfaces the same candidates the
deployed strategy would buy at the next open.

The rule set is frozen in GENOME below. Do not hand-edit it — re-run the lab
and re-export, so the rules on screen always match rules that were validated.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from ..types import ScreeningResult

log = logging.getLogger(__name__)

GENOME = {json.dumps(dict(g), indent=4)}

# .../code/analytics/services/market_screenings/scripts/nis_evolved.py
#      ^parents[4]      ^[3]      ^[2]     ^[1]              ^[0]
_STRATEGYLAB = Path(__file__).resolve().parents[4] / "strategylab"


def run(client, screening: dict) -> ScreeningResult:  # noqa: ARG001
    import sys
    sys.path.insert(0, str(_STRATEGYLAB))

    from strategylab.config import LabConfig
    from strategylab.data.universe import UniverseBuilder
    from strategylab.deploy import live_signals
    from strategylab.genome import Genome
    from strategylab.validation import build_context

    g = Genome(GENOME)
    cfg = LabConfig(run_id="deployed")
    ub = UniverseBuilder()
    symbols = ub.symbols(g["universe.source"], include_delisted=False)
    ctx = build_context(cfg, symbols, ub.sectors(symbols),
                        use_fundamentals=g["gates.use_fundamentals"],
                        use_news=g["gates.use_news"],
                        news_lookback=int(g["gates.news_lookback_days"]))
    df = live_signals(g, ctx)

    if df.empty:
        return ScreeningResult(triggered=False, summary=None, ticker_count=0,
                               data_used={{"genome_hash": "{g.hash}", "passed": 0}})

    rows = df.to_dict("records")
    lines = [f"• <b>{{r['symbol']}}</b> — {{r['sector']}} · stop {{r['stop']}}" for r in rows]
    summary = (f"<b>NIS Evolved</b>\\n{{len(rows)}} setup(s) for the next open\\n\\n"
               + "\\n".join(lines))
    return ScreeningResult(
        triggered=True, summary=summary, ticker_count=len(rows),
        data_used={{"genome_hash": "{g.hash}", "passed": len(rows), "symbols": rows}},
    )
'''
