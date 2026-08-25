"""Flow-Discriminated Pairs CLI.

    python -m strategylab.pairs.cli h1     [--limit N] [--out DIR]
    python -m strategylab.pairs.cli null   [--T 504]
    python -m strategylab.pairs.cli form   --window 0        # inspect one book

`h1` is the gate. It forms the pair book on DEV (2014-2023), collects every
divergence, splits it on the announcement discriminator, runs the pre-registered
battery, and states a verdict. The 2024-2026 window is then run ONCE as a
confirmation and is not permitted to change that verdict.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from ..config import OUTPUT_ROOT, LabConfig, load_env
from ..data.earnings import EarningsStore
from ..data.prices import PriceStore
from ..data.universe import UniverseBuilder
from ..flow.universe import listing_metadata
from . import anchor_study, charts, study
from .anchor import AnchorSpec, synthetic_null
from .discriminate import RegimeSpec, classify, coverage_report
from .events import EventSpec, collect_events, events_frame
from .formation import (FormationSpec, drop_non_sessions, eligible_mask,
                        etf_overlap_matrix, form_pairs, formation_windows,
                        null_distribution)

log = logging.getLogger(__name__)

PANEL_START = "2011-10-01"


def _etf_weights_loader(cache_dir: Path):
    def load(symbol: str):
        p = cache_dir / f"{symbol.replace('/', '_').replace('.', '-')}.json"
        if not p.exists():
            return []
        try:
            return json.loads(p.read_text())
        except Exception:
            return []
    return load


def _load(limit: int | None, end: str):
    load_env()
    ub = UniverseBuilder()
    ordered = [r["symbol"] for r in ub.membership("nyse_nasdaq", include_delisted=True)]
    store = PriceStore()
    cached = set(store.cached_symbols())
    symbols = [s for s in ordered if s in cached]
    if limit:
        symbols = symbols[:limit]
    panel = store.build_panel(symbols, PANEL_START, end, min_rows=400)
    panel, dropped = drop_non_sessions(panel)
    if dropped:
        log.warning("dropped %d non-session row(s) from the panel date index "
                    "(a vendor bar on a non-trading day NaNs every other name "
                    "and empties any formation window containing it): %s",
                    len(dropped), ", ".join(dropped[:8]))
    log.info("panel: %d sessions x %d symbols (%s .. %s)",
             panel.shape[0], panel.shape[1], panel.dates[0], panel.dates[-1])
    return panel


def _run_span(panel, label, start, end, fspec, espec, rspec, industries,
              earnings, etf_vectors, eligible, earnings_have):
    """Form pairs and collect classified events over one span of trading windows."""
    windows = formation_windows(panel, start, end, fspec)
    log.info("[%s] %d trading windows: %s .. %s", label, len(windows),
             windows[0]["trade_start"] if windows else "-",
             windows[-1]["trade_end"] if windows else "-")
    null = null_distribution(fspec.formation_days, fspec.adf_lags,
                             fspec.null_replications, fspec.seed)
    crit = float(np.quantile(null, fspec.coint_alpha))

    all_pairs, funnels = [], []
    for w in windows:
        pairs, funnel = form_pairs(panel, w, industries, fspec, eligible=eligible,
                                   earnings_have=earnings_have,
                                   etf_vectors=etf_vectors, null=null)
        funnel["window"] = w["window"]
        funnel["trade_start"] = w["trade_start"]
        funnel["pairs"] = len(pairs)
        funnels.append(funnel)
        all_pairs.extend(pairs)
        log.info("[%s] window %2d %s: %4d candidates -> %3d pairs",
                 label, w["window"], w["trade_start"],
                 funnel.get("candidate pairs (within industry)", 0), len(pairs))

    events = collect_events(panel, all_pairs, espec)
    df = events_frame(events)
    if len(df):
        df = classify(df, panel, earnings, rspec)
    log.info("[%s] %d pairs -> %d divergence events", label, len(all_pairs), len(df))

    traded = sorted({p.a for p in all_pairs} | {p.b for p in all_pairs})
    meta = {
        "span": [start, end],
        "windows": len(windows),
        "pairs_formed": len(all_pairs),
        "distinct_symbols_traded": len(traded),
        "events": int(len(df)),
        "simulated_critical_value": round(crit, 3),
        "median_pair_half_life": float(np.median([p.half_life for p in all_pairs]))
        if all_pairs else None,
        "median_pair_adf_t": float(np.median([p.adf_t for p in all_pairs]))
        if all_pairs else None,
        "announcement_coverage": coverage_report(panel, earnings, traded),
        "funnels": funnels,
    }
    return df, all_pairs, meta, null, crit


def cmd_h1(args) -> int:
    out_dir = Path(args.out or (OUTPUT_ROOT / "pairs" / "h1"))
    out_dir.mkdir(parents=True, exist_ok=True)

    cfg = LabConfig()
    fspec = FormationSpec()
    espec = EventSpec(cost_bps_per_side=(cfg.costs.commission_bps
                                         + cfg.costs.slippage_bps
                                         + cfg.costs.spread_bps))
    rspec = RegimeSpec()

    protocol = {
        "formation": fspec.__dict__, "events": espec.__dict__, "regimes": rspec.__dict__,
        "dev": [cfg.splits.dev_start, cfg.splits.dev_end],
        "vault": [cfg.splits.vault_start, cfg.splits.vault_end],
        "panel_start": PANEL_START,
        "protocol_version": cfg.protocol_version,
    }
    prereg = study.preregister(out_dir, protocol, notes=args.notes or "")
    log.info("pre-registered %d variants -> %s",
             prereg["n_variants"], out_dir / "preregistration.json")

    panel = _load(args.limit, cfg.splits.vault_end)
    industries = {s: (m or {}).get("industry") for s, m in listing_metadata().items()}
    earnings = EarningsStore().all_dates(list(panel.symbols))
    earnings_have = {s for s, d in earnings.items() if d}
    eligible = eligible_mask(panel, fspec)
    etf_vectors = etf_overlap_matrix(
        list(panel.symbols), _etf_weights_loader(Path(OUTPUT_ROOT) / "cache" / "etf_weights"))
    log.info("ETF exposure vectors for %d/%d names", len(etf_vectors), len(panel.symbols))

    dev, dev_pairs, dev_meta, null, crit = _run_span(
        panel, "dev", cfg.splits.dev_start, cfg.splits.dev_end,
        fspec, espec, rspec, industries, earnings, etf_vectors, eligible, earnings_have)

    if not len(dev):
        log.error("no divergence events on dev — nothing to test")
        return 2

    tests = study.run_tests(dev)
    diag = study.ou_implied_convergence(dev, horizon=espec.horizon)
    expl = study.exploratory(dev)
    expl["D1_ou_implied_vs_realized"] = diag
    expl["D2_drift_attribution"] = study.drift_attribution(panel, dev_pairs)
    verd = study.verdict(tests)

    # The vault: run ONCE, reported, never allowed to change the verdict.
    vault, _, vault_meta, _, _ = _run_span(
        panel, "vault", cfg.splits.vault_start, cfg.splits.vault_end,
        fspec, espec, rspec, industries, earnings, etf_vectors, eligible, earnings_have)
    vault_tests = study.run_tests(vault) if len(vault) else {}

    res = study.StudyResult(
        protocol=protocol,
        universe={"panel": list(panel.shape), "symbols": len(panel.symbols),
                  "first_session": str(panel.dates[0]), "last_session": str(panel.dates[-1])},
        formation={"dev": dev_meta, "vault": vault_meta},
        baseline=tests.get("P0_baseline_pairs_converge", {}),
        tests=tests, exploratory=expl, verdict=verd, preregistration=prereg)
    payload = res.to_dict()
    payload["vault_confirmation"] = {
        "meta": vault_meta,
        "tests": vault_tests,
        "note": ("Run once, after the dev verdict was fixed. It confirms or fails to "
                 "confirm; it does not overturn."),
    }

    (out_dir / "h1.json").write_text(json.dumps(payload, indent=2, default=str))
    dev.to_csv(out_dir / "events_dev.csv.gz", index=False, compression="gzip")
    if len(vault):
        vault.to_csv(out_dir / "events_vault.csv.gz", index=False, compression="gzip")
    pd.DataFrame([p.to_dict() for p in dev_pairs]).to_csv(
        out_dir / "pairs_dev.csv.gz", index=False, compression="gzip")

    if not args.no_charts:
        adf = np.array([p.adf_t for p in dev_pairs])
        paths = charts.write_all(dev, out_dir / "charts", null=null, adf=adf, crit=crit)
        log.info("charts: %s", ", ".join(Path(p).name for p in paths))

    (out_dir / "h1.md").write_text(_report(payload, dev, vault))
    _print(payload, dev, vault)
    return 0 if verd["h1_replicated"] else 1


def cmd_anchor(args) -> int:
    """Step 1 — is the stale anchor the problem, or is the reversion absent?"""
    out_dir = Path(args.out or (OUTPUT_ROOT / "pairs" / "anchor"))
    out_dir.mkdir(parents=True, exist_ok=True)

    cfg = LabConfig()
    fspec = FormationSpec()
    espec = EventSpec(cost_bps_per_side=(cfg.costs.commission_bps
                                         + cfg.costs.slippage_bps
                                         + cfg.costs.spread_bps))
    rspec = RegimeSpec()
    protocol = {"formation": fspec.__dict__, "events": espec.__dict__,
                "dev": [cfg.splits.dev_start, cfg.splits.dev_end],
                "null_pairs": args.null_pairs, "protocol_version": cfg.protocol_version}
    prereg = anchor_study.preregister(out_dir, protocol, notes=args.notes or "")
    n_var = prereg["n_variants"]
    log.info("pre-registered %d variants (%d anchors x %d tests) -> %s",
             n_var, len(anchor_study.ANCHORS), len(anchor_study.PREREGISTERED_TESTS),
             out_dir / "preregistration.json")

    panel = _load(args.limit, cfg.splits.dev_end)
    industries = {s: (m or {}).get("industry") for s, m in listing_metadata().items()}
    earnings = EarningsStore().all_dates(list(panel.symbols))
    earnings_have = {s for s, d in earnings.items() if d}
    eligible = eligible_mask(panel, fspec)

    windows = formation_windows(panel, cfg.splits.dev_start, cfg.splits.dev_end, fspec)
    null_dist = null_distribution(fspec.formation_days, fspec.adf_lags,
                                  fspec.null_replications, fspec.seed)
    crit = float(np.quantile(null_dist, fspec.coint_alpha))

    pairs = []
    for w in windows:
        got, _ = form_pairs(panel, w, industries, fspec, eligible=eligible,
                            earnings_have=earnings_have, null=null_dist)
        pairs.extend(got)
    log.info("formed %d pairs over %d windows — the SAME book for every anchor",
             len(pairs), len(windows))

    results, frames = {}, {}
    for name, anchor in anchor_study.ANCHORS.items():
        df = events_frame(collect_events(panel, pairs, espec, anchor=anchor))
        if not len(df):
            log.warning("%s produced no events", name)
            continue
        df = classify(df, panel, earnings, rspec)
        null = synthetic_null(anchor, espec, fspec, crit,
                              n_keep=args.null_pairs, seed=fspec.seed + 20)
        res = anchor_study.run_anchor(df, null, n_variants=n_var)
        res["anchor"] = anchor.label
        if name == "A0_frozen":
            res["G0_null_reproduces_the_analytic_random_walk_rate"] = {
                "analytic": anchor_study.analytic_rw_benchmark(df),
                "simulated": null.get("convergence"),
                "note": ("These two must agree for the frozen anchor, where z is "
                         "close to a random walk under the null. They are computed "
                         "by completely different routes, so agreement validates "
                         "the simulation that scores every other anchor."),
            }
        results[name] = res
        frames[name] = df
        log.info("%-28s events %5d  realised %.1f%%  null %.1f%%  excess %+.1fpp",
                 name, len(df), 100 * df["converged"].mean(),
                 100 * null.get("convergence", float("nan")),
                 100 * res.get("G1_excess_convergence_over_matched_null", {})
                 .get("excess", float("nan")))

    verd = anchor_study.verdict(results)
    payload = anchor_study.AnchorResult(protocol=protocol, anchors=results,
                                        verdict=verd, preregistration=prereg).to_dict()
    (out_dir / "anchor.json").write_text(json.dumps(payload, indent=2, default=str))
    for name, df in frames.items():
        df.to_csv(out_dir / f"events_{name}.csv.gz", index=False, compression="gzip")

    _print_anchor(payload)
    return 0 if verd["anchor_repair_succeeds"] else 1


def _print_anchor(payload: dict) -> None:
    a, v = payload["anchors"], payload["verdict"]
    print("\n" + "=" * 84)
    print("FDP Step 1 — re-anchoring: is the mean reversion recoverable?")
    print("=" * 84)
    g0 = a.get("A0_frozen", {}).get("G0_null_reproduces_the_analytic_random_walk_rate")
    if g0 and g0["analytic"].get("available"):
        print(f"G0 validity   frozen anchor: analytic random-walk benchmark "
              f"{g0['analytic']['mean']:.1%}  vs simulated null {g0['simulated']:.1%}"
              f"   (agreement validates the simulation)\n")
    print(f"{'anchor':<30} {'events':>7} {'realised':>9} {'null':>8} {'excess':>9} "
          f"{'t':>7} {'wins':>7} {'net/ev':>9}")
    print("-" * 84)
    for name, r in a.items():
        g1 = r.get("G1_excess_convergence_over_matched_null", {})
        e = r.get("economics", {})
        if not g1.get("available"):
            continue
        print(f"{name:<30} {g1['n']:>7} {g1['realised']:>8.1%} {g1['null']:>7.1%} "
              f"{g1['excess']:>+8.1%} {g1['t']:>+7.2f} "
              f"{g1['windows_positive']:>3}/{g1['clusters']:<3} "
              f"{e.get('net_clustered', float('nan')):>+9.4f}")
    print("-" * 84)
    ph = a.get("A0_frozen", {}).get("POSTHOC_by_cointegration_strength", {})
    if ph.get("quartiles"):
        print("\npost-hoc: does the negative survive inside the STRONGEST pairs? "
              "(frozen anchor)")
        print(f"   {'quartile':<14} {'real':>7} {'null':>7} {'excess':>8}  median ADF real/null")
        for k, r in ph["quartiles"].items():
            print(f"   {k:<14} {r['real']:>6.1%} {r['null']:>6.1%} {r['excess']:>+7.1%}"
                  f"   {r['real_median_adf']:>6.2f} / {r['null_median_adf']:.2f}")

    prim = a.get(v["primary"], {})
    g3 = prim.get("G3_discriminator_survives_the_new_anchor", {})
    if g3.get("available"):
        print(f"G3 discriminator under {v['primary']}: L {g3['mean_hi']:.1%} vs "
              f"N {g3['mean_lo']:.1%}, diff {g3['diff']:+.1%}, t {g3['t']:+.2f} "
              f"-> {'PASS' if g3.get('pass') else 'fail'}")
    print(f"\nVERDICT: anchor repair "
          f"{'SUCCEEDS' if v['anchor_repair_succeeds'] else 'FAILS'}")
    for k, ok in v["conditions"].items():
        print(f"   [{'x' if ok else ' '}] {k}")
    print(f"\n{v['recommendation']}")
    print("=" * 84 + "\n")


def cmd_null(args) -> int:
    null = null_distribution(args.T, args.lags, args.replications, args.seed)
    print(f"Simulated Engle-Granger residual-ADF null  (T={args.T}, lags={args.lags}, "
          f"{len(null)} replications)")
    for q in (0.01, 0.05, 0.10):
        print(f"   {q:>5.0%} critical value   {np.quantile(null, q):+.3f}")
    print(f"   median              {np.median(null):+.3f}")
    print("\nFor reference, MacKinnon's asymptotic values for the 2-variable case with "
          "a constant are about -3.90 / -3.34 / -3.04.")
    return 0


def cmd_form(args) -> int:
    load_env()
    cfg = LabConfig()
    fspec = FormationSpec()
    panel = _load(args.limit, cfg.splits.vault_end)
    industries = {s: (m or {}).get("industry") for s, m in listing_metadata().items()}
    earnings = EarningsStore().all_dates(list(panel.symbols))
    windows = formation_windows(panel, cfg.splits.dev_start, cfg.splits.dev_end, fspec)
    w = windows[min(args.window, len(windows) - 1)]
    pairs, funnel = form_pairs(panel, w, industries, fspec,
                               earnings_have={s for s, d in earnings.items() if d})
    print(f"Window {w['window']}: form {w['formation_start']}..{w['formation_end']}  "
          f"trade {w['trade_start']}..{w['trade_end']}")
    for k, v in funnel.items():
        print(f"   {str(k):<44} {v}")
    print()
    for p in pairs[:args.show]:
        print(f"   {p.a:>6} / {p.b:<6} {p.industry:<28} beta {p.beta:5.2f}  "
              f"ADF {p.adf_t:6.2f}  half-life {p.half_life:5.1f}d  "
              f"overlap {p.etf_overlap:.2f}")
    return 0


# ----------------------------------------------------------------------
def _fmt(r: dict) -> str:
    if not r or not r.get("available", True):
        return f"      unavailable ({r.get('reason', 'n/a')})"
    if "diff" not in r:
        return ""
    mark = "PASS" if r.get("pass") else "fail"
    return (f"      {r['hi']} {r['mean_hi']:+.4f}  vs  {r['lo']} {r['mean_lo']:+.4f}   "
            f"diff {r['diff']:+.4f}  t {r['t']:+.2f}  p {r.get('p_used', float('nan')):.4f}  "
            f"[{r['clusters']} windows, n={r['n_hi']}/{r['n_lo']}]  -> {mark}")


def _print(payload: dict, dev, vault) -> None:
    t = payload["tests"]
    v = payload["verdict"]
    print("\n" + "=" * 78)
    print("FDP H1 — the EGJ news-axis replication (positive control)")
    print("=" * 78)
    m = payload["formation"]["dev"]
    print(f"dev  {m['span'][0]} .. {m['span'][1]}   {m['windows']} windows, "
          f"{m['pairs_formed']} pairs, {m['events']} divergences, "
          f"{m['distinct_symbols_traded']} names")
    cov = m["announcement_coverage"]
    print(f"announcement coverage {cov['coverage']:.1%} of traded names "
          f"({'clean' if cov['clean'] else 'INCOMPLETE — L bucket is contaminated'})")
    p0 = t["P0_baseline_pairs_converge"]
    print(f"\nP0 baseline    convergence {p0['convergence_rate']['mean']:.1%}  "
          f"gross {p0['gross_return']['mean']:+.4f}  net {p0['net_return']['mean']:+.4f}  "
          f"-> {'PASS' if p0['pass'] else 'fail'}")
    d2 = payload["exploratory"].get("D2_drift_attribution", {})
    if d2.get("available"):
        print(f"D2 diagnostic  mean |spread drift| {d2['mean_abs_drift_z']:.2f}z, and its "
              f"correlation with leg-B travel is {d2['corr_drift_vs_leg_b_move']:+.3f} "
              f"(p {d2['corr_p_value']:.3f}) -> {d2['verdict']}")
    d1 = payload["exploratory"].get("D1_ou_implied_vs_realized", {})
    if d1.get("available"):
        print(f"D1 diagnostic  the formation OU fits implied "
              f"{d1['ou_implied_convergence']:.1%} convergence; realised "
              f"{d1['realised_convergence']:.1%}  (gap {d1['gap']:+.1%}, "
              f"t {d1['gap_t_over_windows']:+.2f} over windows)")
    print(f"Bonferroni     alpha {t['alpha_nominal']} / {t['n_variants']} variants "
          f"= {t['alpha_bonferroni']:.5f}\n")
    for name in study.PREREGISTERED_TESTS[1:]:
        print(f"   {name}")
        print(_fmt(t.get(name, {})))
    print("\n" + "-" * 78)
    print(f"VERDICT: H1 {'REPLICATES' if v['h1_replicated'] else 'DOES NOT replicate'}")
    for k, ok in v["conditions"].items():
        print(f"   [{'x' if ok else ' '}] {k}")
    print(f"   corroborating: {v['n_corroborating_passed']}/{v['n_corroborating']}")
    print(f"\n{v['recommendation']}")
    vt = payload.get("vault_confirmation", {}).get("tests", {})
    if vt:
        r = vt.get("H1a_convergence_rate_L_gt_N", {})
        print(f"\nvault 2024-2026 (confirmation only): H1a diff {r.get('diff', float('nan')):+.4f} "
              f"t {r.get('t', float('nan')):+.2f} over {r.get('clusters', 0)} windows")
    print("=" * 78 + "\n")


def _report(payload: dict, dev, vault) -> str:
    t, v = payload["tests"], payload["verdict"]
    m = payload["formation"]["dev"]
    lines = ["# FDP H1 — EGJ news-axis replication", "",
             f"**Verdict: H1 {'replicates' if v['h1_replicated'] else 'does NOT replicate'}.**", "",
             f"- dev {m['span'][0]} .. {m['span'][1]}, {m['windows']} non-overlapping "
             f"6-month trading windows",
             f"- {m['pairs_formed']} cointegrated pairs across {m['distinct_symbols_traded']} names",
             f"- {m['events']} divergence events at |z| > 2",
             f"- announcement coverage {m['announcement_coverage']['coverage']:.1%}",
             f"- simulated Engle-Granger critical value {m['simulated_critical_value']}",
             "", "## Pre-registered tests", "",
             "| test | hi | lo | diff | t | p | windows | pass |",
             "|---|---|---|---|---|---|---|---|"]
    for name in study.PREREGISTERED_TESTS[1:]:
        r = t.get(name, {})
        if not r.get("available", False) or "diff" not in r:
            lines.append(f"| {name} | — | — | — | — | — | — | n/a |")
            continue
        lines.append(f"| {name} | {r['hi']} {r['mean_hi']:+.4f} | {r['lo']} {r['mean_lo']:+.4f} | "
                     f"{r['diff']:+.4f} | {r['t']:+.2f} | {r.get('p_used', float('nan')):.4f} | "
                     f"{r['clusters']} | {'yes' if r.get('pass') else 'no'} |")
    lines += ["", "## Verdict conditions", ""]
    for k, ok in v["conditions"].items():
        lines.append(f"- [{'x' if ok else ' '}] {k}")
    lines += ["", f"{v['recommendation']}", "",
              "## Exploratory (NOT pre-registered)", "",
              "```json", json.dumps(payload["exploratory"], indent=2, default=str)[:4000], "```"]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="strategylab.pairs")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("h1", help="the EGJ news-axis replication — the gate")
    p.add_argument("--limit", type=int, default=None, help="cap the symbol count (smoke runs)")
    p.add_argument("--out", default=None)
    p.add_argument("--notes", default=None)
    p.add_argument("--no-charts", action="store_true")
    p.set_defaults(func=cmd_h1)

    p = sub.add_parser("anchor", help="Step 1 — re-anchoring vs a matched null")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--out", default=None)
    p.add_argument("--notes", default=None)
    p.add_argument("--null-pairs", type=int, default=4000,
                   help="spurious pairs to build each matched null from")
    p.set_defaults(func=cmd_anchor)

    p = sub.add_parser("null", help="simulated Engle-Granger critical values")
    p.add_argument("--T", type=int, default=504)
    p.add_argument("--lags", type=int, default=1)
    p.add_argument("--replications", type=int, default=4000)
    p.add_argument("--seed", type=int, default=11)
    p.set_defaults(func=cmd_null)

    p = sub.add_parser("form", help="inspect one window's pair book")
    p.add_argument("--window", type=int, default=0)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--show", type=int, default=25)
    p.set_defaults(func=cmd_form)

    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
