"""Flow-Inertia Momentum CLI.

    python -m strategylab.flow.cli stage1 [--limit N] [--band mid_cap_target]

Stage 1 is the gate. It builds the Tier-1 signal set, runs the pre-registered
Fama-MacBeth models and the falsification battery, and states whether the
evidence justifies building a portfolio at all.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from ..config import OUTPUT_ROOT, LabConfig, load_env
from ..data.fundamentals import FundamentalsStore
from ..data.prices import PriceStore
from ..data.universe import UniverseBuilder
from . import stage1 as s1
from .panel import build_dataset, long_short_spread, prepare_cross_sections, quantile_sort
from .signals import compute_flow_signals, placebo_flow_signals

log = logging.getLogger(__name__)

REGRESSORS = ["rho", "F", "mom_12_1", "strev", "log_cap", "log_turnover",
              "sigma", "log_illiq", "gap", "t_half", "rho_ema"]
INTERACTIONS = [("rho", "F")]


def _load(limit: int | None, start: str, end: str):
    load_env()
    cfg = LabConfig()
    ub = UniverseBuilder()
    ordered = [r["symbol"] for r in ub.membership("nyse_nasdaq", include_delisted=True)]
    store = PriceStore()
    cached = set(store.cached_symbols())
    symbols = [s for s in ordered if s in cached]
    if limit:
        symbols = symbols[:limit]
    panel = store.build_panel(symbols, start, end, min_rows=400)
    log.info("panel: %d sessions x %d symbols (%s .. %s)", panel.shape[0], panel.shape[1],
             panel.dates[0], panel.dates[-1])
    shares = FundamentalsStore().align_shares(panel.symbols, panel.dates)
    cov = float(np.isfinite(shares).mean())
    log.info("point-in-time share counts cover %.1f%% of the panel", cov * 100)
    return cfg, panel, shares, cov


def _proxy_persistence(panel, idx) -> dict:
    """AR(1) of every candidate flow proxy, weekly and monthly.

    Run as part of T0 rather than as a side experiment: if the spec's proxy has
    no persistence, the first question is whether ANY price-derived proxy does.
    """
    import pandas as pd
    C, H, L, O, V = panel.close, panel.high, panel.low, panel.open, panel.volume
    prev = np.vstack([np.full((1, C.shape[1]), np.nan), C[:-1]])
    ret = C / prev - 1.0
    dv = C * V
    rng = np.where(H - L > 0, H - L, np.nan)

    cands = {
        "sign(r)·$vol  (spec)": np.sign(ret) * dv,
        "CLV·$vol  (Chaikin)": (((C - L) - (H - C)) / rng) * dv,
        "r·$vol  (magnitude)": ret * dv,
        "(C−O)/range·$vol": ((C - O) / rng) * dv,
        "sign(r)·√$vol": np.sign(ret) * np.sqrt(dv),
        "unsigned $vol  (control)": dv,
    }
    out = {}
    for name, mat in cands.items():
        d = pd.DataFrame(mat, index=idx, columns=panel.symbols)
        row = {}
        for label, freq in (("weekly", "W-FRI"), ("monthly", "ME")):
            w = d.resample(freq).sum(min_count=3)
            a = np.array([x for x in (w[c].autocorr(1) for c in w.columns)
                          if np.isfinite(x)])
            row[label] = float(a.mean()) if a.size else float("nan")
        out[name] = row
    return out


def cmd_stage1(args) -> int:
    out_dir = Path(args.out or (OUTPUT_ROOT / "flow" / "stage1"))
    prereg = s1.preregister(out_dir, notes=args.notes or "")
    print(f"Pre-registered {prereg['n_variants']} variants -> "
          f"{out_dir / 'preregistration.json'}\n")

    cfg, panel, shares, share_cov = _load(args.limit, args.start, args.end)

    print("Computing Tier-1 flow signals…")
    sig = compute_flow_signals(panel, shares_out=shares)

    df = build_dataset(sig, horizon_days=args.horizon, min_names=args.min_names)
    if df.empty:
        print("No usable cross-sections — check the data window.")
        return 1

    band = s1.CAP_BANDS[args.band]
    df_band = df[(df["market_cap"] >= band[0]) & (df["market_cap"] < band[1])]
    counts = df_band.groupby("date")["symbol"].transform("size")
    df_band = df_band[counts >= args.min_names]
    print(f"\nUniverse: {args.band} ${band[0]/1e9:.0f}B-${band[1]/1e9:.0f}B  "
          f"rows={len(df_band):,}  cross-sections={df_band['date'].nunique()}  "
          f"avg names={df_band.groupby('date').size().mean():.0f}")

    prep = prepare_cross_sections(df_band, REGRESSORS, INTERACTIONS)

    # ---------------- models ------------------------------------------
    print("\n" + "=" * 62)
    print("PRE-REGISTERED MODELS (Fama-MacBeth, Newey-West t-stats)")
    print("=" * 62)
    models = s1.run_models(prep, nw_lags=args.nw_lags)
    for name, res in models.items():
        print(f"\n--- {name} ---")
        print(res.table())

    # ---------------- falsification -----------------------------------
    print("\n" + "=" * 62)
    print("FALSIFICATION BATTERY")
    print("=" * 62)
    tests: dict = {}

    # --- T0: precondition ------------------------------------------------
    import pandas as _pd
    _idx = _pd.DatetimeIndex(panel.dates)
    _dv = _pd.DataFrame(sig.dollar_volume, index=_idx, columns=panel.symbols)
    _w = _dv.resample("W-FRI").sum(min_count=3)
    _ac = np.array([x for x in (_w[c].autocorr(1) for c in _w.columns) if np.isfinite(x)])
    unsigned_ar1 = float(_ac.mean()) if _ac.size else None

    proxy_ar1 = _proxy_persistence(panel, _idx)
    tests["T0"] = s1.check_inertia_exists(sig, unsigned_ar1=unsigned_ar1)
    tests["T0"]["proxy_comparison"] = proxy_ar1
    print("\nT0 — does the forcing function have measurable inertia at all?")
    t0 = tests["T0"]
    if t0.get("available"):
        print(f"   rho (weekly summed signed flow): mean {t0['rho_mean']:+.4f}  "
              f"median {t0['rho_median']:+.4f}  sd {t0['rho_sd']:.4f}")
        print(f"   detectable at |rho| > {t0['detectable_threshold']:.3f} "
              f"(2 s.e. on a {26}-week AR(1)); "
              f"{t0['share_above_threshold']:.1%} of observations clear it")
        if unsigned_ar1 is not None:
            print(f"   for contrast, UNSIGNED dollar volume AR(1) = {unsigned_ar1:+.3f}")
        print(f"   rho_ema (the spec's smoothed variant): mean {t0['rho_ema_mean']:+.4f}")
        if t0.get("smoothing_artefact_warning"):
            print(f"   !! {t0['smoothing_artefact_warning']}")
        print(f"   {'PASS' if t0['pass'] else 'FAIL'}")

    tests["T1"] = s1.check_momentum_by_rho(df_band, min_per_cs=max(50, args.min_names))
    print("\nT1 — is momentum increasing in flow persistence (rho)?")
    if tests["T1"].get("available"):
        for b in tests["T1"]["buckets"]:
            print(f"   rho Q{b['rho_bucket']+1}: 12-1 momentum spread "
                  f"{b['annualised']:+.2%}/yr  (t={b['t']:+.2f})")
        print(f"   Spearman(rho bucket, momentum) = "
              f"{tests['T1']['spearman_rho_vs_momentum']:+.2f}   "
              f"{'PASS' if tests['T1']['pass'] else 'FAIL'}")
    else:
        print("   unavailable:", tests["T1"].get("reason"))

    tests["T2"] = s1.check_event_time(sig, horizon=args.event_horizon)
    print("\nT2 — event-time drift after F crosses 1, by rho tercile:")
    if tests["T2"].get("available"):
        for name, c in tests["T2"]["curves"].items():
            print(f"   {name:<10} n={c['n']:>6}  +20d {c['cum_20d']:+.2%}  "
                  f"+40d {c['cum_40d']:+.2%}  +60d {c['cum_60d']:+.2%}  "
                  f"(median T_half {c['median_t_half_weeks']:.1f}w)")
        print(f"   {'PASS' if tests['T2'].get('pass') else 'FAIL'}")
    else:
        print("   unavailable:", tests["T2"].get("reason"))

    tests["T3"] = s1.check_impact_law(df_band)
    print("\nT3 — does the square-root impact law hold here?")
    if tests["T3"].get("available"):
        t3 = tests["T3"]
        print(f"   raw OLS      |move|/σ = {t3['intercept']:.3f} + {t3['slope_Y']:.3f}·√|F|"
              f"   (n={t3['n']:,}, p={t3['p']:.1e})")
        print(f"   binned means |move|/σ = {t3['binned_intercept']:.3f} + "
              f"{t3['binned_slope_Y']:.3f}·√|F|   (R²={t3['binned_r2']:.3f})  <- the "
              "impact-literature estimator")
        if t3.get("midrange_slope_Y") is not None:
            print(f"   mid-range only                       Y = {t3['midrange_slope_Y']:.3f}"
                  f"   (where the square-root law is actually claimed to hold)")
        print(f"   baseline move at ~zero flow: {t3['baseline_move_at_zero_flow']:.2f}σ  "
              f"| curvature {t3['curvature']:+.3f}")
        k = t3.get("knee") or {}
        if k:
            print(f"   INERTIA KNEE at F = {k['breakpoint_F']:.2f}  "
                  f"(flow = {k['breakpoint_F']*100:.0f}% of Q_break)")
            print(f"      slope below the knee {k['slope_below']:+.3f}  ->  "
                  f"above {k['slope_above']:+.3f}   "
                  f"({k['improvement_over_straight_line']:.0%} better than a straight line)")
        fw = t3.get("forward_control") or {}
        if fw:
            print(f"   CIRCULARITY CONTROL — same fit on the NEXT window's move")
            print(f"      (F shares no return signs with the target):")
            print(f"      Y = {fw['slope_Y']:+.3f}  intercept {fw['intercept']:.3f}  "
                  f"R² = {fw['r2']:.4f}  p = {fw['p']:.2e}  n = {fw['n']:,}")
            ratio = fw["slope_Y"] / t3["binned_slope_Y"] if t3["binned_slope_Y"] else 0.0
            print(f"      forward slope is {ratio:.0%} of the contemporaneous slope -> "
                  + ("the contemporaneous fit is largely an accounting identity"
                     if abs(ratio) < 0.25 else
                     "a substantial part of the relationship survives"))
        print(f"   literature prior Y in 0.5-1.0   {'PASS' if t3['pass'] else 'FAIL'}")

    # T4 placebo
    print("\nT4 — placebo: rebuild rho and F on randomly re-signed volume.")
    ph = placebo_flow_signals(panel, seed=args.seed)
    # Keep the real size and turnover: the placebo destroys flow DIRECTION only,
    # so everything not derived from the sign must stay identical or the two
    # regressions differ in more than the one thing being tested.
    ph.market_cap = sig.market_cap
    ph.turnover = sig.turnover
    df_p = build_dataset(ph, horizon_days=args.horizon, min_names=args.min_names)
    df_p = df_p[(df_p["market_cap"] >= band[0]) & (df_p["market_cap"] < band[1])]
    prep_p = prepare_cross_sections(df_p, REGRESSORS, INTERACTIONS)
    placebo_models = s1.run_models(prep_p, nw_lags=args.nw_lags)
    real = models.get("M5_add_interaction")
    fake = placebo_models.get("M5_add_interaction")
    rk = real.coefficients.get(s1.KEY_TERM) if real else None
    fk = fake.coefficients.get(s1.KEY_TERM) if fake else None
    if rk and fk:
        real_is_null = abs(rk["t"]) < 2.0
        died = abs(fk["t"]) < 2.0 and abs(fk["t"]) < abs(rk["t"])
        print(f"   real    {s1.KEY_TERM}: coef {rk['coef']:+.5f}  t {rk['t']:+.2f}  p {rk['p']:.4f}")
        print(f"   placebo {s1.KEY_TERM}: coef {fk['coef']:+.5f}  t {fk['t']:+.2f}  p {fk['p']:.4f}")
        if real_is_null:
            # There is no signal for the placebo to fail to reproduce. Calling
            # this a pass would flatter the result; calling it a fail would
            # imply the placebo found something. Neither is true.
            print("   VACUOUS — the real signal is itself null, so the placebo "
                  "comparison carries no information.")
        else:
            print(f"   {'PASS — signal dies on re-signed volume' if died else 'FAIL — signal survives the placebo'}")
        tests["T4"] = {"available": True, "pass": bool(died and not real_is_null),
                       "vacuous": bool(real_is_null),
                       "real_t": rk["t"], "placebo_t": fk["t"],
                       "detail": (f"real t={rk['t']:+.2f}, placebo t={fk['t']:+.2f}"
                                  + (" (vacuous: real signal is null)" if real_is_null else ""))}
        # The rho_ema contrast: the smoothed estimator should look persistent
        # even on noise, which is why it is not the primary estimator.
        for tag, mods in (("real", models), ("placebo", placebo_models)):
            m = mods.get("M5_add_interaction")
            if m and "rho_ema_z" in m.coefficients:
                tests["T4"].setdefault("rho_ema_t", {})[tag] = m.coefficients["rho_ema_z"]["t"]
    else:
        tests["T4"] = {"available": False, "pass": False, "detail": "placebo did not fit"}
        print("   unavailable")

    # T5 cap bands
    print("\nT5 — cap-band controls (effect should be strongest in mid-caps):")
    band_models = {}
    for band_name, (lo, hi) in s1.CAP_BANDS.items():
        sub = df[(df["market_cap"] >= lo) & (df["market_cap"] < hi)]
        c = sub.groupby("date")["symbol"].transform("size")
        sub = sub[c >= args.min_names]
        if sub.empty or sub["date"].nunique() < 24:
            print(f"   {band_name:<20} too few cross-sections ({sub['date'].nunique()})")
            continue
        p = prepare_cross_sections(sub, REGRESSORS, INTERACTIONS)
        band_models[band_name] = s1.run_models(p, nw_lags=args.nw_lags)
        m = band_models[band_name].get("M5_add_interaction")
        k = m.coefficients.get(s1.KEY_TERM) if m else None
        if k:
            print(f"   {band_name:<20} {s1.KEY_TERM} coef {k['coef']:+.5f}  "
                  f"t {k['t']:+.2f}  (avg {m.mean_obs:.0f} names, {m.n_periods} months)")
    tests["T5"] = s1.check_cap_bands(band_models)

    # ---------------- supporting sorts ---------------------------------
    sorts = {}
    for var in ("rho", "F", "t_half"):
        sorts[var] = long_short_spread(df_band, var)
    print("\nSupporting univariate sorts (top-minus-bottom quintile, monthly):")
    for var, r in sorts.items():
        if np.isfinite(r.get("t", np.nan)):
            print(f"   {var:<8} {r['annualised']:+.2%}/yr  t={r['t']:+.2f}  "
                  f"Sharpe={r['sharpe']:.2f}  ({r['n_periods']} months)")

    # ---------------- verdict ------------------------------------------
    v = s1.verdict(models, tests, prereg["n_variants"])
    print("\n" + "=" * 62)
    print("VERDICT")
    print("=" * 62)
    for name, c in v["checks"].items():
        print(f"  [{'PASS' if c['pass'] else 'FAIL'}] {name}")
    print(f"\n  Bonferroni alpha = {v['bonferroni_alpha']:.5f} "
          f"({v['n_variants']} pre-registered variants)")
    print(f"\n  {v['statement']}")

    result = s1.Stage1Result(
        universe={"band": args.band, "range": list(band), "rows": int(len(df_band)),
                  "cross_sections": int(df_band["date"].nunique()),
                  "avg_names": float(df_band.groupby("date").size().mean()),
                  "symbols_loaded": int(len(panel.symbols)),
                  "share_count_coverage": share_cov,
                  "start": str(panel.dates[0]), "end": str(panel.dates[-1])},
        models={k: {"formula": m.formula, "n_periods": m.n_periods,
                    "mean_obs": m.mean_obs, "r2_mean": m.r2_mean,
                    "coefficients": m.coefficients} for k, m in models.items()},
        tests=tests, verdict=v, preregistration=prereg,
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "stage1.json").write_text(json.dumps(result.to_dict(), indent=2, default=str))
    df_band.to_csv(out_dir / "panel.csv.gz", index=False, compression="gzip")

    images: list[Path] = []
    if not args.no_charts:
        from ..charts import contact_sheet
        from . import charts as fc
        print("\nRendering charts…")
        images.append(fc.rho_distribution_chart(sig, out_dir, unsigned_ar1))
        images.append(fc.proxy_comparison_chart(
            {k: v for k, v in tests["T0"]["proxy_comparison"].items()}, out_dir))
        images.append(fc.impact_law_chart(df_band, out_dir,
                                          knee=(tests.get("T3") or {}).get("knee")))
        for maker, arg in ((fc.event_time_chart, tests.get("T2")),
                           (fc.momentum_by_rho_chart, tests.get("T1"))):
            got = maker(arg, out_dir)
            if got:
                images.append(got)
        got = fc.coefficient_chart(result.models, out_dir)
        if got:
            images.append(got)
        sheet = contact_sheet(
            images, out_dir / "report.html",
            "Flow-Inertia Momentum — Stage 1",
            f"{result.universe['cross_sections']} monthly cross-sections, "
            f"{result.universe['avg_names']:.0f} names each, "
            f"{result.universe['start'][:10]} to {result.universe['end'][:10]} · "
            f"{'PROCEED' if v['proceed_to_stage_2'] else 'DO NOT PROCEED'}")
        print(f"-> {sheet}   (open this)")

    print(f"\n-> {out_dir / 'stage1.json'}")
    print(f"-> {out_dir / 'panel.csv.gz'}  (the panel, for your own inspection)")
    for i in images:
        print(f"-> {i}")
    return 0


def cmd_tier2(args) -> int:
    """Ingest mechanical ETF flow, then test whether IT has inertia."""
    from .etf_flow import ETFFlowStore, validate_shares_outstanding

    load_env()
    store = ETFFlowStore()
    cfg, panel, shares, _cov = _load(args.limit, args.start, args.end)
    sig = compute_flow_signals(panel, shares_out=shares)

    # ---- the strategy universe, per the screener spec --------------------
    from ..data.earnings import EarningsStore
    from .universe import UniverseSpec, build_universe, listing_metadata

    spec = UniverseSpec(min_etf_ownership=args.min_etf_ownership,
                        min_adv_usd=args.min_adv)
    meta = listing_metadata()

    # The ETF-ownership gate needs the weight maps, so they are pulled for the
    # cap-band candidates first and the gate applied afterwards.
    cap = sig.market_cap
    in_band = np.array([
        bool(np.isfinite(cap[:, j]).any()
             and np.nanmax(cap[:, j]) >= spec.min_market_cap
             and np.nanmin(cap[np.isfinite(cap[:, j]), j]) < spec.max_market_cap)
        for j in range(len(panel.symbols))])
    candidates = [panel.symbols[j] for j in np.flatnonzero(in_band)]
    print(f"{len(candidates)} names touch the $2–50B band at some point")

    if args.sync:
        print("\nSyncing stock -> ETF weight maps…")
        print(json.dumps(store.sync_weights(candidates, workers=args.workers), indent=2))
        print("Syncing earnings announcement dates…")
        print(json.dumps(EarningsStore().ensure(candidates, workers=args.workers), indent=2))

    earn = EarningsStore().all_dates(candidates)
    uni = build_universe(panel, shares, sig.adv, sig.market_cap, spec,
                         weights_loader=store.load_weights,
                         earnings_dates=earn, listing_meta=meta)
    print("\n" + uni.summary())

    eligible_any = uni.mask.any(axis=0)
    keep = list(np.flatnonzero(eligible_any))
    symbols = [panel.symbols[j] for j in keep]
    if not symbols:
        print("\nUniverse is empty — check the filters.")
        return 1

    if args.sync:
        etfs = store.etfs_referenced(symbols, top_n=args.max_etfs)
        print("\nTop ETFs by dollar exposure to this universe:")
        for row in store.exposure_table(symbols, top_n=10):
            print(f"   {row['etf']:<8} ${row['usd_exposure']/1e9:8.2f}B")
        print(f"\n{len(etfs)} ETFs referenced; validating the share-count gate on a sample…")
        sample = validate_shares_outstanding(etfs[:12], args.start, args.end)
        usable = sum(r.usable for r in sample)
        for r in sample:
            print(f"   {r.symbol:<8} sessions={r.sessions:<5} distinct_SO={r.distinct_so_levels:<5} "
                  f"change_days={r.days_with_change:<5} {'ok' if r.usable else 'UNUSABLE: ' + r.note}")
        if usable < len(sample) * 0.6:
            print("\n! Most sampled ETFs have static implied share counts — the flow "
                  "series would be identically zero. Aborting before wasting the pull.")
            return 1
        print(f"\nSyncing daily flow for {len(etfs)} ETFs…")
        print(json.dumps(store.sync_flows(etfs, args.start, args.end,
                                          workers=args.workers), indent=2))

    print("\nBuilding AIT (arbitrage-induced trading)…")
    dv = sig.dollar_volume[:, keep]
    ait, stats, ait_raw = store.build_ait(symbols, panel.dates, dv)
    stats["universe_funnel"] = {k: (int(v) if isinstance(v, (int, np.integer)) else v)
                                for k, v in uni.funnel.items()}
    print(json.dumps(stats, indent=2))
    if stats.get("error"):
        return 1

    # ---- the same T0 question, now on mechanical flow -------------------
    idx = pd.DatetimeIndex(panel.dates)
    # Only measure where the name is actually eligible: rho computed over
    # periods when a stock was outside the universe is not a property of the
    # strategy's universe.
    def _ar1(mat):
        masked = np.where(uni.mask[:, keep], mat, np.nan)
        w = pd.DataFrame(masked, index=idx, columns=symbols).resample("W-FRI").sum(min_count=3)
        return np.array([x for x in (w[c].autocorr(1) for c in w.columns)
                         if np.isfinite(x)])

    ar = _ar1(ait)
    ar_raw = _ar1(ait_raw)
    nz = float(np.mean(np.abs(ait[np.isfinite(ait)]) > 1e-12))

    print("\n" + "=" * 62)
    print("T0 ON MECHANICAL FLOW — does AIT have inertia?")
    print("=" * 62)
    print(f"   non-zero share of the AIT matrix: {nz:.1%}")
    detect = 2.0 / np.sqrt(26)
    print(f"   AIT ÷ dollar volume : weekly AR(1) mean {ar.mean():+.4f}  "
          f"median {np.median(ar):+.4f}  ({float((ar > detect).mean()):.1%} detectable)")
    print(f"   AIT in raw dollars  : weekly AR(1) mean {ar_raw.mean():+.4f}  "
          f"median {np.median(ar_raw):+.4f}  ({float((ar_raw > detect).mean()):.1%} detectable)")
    print(f"   detectable at |ρ| > {detect:.3f}   (n={ar.size} names)")
    if ar.mean() > detect / 2 and ar_raw.mean() < detect / 4:
        print("   ! The scaled series looks persistent but the raw one does not — "
              "that persistence is the dollar-volume denominator, not the flow.")
    # Inertia is a POSITIVE autocorrelation. Testing |rho| would score a
    # strongly mean-reverting series as a strong pass, which is the opposite of
    # the mechanism being tested — flow that alternates sign week to week is
    # evidence against Vayanos-Woolley, not for it.
    if ar.mean() > detect / 2 and ar_raw.mean() > detect / 4:
        verdict_txt = ("PASS — mechanical flow is positively persistent in both the raw "
                       "and scaled series; rho is measurable and Stage 1 can be re-run on it")
    elif ar.mean() < -detect / 2:
        verdict_txt = (f"FAIL — mechanical flow is ANTI-persistent (rho = {ar.mean():+.3f}). "
                       "Creations are followed by redemptions, which is mean reversion, not "
                       "inertia. Check whether this is real AP behaviour or an artefact of "
                       "lumpy share-count reporting before concluding anything about the market.")
    else:
        verdict_txt = "FAIL — mechanical flow shows no positive persistence at this granularity"
    print(f"\n   {verdict_txt}")

    out_dir = Path(args.out or (OUTPUT_ROOT / "flow" / "tier2"))
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "tier2.json").write_text(json.dumps({
        "band": args.band, "symbols": len(symbols), "window": [args.start, args.end],
        "ait_stats": stats, "nonzero_share": nz,
        "weekly_ar1_mean": float(ar.mean()), "weekly_ar1_median": float(np.median(ar)),
        "weekly_ar1_raw_dollars_mean": float(ar_raw.mean()),
        "weekly_ar1_raw_dollars_median": float(np.median(ar_raw)),
        "share_detectable": float((ar > detect).mean()),
        "verdict": verdict_txt,
    }, indent=2, default=str))
    print(f"\n-> {out_dir / 'tier2.json'}")

    if not args.no_charts:
        from ..charts import _note, _save
        import matplotlib.pyplot as plt
        from ..charts import ACCENT, INK, MUTED, POS, WARN
        fig, ax = plt.subplots(figsize=(9, 4.6))
        ax.hist(ar, bins=60, color=POS, alpha=0.85, edgecolor="white", linewidth=0.3,
                label=f"ρ of mechanical ETF flow (mean {ar.mean():+.3f})")
        rho_t1 = sig.rho[np.isfinite(sig.rho)]
        ax.hist(rho_t1, bins=60, color=ACCENT, alpha=0.45, edgecolor="white",
                linewidth=0.3, density=False,
                weights=np.full(rho_t1.size, ar.size / max(rho_t1.size, 1)),
                label=f"ρ of Tier-1 signed volume (mean {rho_t1.mean():+.3f})")
        ax.axvline(0, color=INK, lw=1.2)
        ax.axvline(detect, color=WARN, ls="--", lw=1.5)
        ax.annotate(f"detectable |ρ| > {detect:.2f}", xy=(detect, ax.get_ylim()[1] * .9),
                    xytext=(6, 0), textcoords="offset points", fontsize=8.5, color=WARN)
        ax.set_xlabel("AR(1) persistence")
        ax.set_ylabel("names (Tier-1 rescaled to match)")
        ax.set_title("Does mechanical flow have the inertia that price-derived flow lacks?")
        _note(ax, f"AIT built from ETF creations/redemptions across "
                  f"{stats['etfs_with_flow']} ETFs covering {stats['coverage']:.0%} of the "
                  "universe. This flow is direction-known and independent of the stock's "
                  "own returns.")
        ax.legend(frameon=False, fontsize=8.5)
        print(f"-> {_save(fig, out_dir, 'tier2_rho.png')}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="strategylab.flow", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--log", default="INFO")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("stage1", help="panel evidence — the gate")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--start", default="2014-01-01")
    p.add_argument("--end", default="2026-06-30")
    p.add_argument("--band", default="mid_cap_target", choices=list(s1.CAP_BANDS))
    p.add_argument("--horizon", type=int, default=21, help="forward-return days")
    p.add_argument("--event-horizon", type=int, default=60)
    p.add_argument("--min-names", type=int, default=50)
    p.add_argument("--nw-lags", type=int, default=6)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--out", default=None)
    p.add_argument("--notes", default="")
    p.add_argument("--no-charts", action="store_true")
    p.set_defaults(func=cmd_stage1)

    p = sub.add_parser("tier2", help="mechanical ETF flow — the Tier-2 inertia test")
    p.add_argument("--sync", action="store_true", help="pull weights + ETF flows first")
    p.add_argument("--limit", type=int, default=800)
    p.add_argument("--start", default="2021-06-01")
    p.add_argument("--end", default="2026-06-30")
    p.add_argument("--band", default="mid_cap_target", choices=list(s1.CAP_BANDS))
    p.add_argument("--max-etfs", type=int, default=300)
    p.add_argument("--min-etf-ownership", type=float, default=0.03,
                   help="minimum share of stock held by ETFs (the AIT precondition)")
    p.add_argument("--min-adv", type=float, default=10e6)
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--out", default=None)
    p.add_argument("--no-charts", action="store_true")
    p.set_defaults(func=cmd_tier2)

    args = ap.parse_args(argv)
    logging.basicConfig(level=getattr(logging, args.log.upper(), logging.INFO),
                        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
                        datefmt="%H:%M:%S")
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
