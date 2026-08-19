"""Stage 1 — does rho x F predict returns beyond price momentum?

This module runs a PRE-REGISTERED set of models and falsification tests and
then states a verdict. The pre-registration matters more than it looks: the
brief's own warning is that a t-stat of 2 after 30 variations is noise, so the
variant list is written to disk before the data is touched and the reported
significance is haircut by the number of variants actually run.

The verdict is deliberately hard to pass. Six conditions, and the interaction
being significant is only one of them — a signal that survives the interaction
test but dies on the placebo is a volume-and-volatility effect, not flow.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from .panel import (FMResult, build_dataset, fama_macbeth, long_short_spread,
                    prepare_cross_sections, quantile_sort)
from .signals import AR_WINDOW_WEEKS, FlowSignals

# Cap bands, in dollars. The mid-cap band is where the theory says the signal
# should live; the other two are CONTROLS, not extra chances to find something.
# Mega-caps have deep elastic capital that absorbs flow; micro-caps are maximally
# inelastic but their estimators are noise. If the effect is strongest in
# mega-caps, that is evidence of having fitted something other than the
# mechanism — a falsification, obtained for free.
CAP_BANDS: dict[str, tuple[float, float]] = {
    "mid_cap_target": (2e9, 50e9),
    "mega_cap_control": (50e9, 1e15),
    "small_cap_control": (1e8, 2e9),
}

BASE_CONTROLS = ["mom_12_1", "strev", "log_cap", "log_turnover", "sigma", "log_illiq"]

# --- the pre-registered variant list ---------------------------------------
PREREGISTERED_MODELS = [
    ("M1_momentum_only", ["mom_12_1_z"]),
    ("M2_momentum_controls", [c + "_z" for c in BASE_CONTROLS]),
    ("M3_add_rho", [c + "_z" for c in BASE_CONTROLS] + ["rho_z"]),
    ("M4_add_F", [c + "_z" for c in BASE_CONTROLS] + ["rho_z", "F_z"]),
    ("M5_add_interaction", [c + "_z" for c in BASE_CONTROLS]
                           + ["rho_z", "F_z", "rho_x_F_z"]),
]
PREREGISTERED_TESTS = [
    "T0_forcing_function_has_measurable_inertia",
    "T1_momentum_increasing_in_rho",
    "T2_event_time_drift_by_rho",
    "T3_impact_law_slope_Y",
    "T4_placebo_resigned_volume",
    "T5_cap_band_controls",
]
KEY_TERM = "rho_x_F_z"


@dataclass
class Stage1Result:
    universe: dict = field(default_factory=dict)
    models: dict = field(default_factory=dict)
    tests: dict = field(default_factory=dict)
    verdict: dict = field(default_factory=dict)
    preregistration: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"universe": self.universe, "models": self.models,
                "tests": self.tests, "verdict": self.verdict,
                "preregistration": self.preregistration}


def preregister(out_dir: Path, notes: str = "") -> dict:
    """Write the variant list BEFORE looking at results.

    The file is the honesty mechanism: any model or test not in it, run later
    and reported, is a post-hoc variant and inflates the effective trial count.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "registered_at": datetime.now().isoformat(timespec="seconds"),
        "models": [name for name, _ in PREREGISTERED_MODELS],
        "tests": list(PREREGISTERED_TESTS),
        "key_term": KEY_TERM,
        "n_variants": len(PREREGISTERED_MODELS) + len(PREREGISTERED_TESTS),
        "decision_rule": (
            "Proceed to Stage 2 only if the rho x F interaction is significant "
            "at the Bonferroni-adjusted level with all controls in, AND the "
            "placebo dies, AND the effect is not strongest in the mega-cap "
            "control band."
        ),
        "notes": notes,
    }
    (out_dir / "preregistration.json").write_text(json.dumps(payload, indent=2))
    return payload


# ----------------------------------------------------------------------
def _regressors_present(df: pd.DataFrame, xs: list[str]) -> list[str]:
    return [x for x in xs if x in df.columns and df[x].notna().sum() > 100]


