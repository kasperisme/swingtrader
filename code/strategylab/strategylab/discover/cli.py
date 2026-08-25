"""Discovery-loop CLI.

    python -m strategylab.discover.cli run [--iterations N] [--minutes M]
    python -m strategylab.discover.cli status

The loop is resumable. The registry persists, so a run started tomorrow
inherits today's trial count — and therefore today's higher bar.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from ..config import OUTPUT_ROOT, LabConfig
from ..momentum.cli import _load as _load_panel
from ..momentum.universe import UniverseSpec, pin_universe
from ..setups.detect import SetupSpec, detect_setups, pseudo_setups
from ..setups.outcomes import OutcomeSpec, resolve_setups
from .execute import Context
from .hypothesis import HypothesisSpace
from .loop import DiscoveryLoop, LoopConfig, significance_bar
from .registry import Registry

log = logging.getLogger(__name__)


def _build_context(args, cfg: LabConfig):
    panel, bank = _load_panel(args.limit, "2004-01-01", cfg.splits.vault_end)
    uni = pin_universe(panel, bank, UniverseSpec())
    dev = (panel.date_index(cfg.splits.dev_start),
           min(panel.shape[0], panel.date_index(cfg.splits.dev_end) + 1))
    vault = (panel.date_index(cfg.splits.vault_start),
             min(panel.shape[0], panel.date_index(cfg.splits.vault_end) + 1))
    log.info("universe [%s] median %d names/day", uni.fingerprint[:12],
             uni.stats()["median_names_per_day"])

    setups = controls = None
    if not args.no_setups:
        cost = cfg.costs.commission_bps + cfg.costs.slippage_bps + cfg.costs.spread_bps
        sspec = SetupSpec(trigger="pullback", require_volume=False,
                          cost_bps_per_side=cost)
        ospec = OutcomeSpec(max_hold=60, cost_bps_per_side=cost)
        rs, _ = detect_setups(panel, bank, uni.mask, sspec)
        fs, _ = pseudo_setups(panel, bank, uni.mask, sspec)
        setups = resolve_setups(panel, rs, ospec)
        controls = resolve_setups(panel, fs, ospec)
        for d in (setups, controls):
            if not d.empty:
                d["date"] = pd.to_datetime(d["date"])
        log.info("setup book: %d pullback entries, %d controls", len(setups), len(controls))
    return Context(panel, bank, uni.mask, dev, vault, setups, controls), uni


def cmd_run(args) -> int:
    cfg = LabConfig()
    out_dir = Path(args.out or (OUTPUT_ROOT / "discover"))
    out_dir.mkdir(parents=True, exist_ok=True)
    reg = Registry(out_dir / "registry.sqlite")
    ctx, uni = _build_context(args, cfg)
    space = HypothesisSpace()

    lcfg = LoopConfig(max_iterations=args.iterations,
                      rung0_batch=args.batch, promote_top=args.promote,
                      time_budget_s=args.minutes * 60.0 if args.minutes else 0.0)
    loop = DiscoveryLoop(ctx, reg, space, lcfg)
    log.info("space %d hypotheses; %d already tested; bar now |t| > %.2f",
             space.size(), reg.n_tested(), significance_bar(max(1, reg.n_tested())))

    def on_step(out):
        if out.get("done"):
            return
        best = max((r["t_stat"] for r in out["results"]
                    if r.get("t_stat") is not None and np.isfinite(r["t_stat"])),
                   key=abs, default=float("nan"))
        log.info("iter %3d  tested %4d  bar |t|>%.2f  best this iter %+.2f%s",
                 loop.state.iterations, out["tested_total"], out["bar"], best,
                 "  <-- CLEARED" if any(r["cleared"] for r in out["results"]) else "")

    state = loop.run(on_step=on_step)
    summary = reg.summary() | {"stopped_because": state.stopped_because,
                               "iterations": state.iterations,
                               "space_size": space.size(),
                               "bar_now": significance_bar(max(1, reg.n_tested())),
                               "universe": uni.fingerprint}
    (out_dir / "summary.json").write_text(json.dumps(
        summary | {"best": reg.best(15), "confirmed": reg.confirmed()},
        indent=2, default=str))
    _print(reg, summary)
    return 0 if summary["confirmed"] else 1


def cmd_status(args) -> int:
    out_dir = Path(args.out or (OUTPUT_ROOT / "discover"))
    reg = Registry(out_dir / "registry.sqlite")
    s = reg.summary()
    _print(reg, s | {"stopped_because": "-", "space_size": HypothesisSpace().size(),
                     "bar_now": significance_bar(max(1, s["tested"]))})
    return 0


def _print(reg: Registry, s: dict) -> None:
    print("\n" + "=" * 96)
    print("DISCOVERY LOOP — hypotheses tested against a bar that rises with the trial count")
    print("=" * 96)
    print(f"space {s.get('space_size')} hypotheses | registered {s['registered']} | "
          f"tested {s['tested']} | cleared {s['cleared']} | confirmed {s['confirmed']}")
    print(f"significance bar now |t| > {s.get('bar_now', float('nan')):.2f}   "
          f"(max |t| seen {s.get('max_abs_t') or float('nan'):.2f}, "
          f"mean {s.get('mean_abs_t') or float('nan'):.2f})")
    print(f"stopped: {s.get('stopped_because')}\n")

    rows = reg.best(12)
    if rows:
        print(f"{'hypothesis':<44}{'rung':>5}{'effect':>10}{'t':>8}{'bar':>7}"
              f"{'placebo t':>11}{'cleared':>9}")
        for r in rows:
            print(f"{r['name']:<44}{r['rung']:>5}"
                  f"{(r['effect'] or 0):>+10.4f}{(r['t_stat'] or 0):>+8.2f}"
                  f"{(r['bar'] or 0):>7.2f}{(r['placebo_t'] or 0):>+11.2f}"
                  f"{'YES' if r['cleared'] else '-':>9}")
    conf = reg.confirmed()
    print()
    if conf:
        print("CONFIRMED (cleared the bar on dev AND held out of sample):")
        for r in conf:
            print(f"   {r['name']}  dev t {r['t_stat']:+.2f}  vault t {r['vault_t']:+.2f}")
    else:
        print("No hypothesis has cleared the bar and confirmed out of sample.")
        print("That is a result: the maximum |t| seen is what a search of this size")
        print("produces from noise alone.")
    print("=" * 96 + "\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="strategylab.discover")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("run", help="iterate: propose, test, raise the bar")
    p.add_argument("--iterations", type=int, default=200)
    p.add_argument("--batch", type=int, default=12)
    p.add_argument("--promote", type=int, default=3)
    p.add_argument("--minutes", type=float, default=0.0)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--no-setups", action="store_true")
    p.add_argument("--out", default=None)
    p.set_defaults(func=cmd_run)
    p = sub.add_parser("status", help="what the registry knows")
    p.add_argument("--out", default=None)
    p.set_defaults(func=cmd_status)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
