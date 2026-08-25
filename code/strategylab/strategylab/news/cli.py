"""News-repricing CLI.

    python -m strategylab.news.cli nrp [--limit N] [--horizon 21]

Builds every earnings announcement on the cached panel, measures the surprise
as an abnormal return over [D-1, D+1], measures what happens from D+2 onward,
and scores it against the same measurement performed on days when nothing was
announced.
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
from ..pairs.formation import drop_non_sessions
from . import study
from .eventstudy import (EventSpec, assign_buckets, build_events, liquidity_tier,
                         market_model, pseudo_events, winsorize)

log = logging.getLogger(__name__)

PANEL_START = "1997-01-01"


def _load(limit: int | None, end: str):
    load_env()
    ub = UniverseBuilder()
    ordered = [r["symbol"] for r in ub.membership("nyse_nasdaq", include_delisted=True)]
    store = PriceStore()
    cached = set(store.cached_symbols())
    symbols = [s for s in ordered if s in cached]
    if "SPY" in cached and "SPY" not in symbols:
        symbols.append("SPY")
    if limit:
        symbols = symbols[:limit] + (["SPY"] if "SPY" in cached else [])
    panel = store.build_panel(sorted(set(symbols)), PANEL_START, end, min_rows=300)
    panel, dropped = drop_non_sessions(panel)
    if dropped:
        log.warning("dropped %d non-session row(s): %s", len(dropped),
                    ", ".join(dropped[:6]))
    log.info("panel: %d sessions x %d symbols (%s .. %s)", panel.shape[0],
             panel.shape[1], panel.dates[0], panel.dates[-1])
    return panel


def _slice(df: pd.DataFrame, start: str, end: str) -> pd.DataFrame:
    d = pd.to_datetime(df["date"])
    return df[(d >= pd.Timestamp(start)) & (d <= pd.Timestamp(end))]


def cmd_nrp(args) -> int:
    out_dir = Path(args.out or (OUTPUT_ROOT / "news" / "nrp"))
    out_dir.mkdir(parents=True, exist_ok=True)

    cfg = LabConfig()
    spec = EventSpec(cost_bps_per_side=(cfg.costs.commission_bps
                                        + cfg.costs.slippage_bps
                                        + cfg.costs.spread_bps))
    protocol = {"events": {k: (list(v) if isinstance(v, tuple) else v)
                           for k, v in spec.__dict__.items()},
                "horizons": list(spec.drift_horizons),
                "primary_horizon": args.horizon,
                "dev": [cfg.splits.dev_start, cfg.splits.dev_end],
                "vault": [cfg.splits.vault_start, cfg.splits.vault_end],
                "pre_era": [cfg.splits.holdout_start, cfg.splits.holdout_end],
                "panel_start": PANEL_START, "market": "SPY",
                "protocol_version": cfg.protocol_version}
    prereg = study.preregister(out_dir, protocol, notes=args.notes or "")
    n_var = prereg["n_variants"]
    log.info("pre-registered %d variants -> %s", n_var, out_dir / "preregistration.json")

    panel = _load(args.limit, cfg.splits.vault_end)
    AB, beta, sigma, m = market_model(panel, market="SPY", spec=spec)
    log.info("market model built: abnormal-return coverage %.1f%%",
             100 * float(np.isfinite(AB).mean()))
    adv = pd.DataFrame(panel.close * panel.volume).rolling(20, min_periods=10).mean().to_numpy()

    earnings = EarningsStore().all_dates(list(panel.symbols))
    earnings = {k: v for k, v in earnings.items() if v and k != "SPY"}
    tiers = liquidity_tier(adv)
    real = build_events(panel, earnings, spec, AB, beta, sigma, m, adv)
    fake = pseudo_events(panel, earnings, spec, AB, beta, sigma, m, adv, tiers)
    log.info("events: %d announcements, %d day- and tier-matched pseudo-events",
             len(real), len(fake))

    wins = winsorize(real, fake, spec)
    log.info("winsorised at %.0f%%/%.0f%%; %d return observations beyond +/-%.0f%% "
             "(unadjusted corporate actions) were clipped",
             100 * spec.winsorize_pct, 100 * (1 - spec.winsorize_pct),
             sum(wins["absurd"].values()), 100 * spec.absurd_return)

    for df in (real, fake):
        df["tier"] = liquidity_tier(df["adv"].to_numpy())
    real = assign_buckets(real, spec)
    fake = assign_buckets(fake, spec)
    log.info("bucketed: %d announcements, %d pseudo-events carry a decile",
             int(real["bucket"].notna().sum()), int(fake["bucket"].notna().sum()))

    H = args.horizon
    dev_r = _slice(real, cfg.splits.dev_start, cfg.splits.dev_end)
    dev_f = _slice(fake, cfg.splits.dev_start, cfg.splits.dev_end)
    tests = study.run_tests(dev_r, dev_f, spec, H, n_variants=n_var)
    tiers = study.by_tier(dev_r, dev_f, spec, H)
    verd = study.verdict(tests)

    eras = {}
    for name, (a, b) in (("vault_2024_2026", (cfg.splits.vault_start, cfg.splits.vault_end)),
                         ("pre_era_1998_2013", (cfg.splits.holdout_start,
                                                cfg.splits.holdout_end))):
        r_, f_ = _slice(real, a, b), _slice(fake, a, b)
        if len(r_) < 500:
            continue
        eras[name] = {"events": int(len(r_)),
                      "tests": study.run_tests(r_, f_, spec, H, n_variants=n_var),
                      "tiers": study.by_tier(r_, f_, spec, H)}

    expl = {"winsorisation": wins, "by_horizon": {}}
    for h in spec.drift_horizons:
        sp = study.spread_series(dev_r, f"ret_{h}", spec.n_buckets)
        c = study._cluster(sp.to_numpy())
        if c.get("available"):
            expl["by_horizon"][f"H{h}"] = {
                "gross": c["mean"], "t": c["t"],
                "net": c["mean"] - 4 * spec.cost_bps_per_side * 1e-4,
                "cost_share_of_gross": (float(4 * spec.cost_bps_per_side * 1e-4 / c["mean"])
                                        if c["mean"] > 0 else None)}

    expl["POSTHOC_reversal_asymmetry"] = {
        "dev": study.posthoc_reversal_asymmetry(dev_r, dev_f, spec, H),
        "vault": study.posthoc_reversal_asymmetry(
            _slice(real, cfg.splits.vault_start, cfg.splits.vault_end),
            _slice(fake, cfg.splits.vault_start, cfg.splits.vault_end), spec, H),
        "pre_era": study.posthoc_reversal_asymmetry(
            _slice(real, cfg.splits.holdout_start, cfg.splits.holdout_end),
            _slice(fake, cfg.splits.holdout_start, cfg.splits.holdout_end), spec, H),
        "vault_use_note": ("This is a SECOND use of the sealed vault. The first was "
                           "the registered era report. A holdout tested repeatedly "
                           "is a training set."),
    }

    res = study.NRPResult(
        protocol=protocol,
        universe={"panel": list(panel.shape), "symbols": len(panel.symbols),
                  "announcements": int(len(real)), "pseudo_events": int(len(fake)),
                  "dev_announcements": int(len(dev_r))},
        tests=tests, tiers=tiers, eras=eras, exploratory=expl,
        verdict=verd, preregistration=prereg)
    payload = res.to_dict()
    (out_dir / "nrp.json").write_text(json.dumps(payload, indent=2, default=str))
    keep = [c for c in real.columns if c != "col"]
    real[keep].to_csv(out_dir / "events.csv.gz", index=False, compression="gzip")
    fake[keep].to_csv(out_dir / "pseudo_events.csv.gz", index=False, compression="gzip")

    _print(payload, spec, H)
    return 0 if verd["effect_is_real_and_tradeable"] else 1


def _print(payload: dict, spec, H: int) -> None:
    t, v, u = payload["tests"], payload["verdict"], payload["universe"]
    print("\n" + "=" * 86)
    print(f"NRP Stage 1 — news repricing / post-announcement drift  (horizon {H}d)")
    print("=" * 86)
    print(f"{u['announcements']:,} announcements and {u['pseudo_events']:,} matched "
          f"pseudo-events over {u['symbols']} names; dev {u['dev_announcements']:,}")

    tbl = t.get("bucket_means_ret", {})
    if tbl:
        print(f"\nmean market-hedged return over {H}d, by surprise decile "
              f"(0 = worst news, 9 = best):")
        line = "   " + "".join(f"{k:>7}" for k in sorted(tbl))
        vals = "   " + "".join(f"{tbl[k]['mean']*100:>+7.2f}" for k in sorted(tbl))
        print(line + "\n" + vals + "   (%)")
    mono = t.get("P1_drift_is_monotone_in_the_surprise", {})
    if mono.get("available"):
        print(f"\nP1 monotonicity   Spearman {mono['spearman']:+.3f} over "
              f"{mono['buckets']} deciles -> {'PASS' if mono.get('pass') else 'fail'}")

    def row(name, r, unit="%"):
        if not r or not r.get("available"):
            print(f"   {name:<46} unavailable")
            return
        mark = "PASS" if r.get("pass") else "fail"
        print(f"   {name:<46} {r['mean']*100:>+7.3f}{unit}  t {r['t']:>+6.2f}  "
              f"p {r.get('p_one_sided', r.get('p_two_sided', float('nan'))):.4f}  "
              f"[{r['months']}m]  -> {mark}")

    print(f"\nBonferroni alpha {t['alpha_bonferroni']:.5f}")
    row("P2 top-minus-bottom spread (gross)", t.get("P2_top_minus_bottom_spread_is_positive"))
    row("   ...same spread on pseudo-events", t.get("pseudo_spread"))
    row("N1 EXCESS over pseudo-events", t.get("N1_excess_over_the_pseudo_event_control"))
    row("N2 shuffled labels (must be null)", t.get("N2_placebo_surprise_labels_are_null"))
    row("E1 spread net of costs", t.get("E1_spread_survives_costs"))
    row("E2 long-only top decile, net", t.get("E2_long_only_leg_survives_costs"))

    tiers = payload.get("tiers", {})
    if tiers:
        print(f"\nby liquidity tier (dev, {H}d spread) — where the edge sits vs the friction:")
        print(f"   {'tier':<20} {'events':>8} {'gross':>8} {'net':>8} {'t':>7} "
              f"{'cost/gross':>11} {'excess':>8}")
        for k in sorted(tiers):
            r = tiers[k]
            cs = r.get("cost_share_of_gross")
            ex = r.get("excess_over_pseudo")
            print(f"   {k:<20} {r['events']:>8,} {r['gross']*100:>+7.2f}% "
                  f"{r['net']*100:>+7.2f}% {r['t']:>+7.2f} "
                  f"{(f'{cs:.0%}' if cs is not None else 'n/a'):>11} "
                  f"{(f'{ex*100:+.2f}%' if ex is not None else 'n/a'):>8}")

    eras = payload.get("eras", {})
    for name, e in eras.items():
        n1 = e["tests"].get("N1_excess_over_the_pseudo_event_control", {})
        p2 = e["tests"].get("P2_top_minus_bottom_spread_is_positive", {})
        if p2.get("available"):
            print(f"\n{name}: {e['events']:,} events, gross {p2['mean']*100:+.2f}% "
                  f"(t {p2['t']:+.2f}), excess over pseudo "
                  f"{(n1.get('mean') or 0)*100:+.2f}% (t {n1.get('t', float('nan')):+.2f})")

    ph = payload.get("exploratory", {}).get("POSTHOC_reversal_asymmetry", {})
    if ph:
        print("\nPOST-HOC (found in the control, NOT pre-registered) — fade an extreme")
        print("move when no announcement is near it; do not when one is:")
        print(f"   {'era':<10} {'tier':<20} {'no-news':>9} {'news':>9} "
              f"{'asymmetry':>11} {'t':>7} {'net':>8}")
        for era in ("dev", "vault", "pre_era"):
            for k, r in (ph.get(era, {}).get("tiers", {}) or {}).items():
                if not k.startswith(("T3", "T4")):
                    continue
                print(f"   {era:<10} {k:<20} {r['fade_no_news_gross']*100:>+8.2f}% "
                      f"{r['fade_news_gross']*100:>+8.2f}% {r['asymmetry']*100:>+10.2f}% "
                      f"{r['asymmetry_t']:>+7.2f} {r['fade_no_news_net']*100:>+7.2f}%")

    print("\n" + "-" * 86)
    print(f"VERDICT: the effect is "
          f"{'REAL AND TRADEABLE' if v['effect_is_real_and_tradeable'] else 'NOT tradeable as specified'}")
    for k, ok in v["conditions"].items():
        print(f"   [{'x' if ok else ' '}] {k}")
    print(f"\n{v['recommendation']}")
    print("=" * 86 + "\n")


def cmd_impact(args) -> int:
    """Does the news overlay add anything the price data does not already have?

    Reported with its power floor in front, because the pipeline covers sixteen
    months and a null on an underpowered sample means "not resolvable", not
    "not present".
    """
    from ..momentum import ic as icmod
    from ..momentum.cli import _load as _load_mom
    from ..momentum.signals import CONTROLS, compute_all
    from ..momentum.universe import UniverseSpec, pin_universe
    from ..setups.detect import SetupSpec, detect_setups, pseudo_setups
    from ..setups.outcomes import OutcomeSpec, resolve_setups
    from ..setups.study import conditioner_report
    from .overlay import (NEWS_SIGNALS, build_news_matrices, coverage_report,
                          minimum_detectable_ic)

    cfg = LabConfig()
    out_dir = Path(args.out or (OUTPUT_ROOT / "news" / "impact"))
    out_dir.mkdir(parents=True, exist_ok=True)

    panel, bank = _load_mom(args.limit, "2004-01-01", args.end)
    uni = pin_universe(panel, bank, UniverseSpec())
    mats = build_news_matrices(panel, lookback=args.lookback)
    cov = coverage_report(panel, uni.mask, mats)
    log.info("news covers %d sessions, median %d universe names/day (%.0f%% of the "
             "cross-section)", cov["covered_sessions"],
             cov["median_universe_names_with_news"], 100 * cov["median_share_of_universe_with_news"])

    first = panel.date_index(cov["first_covered_session"])
    last = panel.date_index(cov["last_covered_session"]) + 1
    split = panel.date_index(args.split)
    spans = {"news_dev": (first, min(split, last)), "news_holdout": (split, last)}

    power = {f"H{h}": minimum_detectable_ic(cov["covered_sessions"], h)
             for h in args.horizons}

    ic_out = {}
    for span, (lo, hi) in spans.items():
        m = np.zeros_like(uni.mask)
        m[lo:hi] = uni.mask[lo:hi]
        if m.sum() < 1000:
            continue
        controls = compute_all(bank, CONTROLS, mask=m)
        for h in args.horizons:
            fwd = icmod.forward_returns(panel, h)
            for name in NEWS_SIGNALS:
                s_ = np.where(m, mats[name], np.nan)
                r = icmod.ic_summary(icmod.daily_ic(s_, fwd, m), h)
                if not r.get("available"):
                    continue
                scores = dict(controls)
                scores["_news"] = s_
                inc = icmod.incremental_ic(scores, panel, m, h, CONTROLS)
                c = inc["coefficients"].get("_news", {})
                p = icmod.placebo_ic(s_, fwd, m, h, seeds=3)
                ic_out[f"{span}|{name}|H{h}"] = {
                    "ic": r["ic_mean"], "t": r["t_newey_west"], "days": r["days"],
                    "t_block": r.get("t_block"), "n_blocks": r.get("n_blocks"),
                    "too_few_blocks": r.get("too_few_blocks"),
                    "effective_obs": r.get("effective_independent_obs"),
                    "overlap_unreliable": r.get("overlap_unreliable"),
                    "incremental_bps_per_sigma": c.get("mean_bps_per_sigma"),
                    "incremental_t": c.get("t_newey_west"),
                    "placebo_t": p.get("t_mean"),
                    "above_power_floor": bool(
                        abs(r["ic_mean"]) >= power[f"H{h}"]["min_detectable_ic"]),
                }

    setup_out = {}
    if not args.no_setups:
        cost = cfg.costs.commission_bps + cfg.costs.slippage_bps + cfg.costs.spread_bps
        sspec = SetupSpec(trigger="pullback", require_volume=False, cost_bps_per_side=cost)
        ospec = OutcomeSpec(max_hold=60, cost_bps_per_side=cost)
        rs, _ = detect_setups(panel, bank, uni.mask, sspec)
        fs, _ = pseudo_setups(panel, bank, uni.mask, sspec)
        real = resolve_setups(panel, rs, ospec)
        ctrl = resolve_setups(panel, fs, ospec)
        for df in (real, ctrl):
            df["date"] = pd.to_datetime(df["date"])
            t, j = df["day"].to_numpy(), df["col"].to_numpy()
            for name in NEWS_SIGNALS:
                df[name] = mats[name][t, j]
        for span, (lo, hi) in spans.items():
            r_ = real[(real["day"] >= lo) & (real["day"] < hi)]
            c_ = ctrl[(ctrl["day"] >= lo) & (ctrl["day"] < hi)]
            if len(r_) < 300:
                continue

            class _S:
                reward_multiple = 2.0
            rep = conditioner_report(r_, list(NEWS_SIGNALS), _S(),
                                     n_variants=len(NEWS_SIGNALS) * 2, control=c_)
            setup_out[span] = {"n": int(len(r_)), "rows": rep["rows"],
                               "bar": rep["alpha_bonferroni"]}

    payload = {"coverage": cov, "power": power, "ic": ic_out, "setups": setup_out,
               "split": args.split, "lookback": args.lookback,
               "universe": uni.fingerprint}
    (out_dir / "impact.json").write_text(json.dumps(payload, indent=2, default=str))
    _print_impact(payload)
    return 0


def _print_impact(p: dict) -> None:
    cov, power = p["coverage"], p["power"]
    print("\n" + "=" * 98)
    print("NEWS OVERLAY — does the pipeline add anything the price data lacks?")
    print("=" * 98)
    print(f"coverage {cov['first_covered_session']} .. {cov['last_covered_session']}  "
          f"({cov['covered_sessions']} sessions), median "
          f"{cov['median_universe_names_with_news']:.0f} universe names/day "
          f"({cov['median_share_of_universe_with_news']:.0%} of the cross-section)")
    print("\nPOWER FLOOR — read this before the results:")
    for k, v in power.items():
        print(f"   {k}: {v['effective_independent_obs']:>5} independent observations "
              f"-> smallest resolvable IC {v['min_detectable_ic']:.4f}")
    print("   A real equity signal runs IC 0.02-0.05. Anything below the floor is")
    print("   invisible here: a null means 'not resolvable', not 'not present'.\n")

    if p["ic"]:
        print(f"{'span|signal|horizon':<40}{'IC':>9}{'t(NW)':>7}{'t(block)':>10}"
              f"{'eff obs':>9}{'incr t':>8}{'>floor':>8}")
        for k, v in p["ic"].items():
            flag = "!" if v.get("overlap_unreliable") else " "
            bt = v.get("t_block")
            bt_s = "n/a" if bt is None or not np.isfinite(bt) else f"{bt:+.2f}"
            print(f"{k:<40}{v['ic']:>+9.4f}{v['t']:>+7.2f}{flag}"
                  f"{bt_s:>9}"
                  f"{(v.get('effective_obs') or 0):>9.1f}"
                  f"{(v.get('incremental_t') or 0):>+8.2f}"
                  f"{('yes' if v['above_power_floor'] else '-'):>8}")
        print("   ! = Newey-West lags capped: the sample is too short for the horizon.")
        print("   t(block) uses non-overlapping blocks and makes no lag choice; it is")
        print("   reported 'n/a' below 8 blocks, because a t from 4 observations is theatre.")

    for span, s in p.get("setups", {}).items():
        print(f"\nsetup conditioner — {span} ({s['n']:,} pullback entries, "
              f"bar two-sided p < {s['bar']:.4f})")
        print(f"   {'signal':<24}{'hit rates':<26}{'ρR':>6}{'ΔR':>8}{'t(R)':>7}{'ctrl ΔR':>9}")
        for k, v in s["rows"].items():
            if not v.get("available"):
                print(f"   {k:<24}unavailable: {v.get('reason', '')}")
                continue
            hr = " ".join(f"{x:.0%}" for x in v["bucket_hit_rates"])
            print(f"   {k:<24}{hr:<26}{v['spearman_r']:>+6.2f}"
                  f"{(v.get('top_minus_bottom_r') or 0):>+8.3f}"
                  f"{(v.get('t_r') or 0):>+7.2f}"
                  f"{(v.get('control_top_minus_bottom') or 0):>+9.3f}")
    print("=" * 98 + "\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="strategylab.news")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("nrp", help="post-announcement repricing vs its own control")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--horizon", type=int, default=21)
    p.add_argument("--out", default=None)
    p.add_argument("--notes", default=None)
    p.set_defaults(func=cmd_nrp)

    p = sub.add_parser("impact", help="does the news overlay add anything?")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--end", default="2026-06-30")
    p.add_argument("--split", default="2026-01-02",
                   help="news-dev before this, news-holdout after")
    p.add_argument("--lookback", type=int, default=5)
    p.add_argument("--horizons", type=int, nargs="+", default=[5, 21])
    p.add_argument("--no-setups", action="store_true")
    p.add_argument("--out", default=None)
    p.set_defaults(func=cmd_impact)

    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