def run_models(df: pd.DataFrame, nw_lags: int = 6) -> dict[str, FMResult]:
    out = {}
    for name, xs in PREREGISTERED_MODELS:
        present = _regressors_present(df, xs)
        if not present:
            continue
        out[name] = fama_macbeth(df, "fwd_ret", present, nw_lags=nw_lags)
    return out


def check_inertia_exists(sig: FlowSignals, unsigned_ar1: float | None = None) -> dict:
    """T0 — the precondition. Does the forcing function have ANY persistence?

    Everything downstream assumes rho measures something. If the flow proxy's
    own autocorrelation is indistinguishable from zero, then rho is noise, the
    rho x F interaction is noise times something, and no amount of careful
    regression downstream can rescue it.

    This also reports `rho_ema` side by side, because the spec's smoothed
    estimator will look strongly persistent even when the underlying series is
    white noise — that gap is the whole reason T0 exists.
    """
    rho = sig.rho[np.isfinite(sig.rho)]
    rho_ema = sig.rho_ema[np.isfinite(sig.rho_ema)]
    if rho.size < 1000:
        return {"available": False, "reason": "too few rho observations"}

    mean_rho = float(rho.mean())
    # Standard error of an AR(1) estimate over an n-week window is ~1/sqrt(n).
    se = 1.0 / np.sqrt(AR_WINDOW_WEEKS)
    detectable = 2.0 * se

    out = {
        "available": True,
        "rho_mean": mean_rho,
        "rho_median": float(np.median(rho)),
        "rho_sd": float(rho.std()),
        "rho_pct_10_50_90": [float(x) for x in np.percentile(rho, [10, 50, 90])],
        "rho_ema_mean": float(rho_ema.mean()) if rho_ema.size else None,
        "detectable_threshold": detectable,
        "share_above_threshold": float((rho > detectable).mean()),
        "unsigned_volume_ar1": unsigned_ar1,
        "pass": bool(abs(mean_rho) > detectable / 2),
    }
    if out["rho_ema_mean"] is not None and abs(out["rho_ema_mean"]) > 0.3 and abs(mean_rho) < 0.1:
        out["smoothing_artefact_warning"] = (
            f"rho_ema averages {out['rho_ema_mean']:+.2f} while raw rho averages "
            f"{mean_rho:+.2f}. The smoothed estimator is reporting the EMA's own "
            f"memory, not the stock's. Using it would produce a plausible-looking "
            f"inertia measure built entirely out of the filter.")
    return out


# --- T1: momentum profits should increase in rho ---------------------------
def check_momentum_by_rho(df: pd.DataFrame, q: int = 5, min_per_cs: int = 100) -> dict:
    """Standard 12-1 momentum long-short spread, computed WITHIN each rho quintile.

    The mechanism's sharpest cross-sectional prediction: if flow inertia is what
    makes momentum work, momentum should be strong where flow persists and weak
    where it does not. If momentum is just as strong in the low-rho quintile,
    inertia is not the driver — whatever else the data says.
    """
    rows = []
    for date, g in df.groupby("date", sort=True):
        g = g[["rho", "mom_12_1", "fwd_ret"]].dropna()
        if len(g) < min_per_cs:
            continue
        try:
            rq = pd.qcut(g["rho"], q, labels=False, duplicates="drop")
        except ValueError:
            continue
        for bucket in sorted(set(rq.dropna())):
            sub = g[rq == bucket]
            if len(sub) < 15:
                continue
            try:
                mq = pd.qcut(sub["mom_12_1"], q, labels=False, duplicates="drop")
            except ValueError:
                continue
            hi = sub["fwd_ret"][mq == mq.max()].mean()
            lo = sub["fwd_ret"][mq == mq.min()].mean()
            rows.append({"date": date, "rho_bucket": int(bucket), "spread": hi - lo})
    if not rows:
        return {"available": False, "reason": "insufficient cross-sections"}

    per = pd.DataFrame(rows)
    from .panel import _newey_west_t
    buckets = []
    for b in sorted(per["rho_bucket"].unique()):
        s = per[per["rho_bucket"] == b]["spread"].to_numpy()
        mu, _se, t = _newey_west_t(s, 6)
        buckets.append({"rho_bucket": int(b), "momentum_spread_monthly": mu,
                        "annualised": mu * 12 if np.isfinite(mu) else np.nan,
                        "t": t, "n_periods": int(s.size)})
    vals = [b["momentum_spread_monthly"] for b in buckets]
    slope = float(stats.spearmanr(np.arange(len(vals)), vals).statistic) if len(vals) > 2 else 0.0
    top_minus_bottom = vals[-1] - vals[0] if len(vals) > 1 else np.nan
    return {"available": True, "buckets": buckets, "spearman_rho_vs_momentum": slope,
            "top_minus_bottom_monthly": top_minus_bottom,
            "pass": bool(slope > 0.5 and np.isfinite(top_minus_bottom)
                         and top_minus_bottom > 0)}


