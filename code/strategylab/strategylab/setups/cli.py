"""Setup-timing CLI.

    python -m strategylab.setups.cli timing [--limit N]

Detects every Minervini-style breakout in the pinned momentum universe, resolves
each to its first barrier touch (2R target vs support stop), and asks two
questions in order: does the trade clear its own control, and does anything time
it.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from ..config import OUTPUT_ROOT, LabConfig, load_env
from ..momentum.cli import _load as _load_panel
from ..momentum.signals import REGISTRY, compute_all
from ..data.earnings import EarningsStore
from ..momentum.universe import UniverseSpec, pin_universe
from ..pairs.discriminate import announcement_grid
from . import study
from .detect import SetupSpec, detect_setups, ma_test_count, pseudo_setups
from .outcomes import OutcomeSpec, resolve_setups
from .portfolio import PortfolioSpec, run_setup_portfolio
from .vcp import DESCRIPTIONS as VCP_DESC, FEATURES as VCP_FEATURES, base_features

log = logging.getLogger(__name__)

# Conditioners specific to the setup itself, on top of the signal registry.
SETUP_CONDITIONERS = {
    "risk_pct": "how far the support sits below entry — tight base vs loose",
    "base_tightness": "range contraction over the base",
    "breakout_volume": "volume on the trigger bar vs its 50-day average",
    "dist_52w_high": "how much overhead supply is left",
    "atr_pct": "the name's own volatility",
    "market_regime": "benchmark above its own 200-day MA on the trigger day",
}


def _attach_conditioners(df: pd.DataFrame, panel, bank, mask, bench_close):
    """Signal values AS OF the trigger day — never after it."""
    if df.empty:
        return df
    t = df["day"].to_numpy()
    j = df["col"].to_numpy()

    scores = compute_all(bank, list(REGISTRY), mask=mask)
    for name, mat in scores.items():
        df[name] = mat[t, j]

    df["base_tightness"] = bank.get("tightness")[t, j]
    df["breakout_volume"] = bank.get("volume_ratio", length=50)[t, j]
    df["dist_52w_high"] = bank.get("pct_below_52w_high")[t, j]
    df["atr_pct"] = bank.get("atr_pct", length=14)[t, j]

    if bench_close is not None:
        s200 = pd.Series(bench_close).rolling(200, min_periods=150).mean().to_numpy()
        regime = (bench_close > s200).astype(float)
        regime[~np.isfinite(s200)] = np.nan
        df["market_regime"] = regime[t]
    return df


def cmd_timing(args) -> int:
    out_dir = Path(args.out or (OUTPUT_ROOT / "setups"))
    out_dir.mkdir(parents=True, exist_ok=True)
    cfg = LabConfig()
    sspec = SetupSpec(base_len=args.base_len, stop_lookback=args.stop_lookback,
                      max_risk_pct=args.max_risk,
                      reward_multiple=args.reward,
                      cost_bps_per_side=(cfg.costs.commission_bps
                                         + cfg.costs.slippage_bps
                                         + cfg.costs.spread_bps))
    ospec = OutcomeSpec(max_hold=sspec.max_hold,
                        cost_bps_per_side=sspec.cost_bps_per_side)

    cond_names = list(REGISTRY) + list(SETUP_CONDITIONERS)
    protocol = {"setup": sspec.__dict__, "outcome": ospec.__dict__,
                "dev": [cfg.splits.dev_start, cfg.splits.dev_end],
                "vault": [cfg.splits.vault_start, cfg.splits.vault_end],
                "n_conditioners": len(cond_names),
                "protocol_version": cfg.protocol_version}
    prereg = study.preregister(out_dir, protocol, notes=args.notes or "")
    n_var = prereg["n_variants"]
    log.info("pre-registered %d variants -> %s", n_var, out_dir / "preregistration.json")

    panel, bank = _load_panel(args.limit, "2004-01-01", cfg.splits.vault_end)
    uni = pin_universe(panel, bank, UniverseSpec())
    log.info("universe [%s]: median %d names/day", uni.fingerprint[:12],
             uni.stats()["median_names_per_day"])

    real_s, funnel = detect_setups(panel, bank, uni.mask, sspec)
    fake_s, ffunnel = pseudo_setups(panel, bank, uni.mask, sspec)
    log.info("setups: %d real, %d pseudo", len(real_s), len(fake_s))
    for k, v in funnel.items():
        log.info("   %-28s %s", k, f"{v:,}")

    real = resolve_setups(panel, real_s, ospec)
    fake = resolve_setups(panel, fake_s, ospec)
    bench = panel.close[:, panel.symbols.index("SPY")] if "SPY" in panel.symbols else None
    real = _attach_conditioners(real, panel, bank, uni.mask, bench)
    fake = _attach_conditioners(fake, panel, bank, uni.mask, bench)

    for df in (real, fake):
        df["date"] = pd.to_datetime(df["date"])

    def slice_(df, a, b):
        return df[(df["date"] >= pd.Timestamp(a)) & (df["date"] <= pd.Timestamp(b))]

    dev_r = slice_(real, cfg.splits.dev_start, cfg.splits.dev_end)
    dev_f = slice_(fake, cfg.splits.dev_start, cfg.splits.dev_end)
    log.info("dev: %d real setups, %d pseudo", len(dev_r), len(dev_f))

    tests = study.run_tests(dev_r, dev_f, sspec, n_variants=n_var)
    cond = study.conditioner_report(dev_r, [c for c in cond_names if c in dev_r.columns],
                                    sspec, n_variants=n_var, control=dev_f)
    verd = study.verdict(tests, cond)

    vault_r = slice_(real, cfg.splits.vault_start, cfg.splits.vault_end)
    vault_f = slice_(fake, cfg.splits.vault_start, cfg.splits.vault_end)
    vault = study.run_tests(vault_r, vault_f, sspec, n_variants=n_var) \
        if len(vault_r) > 200 else {}

    payload = study.SetupResult(
        protocol=protocol,
        sample={"universe": uni.manifest() | {"symbols": len(uni.symbols)},
                "funnel_real": funnel, "funnel_pseudo": ffunnel,
                "dev_setups": int(len(dev_r)), "dev_pseudo": int(len(dev_f)),
                "vault_setups": int(len(vault_r))},
        tests=tests, conditioners=cond, verdict=verd,
        preregistration=prereg).to_dict()
    payload["vault"] = vault
    (out_dir / "timing.json").write_text(json.dumps(payload, indent=2, default=str))
    real.to_csv(out_dir / "setups.csv.gz", index=False, compression="gzip")
    fake.to_csv(out_dir / "pseudo_setups.csv.gz", index=False, compression="gzip")

    _print(payload, dev_r, sspec)
    return 0 if verd["setup_has_edge"] else 1


def _print(payload: dict, dev: pd.DataFrame, sspec) -> None:
    t, v, s = payload["tests"], payload["verdict"], payload["sample"]
    print("\n" + "=" * 88)
    print(f"SETUP TIMING — Minervini breakout, support stop, {sspec.reward_multiple:g}R target")
    print("=" * 88)
    print(f"{s['dev_setups']:,} setups on dev, {s['dev_pseudo']:,} matched pseudo-setups")
    print(f"median risk {dev['risk_pct'].median():.1%} of price, "
          f"median hold {dev['days_held'].median():.0f} sessions, "
          f"{(dev['resolved']).mean():.0%} resolved at a barrier")
    print(f"\nresolution: {t['resolution_rate']:.0%} of trades end at a barrier "
          f"({t['stop_rate']:.0%} stopped, {t['hit_rate']:.0%} hit target, "
          f"{1-t['resolution_rate']:.0%} timed out)")
    print(f"breakeven P(target|resolved): {t['breakeven_hit_rate_gross']:.1%} gross, "
          f"{t['breakeven_hit_rate_net']:.1%} after costs "
          f"({t['median_cost_r']:.3f}R) — and 33.3% is exactly the driftless "
          f"random-walk rate")
    print(f"ACTUAL P(target|resolved):    {(t.get('hit_rate_given_resolved') or 0):.1%}"
          f"      pseudo-setup control: "
          f"{(t.get('pseudo_hit_rate_given_resolved') or 0):.1%}")

    def row(name, r, unit=""):
        if not r or not r.get("available"):
            print(f"   {name:<44} unavailable")
            return
        mark = "PASS" if r.get("pass") else "fail"
        print(f"   {name:<44} {r['mean']:>+8.4f}{unit}  t {r['t']:>+6.2f}  "
              f"p {r.get('p_one_sided', float('nan')):.4f}  [{r['months']}m] -> {mark}")

    print(f"\nBonferroni alpha {t['alpha_bonferroni']:.5f}")
    row("S1 hit rate minus breakeven", t.get("S1_setup_beats_its_breakeven_hit_rate"))
    row("S2 minus pseudo-setup control", t.get("S2_setup_beats_the_pseudo_setup_control"))
    row("S3 net expectancy (R per trade)", t.get("S3_expectancy_net_of_costs_is_positive"))

    cond = payload["conditioners"]["rows"]
    avail = {k: r for k, r in cond.items() if r.get("available")}
    if avail:
        print(f"\nTIMING — does any conditioner lift the hit rate? "
              f"({len(avail)} tested, bar |p| < {payload['conditioners']['alpha_bonferroni']:.5f})")
        print(f"   {'conditioner':<24}{'bucket hit rates (low→high)':<34}"
              f"{'ρ':>7}{'top−bot':>9}{'t':>7}{'plac t':>8}")
        order = sorted(avail, key=lambda k: -(avail[k].get("t") or 0))
        for k in order[:12]:
            r = avail[k]
            hr = " ".join(f"{x:.0%}" for x in r["bucket_hit_rates"])
            print(f"   {k:<24}{hr:<34}{r['spearman']:>+7.2f}"
                  f"{(r.get('top_minus_bottom') or 0):>+9.3f}{(r.get('t') or 0):>+7.2f}"
                  f"{(r.get('placebo_t') or 0):>+8.2f}")

    print("\n" + "-" * 88)
    print(f"VERDICT: the setup {'HAS an edge' if v['setup_has_edge'] else 'does NOT clear its control'}")
    for k, ok in v["conditions"].items():
        print(f"   [{'x' if ok else ' '}] {k}")
    print(f"   conditioners that time it: "
          f"{', '.join(v['conditioners_that_time_it']) or 'NONE'} "
          f"(of {v['n_conditioners_tested']} tested)")
    print(f"\n{v['recommendation']}")
    vault = payload.get("vault") or {}
    if vault.get("hit_rate") is not None:
        print(f"\nvault {s['vault_setups']:,} setups: hit rate {vault['hit_rate']:.1%} "
              f"vs control {vault['pseudo_hit_rate']:.1%}, breakeven "
              f"{vault['breakeven_hit_rate_net']:.1%}")
    print("=" * 88 + "\n")


def cmd_trail(args) -> int:
    """Head-to-head: fixed 2R target vs converting to an SMA trail at the target.

    The two rules are resolved on the SAME setup list, so every trade appears
    under both and the comparison is PAIRED — the difference is attributable to
    the exit and nothing else. The pseudo-setup control is resolved under both
    rules too, because an exit rule that also improves random entries is a
    property of the market, not of the setup.
    """
    out_dir = Path(args.out or (OUTPUT_ROOT / "setups"))
    out_dir.mkdir(parents=True, exist_ok=True)
    cfg = LabConfig()
    cost = cfg.costs.commission_bps + cfg.costs.slippage_bps + cfg.costs.spread_bps
    sspec = SetupSpec(base_len=args.base_len, stop_lookback=args.stop_lookback,
                      max_risk_pct=args.max_risk, reward_multiple=args.reward,
                      cost_bps_per_side=cost)

    panel, bank = _load_panel(args.limit, "2004-01-01", cfg.splits.vault_end)
    uni = pin_universe(panel, bank, UniverseSpec())
    ma = bank.get("sma", length=args.trail_ma)
    log.info("universe [%s]; trailing on SMA%d", uni.fingerprint[:12], args.trail_ma)

    real_s, _ = detect_setups(panel, bank, uni.mask, sspec)
    fake_s, _ = pseudo_setups(panel, bank, uni.mask, sspec)
    log.info("%d real setups, %d pseudo", len(real_s), len(fake_s))

    fixed = OutcomeSpec(max_hold=sspec.max_hold, cost_bps_per_side=cost)
    trail = OutcomeSpec(max_hold=sspec.max_hold, cost_bps_per_side=cost,
                        trail_on_target=True, trail_ma_len=args.trail_ma,
                        max_trail_hold=args.max_trail_hold)

    frames = {}
    for label, setups in (("real", real_s), ("pseudo", fake_s)):
        a = resolve_setups(panel, setups, fixed)
        b = resolve_setups(panel, setups, trail, trail_ma=ma)
        key = ["symbol", "date", "day", "col"]
        m = a.merge(b, on=key, suffixes=("_fixed", "_trail"))
        m["date"] = pd.to_datetime(m["date"])
        frames[label] = m

    res = {"trail_ma": args.trail_ma, "max_trail_hold": args.max_trail_hold,
           "eras": {}}
    for era, (lo, hi) in (("dev", (cfg.splits.dev_start, cfg.splits.dev_end)),
                          ("vault", (cfg.splits.vault_start, cfg.splits.vault_end))):
        row = {}
        for label, m in frames.items():
            d = m[(m["date"] >= pd.Timestamp(lo)) & (m["date"] <= pd.Timestamp(hi))]
            if len(d) < 100:
                continue
            won = d[d["hit_target_fixed"].astype(bool)]
            row[label] = {
                "trades": int(len(d)),
                "winners": int(len(won)),
                "r_fixed": float(d["r_net_fixed"].mean()),
                "r_trail": float(d["r_net_trail"].mean()),
                "delta_r": study._cluster(
                    study._monthly(d.assign(_x=d["r_net_trail"] - d["r_net_fixed"]), "_x")
                    .to_numpy()),
                "winners_pct_fixed": float(won["pct_return_fixed"].mean()),
                "winners_pct_trail": float(won["pct_return_trail"].mean()),
                "winners_delta_pct": float((won["pct_return_trail"]
                                            - won["pct_return_fixed"]).mean()),
                "winners_delta_r": float((won["r_net_trail"] - won["r_net_fixed"]).mean()),
                "winners_share_improved": float(
                    (won["r_net_trail"] > won["r_net_fixed"]).mean()),
                "median_hold_fixed": float(d["days_held_fixed"].median()),
                "median_hold_trail": float(d["days_held_trail"].median()),
            }
        res["eras"][era] = row

    (out_dir / "trail.json").write_text(json.dumps(res, indent=2, default=str))
    frames["real"].to_csv(out_dir / "trail_paired.csv.gz", index=False, compression="gzip")
    _print_trail(res)
    return 0


def _print_trail(res: dict) -> None:
    print("\n" + "=" * 88)
    print(f"EXIT RULE — fixed 2R target  vs  convert to an SMA{res['trail_ma']} trail at 2R")
    print("=" * 88)
    print("paired on identical setups; only the exit differs\n")
    print(f"{'era':<7}{'book':<9}{'trades':>8}{'R fixed':>9}{'R trail':>9}"
          f"{'ΔR':>8}{'t':>7}{'winners Δ%':>12}{'Δ R':>7}{'improved':>10}")
    for era, row in res["eras"].items():
        for label, r in row.items():
            d = r["delta_r"]
            print(f"{era:<7}{label:<9}{r['trades']:>8,}{r['r_fixed']:>+9.3f}"
                  f"{r['r_trail']:>+9.3f}{d.get('mean', float('nan')):>+8.3f}"
                  f"{d.get('t', float('nan')):>+7.2f}"
                  f"{r['winners_delta_pct']*100:>+11.2f}%{r['winners_delta_r']:>+7.2f}"
                  f"{r['winners_share_improved']:>10.0%}")
    print("\n'winners' = trades that reached 2R under the fixed rule; Δ% is the extra")
    print("price return the trail earned on those, which is the number to compare")
    print("against a remembered ~6% improvement.")
    print("=" * 88 + "\n")


def cmd_base(args) -> int:
    """Does the STRUCTURE of the base separate good breakouts from bad?

    The only conditioners left worth testing. Name-level ones were shown to lift
    the control by as much as the real book, and the universe screen already
    encodes the market regime — so if base structure does not separate triggers,
    the breakout entry has no timing value on this universe.
    """
    out_dir = Path(args.out or (OUTPUT_ROOT / "setups"))
    out_dir.mkdir(parents=True, exist_ok=True)
    cfg = LabConfig()
    cost = cfg.costs.commission_bps + cfg.costs.slippage_bps + cfg.costs.spread_bps
    sspec = SetupSpec(base_len=args.base_len, stop_lookback=args.stop_lookback,
                      max_risk_pct=args.max_risk, reward_multiple=args.reward,
                      cost_bps_per_side=cost)
    ospec = OutcomeSpec(max_hold=sspec.max_hold, cost_bps_per_side=cost)

    protocol = {"setup": sspec.__dict__, "base_len": args.base_len,
                "features": list(VCP_FEATURES),
                "dev": [cfg.splits.dev_start, cfg.splits.dev_end],
                "n_conditioners": len(VCP_FEATURES),
                "protocol_version": cfg.protocol_version}
    prereg = study.preregister(out_dir / "base", protocol, notes=args.notes or "")
    n_var = prereg["n_variants"]
    log.info("pre-registered %d variants", n_var)

    panel, bank = _load_panel(args.limit, "2004-01-01", cfg.splits.vault_end)
    uni = pin_universe(panel, bank, UniverseSpec())
    real_s, _ = detect_setups(panel, bank, uni.mask, sspec)
    fake_s, _ = pseudo_setups(panel, bank, uni.mask, sspec)
    log.info("%d real setups, %d pseudo", len(real_s), len(fake_s))

    frames = {}
    for label, setups in (("real", real_s), ("pseudo", fake_s)):
        res = resolve_setups(panel, setups, ospec)
        feats = base_features(panel, setups, base_len=args.base_len)
        m = res.merge(feats, on=["symbol", "date", "day", "col"], how="inner")
        m["date"] = pd.to_datetime(m["date"])
        frames[label] = m
    log.info("base features computed: %d real, %d pseudo",
             len(frames["real"]), len(frames["pseudo"]))

    def slice_(df):
        return df[(df["date"] >= pd.Timestamp(cfg.splits.dev_start))
                  & (df["date"] <= pd.Timestamp(cfg.splits.dev_end))]

    dev_r, dev_f = slice_(frames["real"]), slice_(frames["pseudo"])
    cond = study.conditioner_report(dev_r, list(VCP_FEATURES), sspec,
                                    n_variants=n_var, control=dev_f)
    tests = study.run_tests(dev_r, dev_f, sspec, n_variants=n_var)
    verd = study.verdict(tests, cond)

    payload = {"protocol": protocol, "preregistration": prereg,
               "sample": {"dev_setups": int(len(dev_r)), "dev_pseudo": int(len(dev_f))},
               "tests": tests, "conditioners": cond, "verdict": verd,
               "descriptions": VCP_DESC}
    (out_dir / "base_structure.json").write_text(json.dumps(payload, indent=2, default=str))
    frames["real"].to_csv(out_dir / "base_features.csv.gz", index=False, compression="gzip")
    _print_base(payload)
    return 0 if verd["conditioners_that_time_it"] else 1


def _print_base(payload: dict) -> None:
    c, v = payload["conditioners"], payload["verdict"]
    print("\n" + "=" * 104)
    print("BASE STRUCTURE — does the shape of the consolidation time the breakout?")
    print("=" * 104)
    print(f"{payload['sample']['dev_setups']:,} setups on dev with a full base window, "
          f"{payload['sample']['dev_pseudo']:,} matched controls")
    print(f"bar: two-sided p < {c['alpha_bonferroni']:.5f}, |rank corr| >= 0.7, "
          f"on EXPECTANCY not hit rate\n")
    rows = c["rows"]
    avail = {k: r for k, r in rows.items() if r.get("available")}
    print(f"   {'feature':<22}{'hit rates (low→high)':<32}{'ρhit':>6}"
          f"{'ΔR':>8}{'t(R)':>7}{'ρR':>6}{'ctrl ΔR':>9}{'plac':>7}")
    for k in sorted(avail, key=lambda x: -abs(avail[x].get("t_r") or 0)):
        r = avail[k]
        hr = " ".join(f"{x:.0%}" for x in r["bucket_hit_rates"])
        print(f"   {k:<22}{hr:<32}{r['spearman_hit']:>+6.2f}"
              f"{(r.get('top_minus_bottom_r') or 0):>+8.3f}{(r.get('t_r') or 0):>+7.2f}"
              f"{r['spearman_r']:>+6.2f}"
              f"{(r.get('control_top_minus_bottom') or 0):>+9.3f}"
              f"{(r.get('placebo_t') or 0):>+7.2f}")
    missing = [k for k, r in rows.items() if not r.get("available")]
    if missing:
        print(f"\n   not testable: {', '.join(missing)}")
    print("\n" + "-" * 104)
    print(f"features that sort EXPECTANCY: {', '.join(v['conditioners_that_time_it']) or 'NONE'}")
    print(f"features that sort HIT RATE only (mechanical, not edge): "
          f"{', '.join(v.get('sort_hit_rate_but_not_expectancy', [])) or 'NONE'}")
    print("=" * 104 + "\n")


def cmd_entry(args) -> int:
    """Breakout entry vs pullback entry, each against its own control.

    The breakout was already shown to lose to a no-trigger control. The pullback
    is the alternative both this project's own data and the practitioner
    literature point at: within a name that is already trending, recent strength
    is a negative signal — which is the same thing the skip-month in 12-1
    momentum encodes.
    """
    out_dir = Path(args.out or (OUTPUT_ROOT / "setups"))
    out_dir.mkdir(parents=True, exist_ok=True)
    cfg = LabConfig()
    cost = cfg.costs.commission_bps + cfg.costs.slippage_bps + cfg.costs.spread_bps
    ospec = OutcomeSpec(max_hold=60, cost_bps_per_side=cost)

    panel, bank = _load_panel(args.limit, "2004-01-01", cfg.splits.vault_end)
    uni = pin_universe(panel, bank, UniverseSpec())
    earn = EarningsStore().all_dates(list(panel.symbols))
    egrid = announcement_grid(panel, earn, args.earnings_window)
    log.info("universe [%s]; earnings grid on %d names",
             uni.fingerprint[:12], sum(1 for v in earn.values() if v))

    results, frames = {}, {}
    for trig in ("breakout", "pullback"):
        sspec = SetupSpec(trigger=trig, base_len=args.base_len,
                          stop_lookback=args.stop_lookback, max_risk_pct=args.max_risk,
                          reward_multiple=args.reward, ma_len=args.ma_len,
                          cost_bps_per_side=cost,
                          require_volume=(trig == "breakout"))
        real_s, funnel = detect_setups(panel, bank, uni.mask, sspec)
        fake_s, _ = pseudo_setups(panel, bank, uni.mask, sspec)
        real = resolve_setups(panel, real_s, ospec)
        fake = resolve_setups(panel, fake_s, ospec)
        if real.empty:
            continue
        mt = ma_test_count(panel, bank, sspec)
        for df in (real, fake):
            df["date"] = pd.to_datetime(df["date"])
            t, j = df["day"].to_numpy(), df["col"].to_numpy()
            df["ma_tests"] = mt[t, j]
            df["near_earnings"] = egrid[t, j]
        dev = real[(real["date"] >= pd.Timestamp(cfg.splits.dev_start))
                   & (real["date"] <= pd.Timestamp(cfg.splits.dev_end))]
        devf = fake[(fake["date"] >= pd.Timestamp(cfg.splits.dev_start))
                    & (fake["date"] <= pd.Timestamp(cfg.splits.dev_end))]
        vault = real[real["date"] >= pd.Timestamp(cfg.splits.vault_start)]
        vaultf = fake[fake["date"] >= pd.Timestamp(cfg.splits.vault_start)]
        results[trig] = {
            "funnel": funnel,
            "n_dev": int(len(dev)), "n_vault": int(len(vault)),
            "dev": study.run_tests(dev, devf, sspec, n_variants=args.variants),
            "vault": study.run_tests(vault, vaultf, sspec, n_variants=args.variants)
            if len(vault) > 200 else {},
            "conditioners": study.conditioner_report(
                dev, ["ma_tests", "near_earnings", "risk_pct"], sspec,
                n_variants=args.variants, control=devf),
        }
        frames[trig] = {"dev": dev, "devf": devf}

    # Earnings: the gap-through-stop tail was -1.31R. Does it live near reports?
    earn_block = {}
    for trig, fr in frames.items():
        d = fr["dev"]
        gaps = d[d["exit_reason"] == "stop_gap"]
        base = float(d["near_earnings"].mean())
        earn_block[trig] = {
            "share_of_all_setups_near_earnings": base,
            "share_of_gap_stops_near_earnings": float(gaps["near_earnings"].mean())
            if len(gaps) else None,
            "n_gap_stops": int(len(gaps)),
            "mean_r_gap_stop": float(gaps["r_net"].mean()) if len(gaps) else None,
            "expectancy_all": float(d["r_net"].mean()),
            "expectancy_excluding_earnings_entries": float(
                d[~d["near_earnings"].astype(bool)]["r_net"].mean()),
            "expectancy_earnings_entries_only": float(
                d[d["near_earnings"].astype(bool)]["r_net"].mean())
            if d["near_earnings"].any() else None,
        }

    payload = {"universe": uni.manifest() | {"symbols": len(uni.symbols)},
               "results": results, "earnings": earn_block,
               "earnings_window": args.earnings_window}
    (out_dir / "entry.json").write_text(json.dumps(payload, indent=2, default=str))
    for trig, fr in frames.items():
        fr["dev"].to_csv(out_dir / f"entry_{trig}.csv.gz", index=False, compression="gzip")
    _print_entry(payload)
    return 0


def _print_entry(payload: dict) -> None:
    print("\n" + "=" * 96)
    print("ENTRY TIMING — breakout vs pullback, each against its own no-trigger control")
    print("=" * 96)
    print(f"{'trigger':<12}{'era':<8}{'setups':>8}{'P(tgt|res)':>12}{'control':>10}"
          f"{'S2 diff':>10}{'t':>7}{'net R':>9}{'t':>7}")
    for trig, r in payload["results"].items():
        for era in ("dev", "vault"):
            t = r.get(era) or {}
            if not t.get("hit_rate_given_resolved"):
                continue
            s2 = t.get("S2_setup_beats_the_pseudo_setup_control", {})
            s3 = t.get("S3_expectancy_net_of_costs_is_positive", {})
            print(f"{trig:<12}{era:<8}{r.get('n_' + era, 0):>8,}"
                  f"{t['hit_rate_given_resolved']:>11.1%}"
                  f"{(t.get('pseudo_hit_rate_given_resolved') or 0):>10.1%}"
                  f"{(s2.get('mean') or 0):>+10.3f}{(s2.get('t') or 0):>+7.2f}"
                  f"{(s3.get('mean') or 0):>+9.4f}{(s3.get('t') or 0):>+7.2f}")

    print("\ntrigger-level conditioners (dev) — the control cannot share these:")
    print(f"   {'trigger':<11}{'conditioner':<16}{'hit rates':<26}{'ρR':>6}{'ΔR':>8}{'t(R)':>7}")
    for trig, r in payload["results"].items():
        for k, v in (r.get("conditioners", {}).get("rows", {}) or {}).items():
            if not v.get("available"):
                continue
            hr = " ".join(f"{x:.0%}" for x in v["bucket_hit_rates"])
            print(f"   {trig:<11}{k:<16}{hr:<26}{v['spearman_r']:>+6.2f}"
                  f"{(v.get('top_minus_bottom_r') or 0):>+8.3f}{(v.get('t_r') or 0):>+7.2f}")

    print(f"\nearnings proximity (+/-{payload['earnings_window']} sessions of a report):")
    for trig, e in payload["earnings"].items():
        print(f"   {trig}: {e['share_of_all_setups_near_earnings']:.1%} of entries sit near a "
              f"report; {(e['share_of_gap_stops_near_earnings'] or 0):.1%} of the "
              f"{e['n_gap_stops']} gap-stops do")
        print(f"      expectancy  all {e['expectancy_all']:+.4f}R   "
              f"excluding earnings entries {e['expectancy_excluding_earnings_entries']:+.4f}R   "
              f"earnings entries only {(e['expectancy_earnings_entries_only'] or 0):+.4f}R")
    print("=" * 96 + "\n")


def cmd_book(args) -> int:
    """The setup strategy with a cap on concurrent positions.

    Per-trade expectancy cannot answer this: a book that can hold ten names is a
    different animal from one that takes every setup, because capacity forces a
    choice and idle capital earns nothing.
    """
    from ..momentum import hold as holdmod
    from ..momentum.signals import compute_all

    cfg = LabConfig()
    out_dir = Path(args.out or (OUTPUT_ROOT / "setups"))
    out_dir.mkdir(parents=True, exist_ok=True)
    cost = cfg.costs.commission_bps + cfg.costs.slippage_bps + cfg.costs.spread_bps
    sspec = SetupSpec(trigger=args.trigger, base_len=args.base_len,
                      stop_lookback=args.stop_lookback, max_risk_pct=args.max_risk,
                      reward_multiple=args.reward, cost_bps_per_side=cost,
                      require_volume=(args.trigger == "breakout"))
    ospec = OutcomeSpec(max_hold=60, cost_bps_per_side=cost,
                        trail_on_target=args.trail, trail_ma_len=args.trail_ma)

    panel, bank = _load_panel(args.limit, "2004-01-01", cfg.splits.vault_end)
    uni = pin_universe(panel, bank, UniverseSpec())
    ma = bank.get("sma", length=args.trail_ma) if args.trail else None
    setups, funnel = detect_setups(panel, bank, uni.mask, sspec)
    resolved = resolve_setups(panel, setups, ospec, trail_ma=ma)
    resolved["date"] = pd.to_datetime(resolved["date"])
    log.info("%d %s setups resolved", len(resolved), args.trigger)

    score = compute_all(bank, ["rs_rank"], mask=uni.mask)["rs_rank"]
    spy = holdmod.buy_and_hold(panel, "SPY")
    screen_spec = holdmod.HoldSpec(cost_bps_per_side=cost, breadth_scaled=True)
    screen, _ = holdmod.run_hold(panel, uni.mask, screen_spec,
                                 start=panel.date_index("2005-01-03"))

    spans = {"full 2005-2026": ("2005-01-03", cfg.splits.vault_end),
             "dev 2014-2023": (cfg.splits.dev_start, cfg.splits.dev_end)}
    rows = {}
    for cap in args.caps:
        for sel in args.selection:
            pspec = PortfolioSpec(max_positions=cap, risk_per_trade=args.risk,
                                  selection=sel)
            r, d = run_setup_portfolio(panel, resolved, pspec, score=score)
            for span, (a, b) in spans.items():
                lo = panel.date_index(a)
                hi = min(len(r), len(spy), panel.date_index(b) + 1)
                if hi - lo < 300:
                    continue
                rows[(cap, sel, span)] = holdmod.stats_of(r[lo:hi], spy[lo:hi]) | d

    payload = {"universe": uni.fingerprint, "trigger": args.trigger,
               "risk_per_trade": args.risk, "trail": args.trail,
               "setups": int(len(resolved)),
               "rows": {f"{k[0] or 'unlimited'}|{k[1]}|{k[2]}": v for k, v in rows.items()},
               "benchmarks": {s: {"spy": holdmod.stats_of(
                   spy[panel.date_index(a):min(len(spy), panel.date_index(b) + 1)]),
                   "screen": holdmod.stats_of(
                       screen[panel.date_index(a):min(len(screen), panel.date_index(b) + 1)])}
                   for s, (a, b) in spans.items()}}
    (out_dir / "book.json").write_text(json.dumps(payload, indent=2, default=str))

    print("\n" + "=" * 104)
    print(f"SETUP BOOK — {args.trigger} entries, {args.risk:.0%} risk per trade, "
          f"capped concurrent positions")
    print("=" * 104)
    print(f"{len(resolved):,} setups resolved"
          + (f", trailing on SMA{args.trail_ma} from target" if args.trail else
             f", fixed {args.reward:g}R target"))
    for span in spans:
        bm = payload["benchmarks"][span]
        print(f"\n--- {span}")
        print(f"   SPY            CAGR {bm['spy']['cagr']:+.1%}  "
              f"Sharpe {bm['spy']['sharpe']:.2f}  maxDD {bm['spy']['max_drawdown']:.1%}")
        print(f"   hold-the-screen CAGR {bm['screen']['cagr']:+.1%}  "
              f"Sharpe {bm['screen']['sharpe']:.2f}  maxDD {bm['screen']['max_drawdown']:.1%}")
        print(f"   {'cap':>5}{'pick':<9}{'CAGR':>8}{'vol':>7}{'Sharpe':>8}{'maxDD':>8}"
              f"{'gross':>8}{'open':>7}{'taken':>8}{'take%':>7}{'binds':>15}")
        for cap in args.caps:
            for sel in args.selection:
                v = rows.get((cap, sel, span))
                if not v:
                    continue
                label = "none" if cap == 0 else str(cap)
                print(f"   {label:>5}{sel:<9}{v['cagr']:>+8.1%}{v['vol']:>7.1%}"
                      f"{v['sharpe']:>8.2f}{v['max_drawdown']:>8.1%}"
                      f"{v['avg_gross_exposure']:>8.0%}{v['avg_open_positions']:>7.1f}"
                      f"{v['trades_taken']:>8,}{v['take_rate']:>7.0%}"
                      f"{v['binding']:>15}")
    print("\n'take%' is the share of available setups the book could actually take.")
    print("=" * 104 + "\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="strategylab.setups")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("timing", help="does the setup work, and does anything time it")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--base-len", type=int, default=40)
    p.add_argument("--stop-lookback", type=int, default=10)
    p.add_argument("--max-risk", type=float, default=0.10)
    p.add_argument("--reward", type=float, default=2.0)
    p.add_argument("--out", default=None)
    p.add_argument("--notes", default=None)
    p.set_defaults(func=cmd_timing)

    p = sub.add_parser("trail", help="fixed 2R target vs an SMA trail from 2R")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--base-len", type=int, default=40)
    p.add_argument("--stop-lookback", type=int, default=10)
    p.add_argument("--max-risk", type=float, default=0.10)
    p.add_argument("--reward", type=float, default=2.0)
    p.add_argument("--trail-ma", type=int, default=21)
    p.add_argument("--max-trail-hold", type=int, default=252)
    p.add_argument("--out", default=None)
    p.set_defaults(func=cmd_trail)

    p = sub.add_parser("base", help="does base structure time the breakout?")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--base-len", type=int, default=40)
    p.add_argument("--stop-lookback", type=int, default=10)
    p.add_argument("--max-risk", type=float, default=0.10)
    p.add_argument("--reward", type=float, default=2.0)
    p.add_argument("--out", default=None)
    p.add_argument("--notes", default=None)
    p.set_defaults(func=cmd_base)

    p = sub.add_parser("entry", help="breakout vs pullback entry, each vs its control")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--base-len", type=int, default=40)
    p.add_argument("--stop-lookback", type=int, default=10)
    p.add_argument("--max-risk", type=float, default=0.10)
    p.add_argument("--reward", type=float, default=2.0)
    p.add_argument("--ma-len", type=int, default=21)
    p.add_argument("--earnings-window", type=int, default=5)
    p.add_argument("--variants", type=int, default=12)
    p.add_argument("--out", default=None)
    p.set_defaults(func=cmd_entry)

    p = sub.add_parser("book", help="setup strategy with a position cap")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--trigger", default="pullback", choices=["pullback", "breakout"])
    p.add_argument("--base-len", type=int, default=40)
    p.add_argument("--stop-lookback", type=int, default=10)
    p.add_argument("--max-risk", type=float, default=0.10)
    p.add_argument("--reward", type=float, default=2.0)
    p.add_argument("--risk", type=float, default=0.01)
    p.add_argument("--caps", type=int, nargs="+", default=[1, 3, 5, 10, 20, 0])
    p.add_argument("--selection", nargs="+", default=["random", "score"])
    p.add_argument("--trail", action="store_true")
    p.add_argument("--trail-ma", type=int, default=50)
    p.add_argument("--out", default=None)
    p.set_defaults(func=cmd_book)

    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