# --- T2: event-time drift after F crosses 1, split by rho -------------------
def check_event_time(sig: FlowSignals, horizon: int = 60, threshold: float = 1.0,
                    min_events: int = 200) -> dict:
    """The single most informative chart in the brief.

    Average return in event time after F crosses above `threshold`, split by rho
    tercile. The theory predicts drift lasting about T_half then flattening for
    high-rho names, and immediate reversal for low-rho names. A shape is much
    harder to overfit than a Sharpe ratio, which is exactly why it is the test.
    """
    F = sig.forcing
    rho = sig.rho
    ret = np.nan_to_num(sig.ret, nan=0.0)
    valid = np.isfinite(sig.ret)

    crossed = (F > threshold) & (np.vstack([np.zeros((1, F.shape[1]), dtype=bool),
                                            (F <= threshold)[:-1]]))
    crossed &= np.isfinite(rho)

    rows_t, rows_j = np.nonzero(crossed)
    keep = (rows_t > 260) & (rows_t < len(sig.dates) - horizon - 1)
    rows_t, rows_j = rows_t[keep], rows_j[keep]
    if rows_t.size < min_events:
        return {"available": False, "n_events": int(rows_t.size),
                "reason": f"only {rows_t.size} events (need {min_events})"}

    rho_at_event = rho[rows_t, rows_j]
    finite = np.isfinite(rho_at_event)
    rows_t, rows_j, rho_at_event = rows_t[finite], rows_j[finite], rho_at_event[finite]
    lo_c, hi_c = np.quantile(rho_at_event, [1 / 3, 2 / 3])

    groups = {"low_rho": rho_at_event <= lo_c,
              "mid_rho": (rho_at_event > lo_c) & (rho_at_event <= hi_c),
              "high_rho": rho_at_event > hi_c}

    out: dict = {"available": True, "n_events": int(rows_t.size),
                 "rho_terciles": [float(lo_c), float(hi_c)], "curves": {}}
    for name, mask in groups.items():
        tt, jj = rows_t[mask], rows_j[mask]
        if tt.size < 30:
            continue
        # Cumulative average abnormal-free return in event time.
        path = np.zeros(horizon)
        counts = np.zeros(horizon)
        for h in range(horizon):
            r = ret[tt + h + 1, jj]
            v = valid[tt + h + 1, jj]
            path[h] = np.nanmean(np.where(v, r, np.nan)) if v.any() else 0.0
            counts[h] = v.sum()
        cum = np.cumsum(np.nan_to_num(path))
        out["curves"][name] = {
            "n": int(tt.size),
            "cum_return_by_day": [round(float(x), 5) for x in cum],
            "cum_20d": float(cum[min(19, horizon - 1)]),
            "cum_40d": float(cum[min(39, horizon - 1)]),
            "cum_60d": float(cum[horizon - 1]),
            "median_t_half_weeks": float(np.nanmedian(sig.t_half[tt, jj])),
        }

    hi = out["curves"].get("high_rho", {})
    lo = out["curves"].get("low_rho", {})
    if hi and lo:
        out["high_minus_low_20d"] = hi["cum_20d"] - lo["cum_20d"]
        # The prediction is directional and specific: high-rho drifts, low-rho
        # does not (and ideally reverses).
        out["pass"] = bool(hi["cum_20d"] > 0 and hi["cum_20d"] > lo["cum_20d"])
    else:
        out["pass"] = False
    return out


# --- T3: does the impact law hold on this universe? ------------------------
def check_impact_law(df: pd.DataFrame) -> dict:
    """Regress |realised move| / sigma on sqrt(|F|); the slope should be ~Y.

    This is a check on the *physics*, independent of any return prediction. If
    the square-root law does not describe this universe, Q_break is mis-scaled
    and F means something other than 'forcing over resistance'.
    """
    # The impact law is a CONTEMPORANEOUS relationship: the flow that was
    # accumulated over the window is what moved the price over that same
    # window. Regressing the FORWARD return on it tests return predictability,
    # which is a different claim and will read as "the law fails" even when it
    # holds perfectly.
    col = "realised_20d" if "realised_20d" in df.columns else "fwd_ret"
    g = df[["F", col, "sigma"]].dropna()
    g = g[(g["sigma"] > 0) & (np.abs(g["F"]) > 1e-9)]
    if len(g) < 500:
        return {"available": False, "reason": "insufficient observations"}
    x = np.sqrt(np.abs(g["F"].to_numpy()))
    y = np.abs(g[col].to_numpy()) / (g["sigma"].to_numpy() * np.sqrt(21))
    ok = np.isfinite(x) & np.isfinite(y)
    x, y = x[ok], y[ok]
    keep = x <= np.quantile(x, 0.99)
    x, y = x[keep], y[keep]

    slope, intercept, r, p, se = stats.linregress(x, y)

    # The impact literature estimates this curve from BINNED conditional means,
    # not from raw scatter, and for good reason: |move| is heavily right-skewed,
    # so an OLS through the point cloud is pulled by the tail and does not track
    # E[|move| | F]. Binning first is the like-for-like estimate.
    b = pd.DataFrame({"x": x, "y": y})
    b["q"] = pd.qcut(b["x"], 40, labels=False, duplicates="drop")
    binned = b.groupby("q").agg(x=("x", "mean"), y=("y", "mean"), n=("y", "size"))
    bslope, bintercept, br, bp, bse = stats.linregress(binned["x"], binned["y"])

    # Curvature check: fit only the middle of the range, where the square-root
    # law is actually claimed to hold. Deviations at both extremes are the
    # documented behaviour (Zarinelli et al.), so a mid-range slope that differs
    # materially from the full-range one is expected, not a defect.
    mid = binned[(binned["x"] >= binned["x"].quantile(0.25))
                 & (binned["x"] <= binned["x"].quantile(0.85))]
    mslope, mintercept, mr, _mp, _mse = stats.linregress(mid["x"], mid["y"]) \
        if len(mid) > 5 else (np.nan,) * 5

    # Is the binned curve convex in sqrt-space? Compare a quadratic fit.
    quad = np.polyfit(binned["x"], binned["y"], 2)
    curvature = float(quad[0])

    # ---- the knee: where flow starts to move price at all ---------------
    # This is the brief's central question made empirical. Fit a two-segment
    # continuous piecewise line and take the breakpoint that minimises SSE:
    # below it price is inert to flow, above it the impact law bites. A knee
    # is a far more useful answer to "how much liquidity breaks inertia" than a
    # single slope, because it says there is a THRESHOLD, not just a gradient.
    knee = _fit_knee(binned["x"].to_numpy(), binned["y"].to_numpy())

    # ---- the circularity control ---------------------------------------
    # F is built from sign(r_t) of the SAME days whose move is on the left-hand
    # side, so the contemporaneous fit is partly tautological: a large |F| needs
    # consistent daily signs, and consistent daily signs mechanically produce a
    # large 20-day move. The honest version regresses the NEXT window's move on
    # this window's F, which shares no return signs at all. If the relationship
    # is real impact it survives; if it was an accounting identity it vanishes.
    fwd = _forward_impact_fit(df)

    xl = np.log1p(x ** 2)
    _s2, _i2, r2, _p2, _se2 = stats.linregress(xl, y)

    return {"available": True, "measured_on": col, "n": int(x.size),
            "slope_Y": float(slope), "intercept": float(intercept),
            "r": float(r), "p": float(p), "se": float(se),
            "binned_slope_Y": float(bslope), "binned_intercept": float(bintercept),
            "binned_r2": float(br ** 2),
            "midrange_slope_Y": float(mslope) if np.isfinite(mslope) else None,
            "midrange_intercept": float(mintercept) if np.isfinite(mintercept) else None,
            "curvature": curvature, "knee": knee, "forward_control": fwd,
            "contemporaneous_is_circular": True,
            "baseline_move_at_zero_flow": float(binned["y"].iloc[0]),
            "sqrt_form_r2": float(r ** 2), "log_form_r2": float(r2 ** 2),
            "better_form": "sqrt" if r ** 2 >= r2 ** 2 else "log",
            # The contemporaneous fit CANNOT establish the impact law, because F
            # is built from the signs of the returns it explains. The test passes
            # only if the forward control — which shares no signs with its target
            # — also finds a relationship.
            "pass": bool(fwd and fwd.get("p", 1.0) < 0.05
                         and 0.2 <= fwd.get("slope_Y", 0.0) <= 3.0)}


def _forward_impact_fit(df: pd.DataFrame) -> dict:
    """Same regression, but on the next window's move — no shared signs."""
    if "fwd_ret" not in df.columns:
        return {}
    g = df[["F", "fwd_ret", "sigma"]].dropna()
    g = g[(g["sigma"] > 0) & (g["F"].abs() > 1e-9)]
    if len(g) < 500:
        return {}
    x = np.sqrt(g["F"].abs().to_numpy())
    y = np.abs(g["fwd_ret"].to_numpy()) / (g["sigma"].to_numpy() * np.sqrt(21))
    ok = np.isfinite(x) & np.isfinite(y)
    x, y = x[ok], y[ok]
    keep = x <= np.quantile(x, 0.99)
    x, y = x[keep], y[keep]
    b = pd.DataFrame({"x": x, "y": y})
    b["q"] = pd.qcut(b["x"], 40, labels=False, duplicates="drop")
    binned = b.groupby("q").agg(x=("x", "mean"), y=("y", "mean"))
    slope, intercept, r, p, se = stats.linregress(binned["x"], binned["y"])
    return {"n": int(x.size), "slope_Y": float(slope), "intercept": float(intercept),
            "r2": float(r ** 2), "p": float(p), "se": float(se)}


def _fit_knee(x: np.ndarray, y: np.ndarray) -> dict:
    """Continuous two-segment fit; returns the best breakpoint."""
    best = None
    lo, hi = np.quantile(x, 0.15), np.quantile(x, 0.85)
    for bp in np.linspace(lo, hi, 60):
        hinge = np.clip(x - bp, 0, None)          # 0 below the knee, linear above
        X = np.column_stack([np.ones_like(x), x, hinge])
        try:
            beta, *_ = np.linalg.lstsq(X, y, rcond=None)
        except np.linalg.LinAlgError:
            continue
        sse = float(((y - X @ beta) ** 2).sum())
        if best is None or sse < best["sse"]:
            best = {"sse": sse, "breakpoint_sqrtF": float(bp),
                    "slope_below": float(beta[1]),
                    "slope_above": float(beta[1] + beta[2]),
                    "intercept": float(beta[0])}
    if best is None:
        return {}
    ss_tot = float(((y - y.mean()) ** 2).sum())
    best["r2"] = 1.0 - best["sse"] / ss_tot if ss_tot > 0 else 0.0
    # Back out of sqrt space: F is the flow-to-Q_break ratio.
    best["breakpoint_F"] = best["breakpoint_sqrtF"] ** 2
    linear = np.polyfit(x, y, 1)
    sse_lin = float(((y - np.polyval(linear, x)) ** 2).sum())
    best["improvement_over_straight_line"] = (
        float(1.0 - best["sse"] / sse_lin) if sse_lin > 0 else 0.0)
    return best


# --- T5: cap-band controls -------------------------------------------------
def check_cap_bands(band_models: dict[str, dict[str, FMResult]]) -> dict:
    """The effect should be strongest in mid-caps, per the mechanism."""
    rows = {}
    for band, models in band_models.items():
        m = models.get("M5_add_interaction")
        if not m:
            continue
        c = m.coefficients.get(KEY_TERM)
        if c:
            rows[band] = {"coef": c["coef"], "t": c["t"], "p": c["p"],
                          "n_periods": m.n_periods, "avg_names": m.mean_obs}
    if "mid_cap_target" not in rows:
        return {"available": False, "bands": rows}
    mid = abs(rows["mid_cap_target"]["t"])
    mega = abs(rows.get("mega_cap_control", {}).get("t", 0.0))
    return {"available": True, "bands": rows,
            "mid_stronger_than_mega": bool(mid > mega),
            "pass": bool(mid > mega)}


# ----------------------------------------------------------------------
def verdict(models: dict[str, FMResult], tests: dict, n_variants: int,
            alpha: float = 0.05) -> dict:
    """Six conditions. All must hold to justify Stage 2."""
    m5 = models.get("M5_add_interaction")
    key = m5.coefficients.get(KEY_TERM) if m5 else None
    # Bonferroni over the pre-registered variant count — the brief's own rule.
    adj_alpha = alpha / max(1, n_variants)

    checks = {
        "T0_inertia_is_measurable": {
            "detail": tests.get("T0", {}).get("rho_mean"),
            "pass": bool(tests.get("T0", {}).get("pass")),
        },
        "interaction_significant": {
            "detail": f"{KEY_TERM} p={key['p']:.4f} vs raw alpha {alpha}" if key else "missing",
            "pass": bool(key and key["p"] < alpha),
        },
        "interaction_survives_multiple_testing": {
            "detail": (f"p={key['p']:.4f} vs Bonferroni alpha {adj_alpha:.4f} "
                       f"({n_variants} pre-registered variants)") if key else "missing",
            "pass": bool(key and key["p"] < adj_alpha),
        },
        "adds_over_momentum": {
            "detail": "M5 mean R2 exceeds M2 (controls without flow terms)",
            "pass": bool(m5 and models.get("M2_momentum_controls")
                         and m5.r2_mean > models["M2_momentum_controls"].r2_mean),
        },
        "T1_momentum_increasing_in_rho": {
            "detail": tests.get("T1", {}).get("spearman_rho_vs_momentum"),
            "pass": bool(tests.get("T1", {}).get("pass")),
        },
        "T4_placebo_dies": {
            # Vacuous when the real signal is itself null: there is nothing for
            # the placebo to fail to reproduce. Reported as such rather than as
            # a pass (which would flatter) or a fail (which would mislead).
            "detail": tests.get("T4", {}).get("detail", ""),
            "pass": bool(tests.get("T4", {}).get("pass")),
            "vacuous": bool(tests.get("T4", {}).get("vacuous")),
        },
        "T5_not_strongest_in_mega_caps": {
            "detail": tests.get("T5", {}).get("bands", {}),
            "pass": bool(tests.get("T5", {}).get("pass")),
        },
    }
    passed = all(c["pass"] for c in checks.values())
    if not checks["T0_inertia_is_measurable"]["pass"]:
        # A failed precondition is not one failed check among six — it makes
        # every downstream result uninterpretable.
        passed = False
    return {
        "proceed_to_stage_2": passed,
        "checks": checks,
        "failed": [k for k, v in checks.items() if not v["pass"]],
        "bonferroni_alpha": adj_alpha,
        "n_variants": n_variants,
        "statement": (
            "Panel evidence supports the flow-inertia mechanism; Stage 2 "
            "(portfolio sorts) is justified."
            if passed else
            ("PRECONDITION FAILED: the flow proxy has no measurable persistence, so "
             "rho is noise and every downstream test is uninterpretable. The thesis "
             "is not refuted — it is untestable with this proxy. Move to Tier 2 "
             "(mechanical flow) or abandon."
             if not checks["T0_inertia_is_measurable"]["pass"] else
             "Panel evidence does not support proceeding. Per the spec's own decision "
             "rule, no portfolio construction should be attempted on this signal as "
             "specified.")),
    }
