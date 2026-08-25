"""NRP Stage 1 — does the repricing that broke the pairs book pay directionally?

The pairs study established that announcements move a spread to a new level and
keep it there. Read the other way that is post-earnings-announcement drift, and
this asks whether it is (a) present on this panel, (b) larger than the same
measurement produces on days when nothing was announced, and (c) larger than
the frictions a retail account actually pays.

(b) is the part most PEAD work skips. Drift after a large abnormal move is not
by itself evidence of an announcement effect — momentum and volatility
clustering produce some of it unconditionally. The pseudo-event control runs
the identical pipeline on non-announcement days, and the registered quantity is
the EXCESS. It is the same discipline the anchor study used to catch a rolling
filter manufacturing 81% convergence out of random walks.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

PREREGISTERED_TESTS = [
    "P1_drift_is_monotone_in_the_surprise",     # positive control
    "P2_top_minus_bottom_spread_is_positive",   # THE test
    "N1_excess_over_the_pseudo_event_control",  # the falsification
    "N2_placebo_surprise_labels_are_null",
    "E1_spread_survives_costs",
    "E2_long_only_leg_survives_costs",          # the retail-accessible half
]
KEY_TEST = "N1_excess_over_the_pseudo_event_control"

DECISION_RULE = (
    "The effect is declared REAL and TRADEABLE only if ALL of: (P1) mean drift "
    "is monotone in the surprise decile by a rank correlation of at least 0.7; "
    "(P2) the top-minus-bottom spread is positive and significant at the "
    "Bonferroni-adjusted one-sided level, clustered on calendar month; (N1) that "
    "spread EXCEEDS the identical spread measured on pseudo-events by a "
    "significant margin; and (E1) it remains positive after a round trip on both "
    "legs. E2 is reported separately because shorting the bottom decile is often "
    "not available to a retail account, so a strategy that needs it is not the "
    "same strategy. Significance without N1 is momentum, not an announcement "
    "effect. Tests are run on DEV (2014-2023); the vault and the pre-2014 era "
    "are reported once each and cannot change the verdict."
)


@dataclass
class NRPResult:
    protocol: dict = field(default_factory=dict)
    universe: dict = field(default_factory=dict)
    tests: dict = field(default_factory=dict)
    tiers: dict = field(default_factory=dict)
    eras: dict = field(default_factory=dict)
    exploratory: dict = field(default_factory=dict)
    verdict: dict = field(default_factory=dict)
    preregistration: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return dict(self.__dict__)


def preregister(out_dir: Path, protocol: dict, notes: str = "") -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "registered_at": datetime.now().isoformat(timespec="seconds"),
        "study": "NRP Stage 1 - news repricing / post-announcement drift",
        "tests": list(PREREGISTERED_TESTS),
        "key_test": KEY_TEST,
        "n_variants": len(PREREGISTERED_TESTS) * len(protocol.get("horizons", [1])),
        "decision_rule": DECISION_RULE,
        "origin": (
            "Follows directly from the FDP result: announcements were shown to "
            "prevent spread convergence, i.e. to reprice one leg permanently. "
            "This tests whether that repricing is tradeable directionally."
        ),
        "protocol": protocol,
        "notes": notes,
    }
    path = out_dir / "preregistration.json"
    if path.exists():
        try:
            prev = json.loads(path.read_text())
            if all(prev.get(k) == payload.get(k)
                   for k in ("tests", "key_test", "decision_rule")):
                payload["registered_at"] = prev.get("registered_at",
                                                    payload["registered_at"])
                payload["last_run_at"] = datetime.now().isoformat(timespec="seconds")
        except Exception:
            pass
    path.write_text(json.dumps(payload, indent=2))
    return payload


# ----------------------------------------------------------------------
def _cluster(series_by_month: np.ndarray, boot: int = 4000, seed: int = 5) -> dict:
    k = len(series_by_month)
    if k < 6:
        return {"available": False, "reason": f"only {k} months"}
    mean = float(series_by_month.mean())
    se = float(series_by_month.std(ddof=1) / np.sqrt(k))
    t = mean / se if se > 0 else float("nan")
    rng = np.random.default_rng(seed)
    draws = series_by_month[rng.integers(0, k, size=(boot, k))].mean(axis=1)
    return {"available": True, "mean": mean, "se": se, "t": float(t),
            "p_one_sided": float(stats.t.sf(t, df=k - 1)) if np.isfinite(t) else float("nan"),
            "p_two_sided": float(2 * stats.t.sf(abs(t), df=k - 1)) if np.isfinite(t) else float("nan"),
            "boot_ci95": [float(np.quantile(draws, 0.025)), float(np.quantile(draws, 0.975))],
            "months": k,
            "share_months_positive": float((series_by_month > 0).mean())}


def _monthly(df: pd.DataFrame, value: str) -> pd.Series:
    d = df.dropna(subset=[value]).copy()
    d["_m"] = pd.PeriodIndex(pd.to_datetime(d["date"]), freq="M")
    return d.groupby("_m")[value].mean()


MIN_PER_CELL = 5
"""Minimum announcements in EACH extreme decile for a month to count.

Not a tuning knob. Earnings cluster into four seasons, so off-season months can
carry one or two announcements in a decile, and a "decile mean" from a single
observation is not a mean. Left unguarded these months produced spreads of
±17% and flipped the sign of the whole statistic: the pooled spread was +0.49%
while the month-equal-weighted spread was -0.30%, decided by three months
holding one or two events apiece. The pairs study's `cluster_diff` already
drops thin cells for the same reason; this is the same rule.
"""


def spread_series(df: pd.DataFrame, value: str, n_buckets: int = 10,
                  min_per_cell: int = MIN_PER_CELL, freq: str = "M"):
    """Top-decile-minus-bottom-decile mean per period.

    Periods missing either leg, or too thin on either leg, are dropped rather
    than filled — a spread computed from one leg, or from one observation, is
    not a spread. Returns the series; `spread_series_detail` also reports how
    many periods were dropped, which is part of the claim.
    """
    ser, _ = spread_series_detail(df, value, n_buckets, min_per_cell, freq)
    return ser


def spread_series_detail(df: pd.DataFrame, value: str, n_buckets: int = 10,
                         min_per_cell: int = MIN_PER_CELL, freq: str = "M"):
    d = df.dropna(subset=[value, "bucket"]).copy()
    if d.empty:
        return pd.Series(dtype=float), {"periods": 0, "dropped": 0}
    d["_m"] = pd.PeriodIndex(pd.to_datetime(d["date"]), freq=freq)
    hi = d[d["bucket"] == n_buckets - 1].groupby("_m")[value].agg(["mean", "size"])
    lo = d[d["bucket"] == 0].groupby("_m")[value].agg(["mean", "size"])
    both = hi.index.intersection(lo.index)
    hi, lo = hi.loc[both], lo.loc[both]
    ok = (hi["size"] >= min_per_cell) & (lo["size"] >= min_per_cell)
    ser = (hi["mean"] - lo["mean"])[ok].sort_index()
    info = {"periods": int(ok.sum()), "dropped": int((~ok).sum()),
            "min_per_cell": min_per_cell,
            "pooled": float(d[d["bucket"] == n_buckets - 1][value].mean()
                            - d[d["bucket"] == 0][value].mean())}
    return ser, info


def bucket_table(df: pd.DataFrame, value: str, n_buckets: int = 10) -> dict:
    d = df.dropna(subset=[value, "bucket"])
    g = d.groupby("bucket")[value].agg(["mean", "count"])
    return {int(k): {"mean": float(v["mean"]), "n": int(v["count"])}
            for k, v in g.iterrows()}


def monotonicity(table: dict) -> dict:
    ks = sorted(table)
    if len(ks) < 5:
        return {"available": False}
    means = [table[k]["mean"] for k in ks]
    rho, p = stats.spearmanr(ks, means)
    return {"available": True, "spearman": float(rho), "p": float(p),
            "buckets": len(ks)}


def costed(spread: pd.Series, spec, legs: int = 2) -> pd.Series:
    """Charge a round trip per leg on the traded notional."""
    return spread - legs * 2.0 * spec.cost_bps_per_side * 1e-4


def run_tests(real: pd.DataFrame, pseudo: pd.DataFrame, spec,
              horizon: int, alpha: float = 0.05, n_variants: int = 6) -> dict:
    adj = alpha / n_variants
    ret, car = f"ret_{horizon}", f"car_{horizon}"
    out = {"horizon": horizon, "alpha_bonferroni": adj}

    tbl = bucket_table(real, car, spec.n_buckets)
    out["bucket_means_car"] = tbl
    out["bucket_means_ret"] = bucket_table(real, ret, spec.n_buckets)
    mono = monotonicity(tbl)
    mono["pass"] = bool(mono.get("available") and mono["spearman"] >= 0.7)
    out["P1_drift_is_monotone_in_the_surprise"] = mono

    sp, info = spread_series_detail(real, ret, spec.n_buckets)
    r = _cluster(sp.to_numpy())
    if r.get("available"):
        r["threshold"] = adj
        r["pass"] = bool(r["p_one_sided"] < adj and r["mean"] > 0)
        r["events"] = int(real.dropna(subset=[ret, "bucket"]).shape[0])
        r.update({"months_dropped_as_thin": info["dropped"], "pooled": info["pooled"]})
        # Sensitivity to the thin-cell rule, reported rather than chosen.
        r["sensitivity_min_per_cell"] = {
            str(k): float(spread_series(real, ret, spec.n_buckets, min_per_cell=k).mean())
            for k in (1, 3, 5, 10)}
        r["quarterly_cluster"] = float(
            spread_series(real, ret, spec.n_buckets, freq="Q").mean())
    out["P2_top_minus_bottom_spread_is_positive"] = r

    sp_p = spread_series(pseudo, ret, spec.n_buckets)
    rp = _cluster(sp_p.to_numpy())
    out["pseudo_spread"] = rp
    both = sp.index.intersection(sp_p.index)
    if len(both) >= 6:
        ex = _cluster((sp.loc[both] - sp_p.loc[both]).to_numpy())
        ex["threshold"] = adj
        ex["pass"] = bool(ex.get("available") and ex["p_one_sided"] < adj
                          and ex["mean"] > 0)
        ex["note"] = ("Real minus pseudo, month by month. This is the number that "
                      "distinguishes an announcement effect from momentum.")
    else:
        ex = {"available": False, "reason": "too few overlapping months"}
    out["N1_excess_over_the_pseudo_event_control"] = ex

    # N2 - shuffle the surprise labels within each month. Destroys the sort,
    # keeps the return distribution, the calendar and the bucket sizes.
    rng = np.random.default_rng(97)
    d = real.dropna(subset=[ret, "bucket"]).copy()
    d["_m"] = pd.PeriodIndex(pd.to_datetime(d["date"]), freq="M")
    d["bucket"] = d.groupby("_m")["bucket"].transform(
        lambda x: rng.permutation(x.to_numpy()))
    r2 = _cluster(spread_series(d, ret, spec.n_buckets).to_numpy())
    if r2.get("available"):
        r2["threshold"] = alpha
        r2["pass"] = bool(r2["p_two_sided"] >= alpha)
        r2["note"] = "PASS means no effect — a shuffled sort must not pay."
    out["N2_placebo_surprise_labels_are_null"] = r2

    net = costed(sp, spec, legs=2)
    r3 = _cluster(net.to_numpy())
    if r3.get("available"):
        r3["threshold"] = adj
        r3["pass"] = bool(r3["p_one_sided"] < adj and r3["mean"] > 0)
        r3["round_trip_bps"] = 4 * spec.cost_bps_per_side
    out["E1_spread_survives_costs"] = r3

    hi = real[(real["bucket"] == spec.n_buckets - 1)]
    lo_leg = _monthly(hi, ret)
    r4 = _cluster(costed(lo_leg, spec, legs=1).to_numpy())
    if r4.get("available"):
        r4["threshold"] = adj
        r4["pass"] = bool(r4["p_one_sided"] < adj and r4["mean"] > 0)
        r4["note"] = ("Top decile alone, market-hedged, one round trip. The half a "
                      "retail account can actually hold.")
    out["E2_long_only_leg_survives_costs"] = r4
    return out


def by_tier(real: pd.DataFrame, pseudo: pd.DataFrame, spec, horizon: int) -> dict:
    """The question the whole study exists to answer: where does the edge live
    relative to the friction?"""
    ret = f"ret_{horizon}"
    out = {}
    for tier, g in real.groupby("tier"):
        gp = pseudo[pseudo["tier"] == tier]
        sp = spread_series(g, ret, spec.n_buckets)
        r = _cluster(sp.to_numpy())
        if not r.get("available"):
            continue
        entry = {"events": int(len(g)), "gross": r["mean"], "t": r["t"],
                 "months": r["months"]}
        entry["net"] = r["mean"] - 4 * spec.cost_bps_per_side * 1e-4
        entry["cost_share_of_gross"] = (
            float(4 * spec.cost_bps_per_side * 1e-4 / r["mean"]) if r["mean"] > 0 else None)
        sp_p = spread_series(gp, ret, spec.n_buckets)
        both = sp.index.intersection(sp_p.index)
        if len(both) >= 6:
            ex = _cluster((sp.loc[both] - sp_p.loc[both]).to_numpy())
            entry["pseudo"] = float(sp_p.loc[both].mean())
            entry["excess_over_pseudo"] = ex.get("mean")
            entry["excess_t"] = ex.get("t")
        out[str(tier)] = entry
    return out


def posthoc_reversal_asymmetry(real: pd.DataFrame, pseudo: pd.DataFrame, spec,
                               horizon: int, tiers: tuple = ()) -> dict:
    """POST-HOC. Generated by looking at the control, so labelled accordingly.

    The pseudo-event deciles came out strongly DOWNWARD sloping in the liquid
    tiers: a large abnormal move with no announcement near it reverts. The real
    announcements do not. That is the FDP taxonomy - transient liquidity shocks
    decay, information repricings do not - showing up in single-name directional
    returns, on a construction that shares no code path with the pairs study.

    This was not pre-registered. It was found in a control, which is exactly the
    situation that produces false discoveries, so it is reported as a hypothesis
    with numbers attached and NOT as a result. The vault figure below is a second
    use of the vault and is recorded as such.
    """
    ret = f"ret_{horizon}"
    cost = 4.0 * spec.cost_bps_per_side * 1e-4
    out: dict = {
        "status": "POST-HOC — generated from the control, not pre-registered",
        "hypothesis": ("Fade an extreme abnormal move when NO announcement is "
                       "near it; do not fade it when one is. The edge is the "
                       "difference, not either leg."),
        "cost_charged_bps": cost * 1e4,
        "tiers": {},
    }
    for tier in (tiers or sorted(real["tier"].dropna().unique())):
        R = real[real["tier"] == tier]
        F = pseudo[pseudo["tier"] == tier]
        sr = spread_series(R, ret, spec.n_buckets)
        sf = spread_series(F, ret, spec.n_buckets)
        both = sr.index.intersection(sf.index)
        if len(both) < 8:
            continue
        no_news = _cluster((-sf.loc[both]).to_numpy())
        news = _cluster((-sr.loc[both]).to_numpy())
        diff = _cluster((-sf.loc[both] + sr.loc[both]).to_numpy())
        net = _cluster((-sf.loc[both] - cost).to_numpy())
        out["tiers"][str(tier)] = {
            "fade_no_news_gross": no_news["mean"], "t": no_news["t"],
            "fade_news_gross": news["mean"], "news_t": news["t"],
            "asymmetry": diff["mean"], "asymmetry_t": diff["t"],
            "fade_no_news_net": net["mean"], "net_t": net["t"],
            "share_months_positive": net["share_months_positive"],
            "months": int(len(both)),
        }
    return out


def verdict(tests: dict) -> dict:
    def ok(n):
        return bool(tests.get(n, {}).get("pass"))
    conditions = {
        "P1 drift monotone in the surprise": ok("P1_drift_is_monotone_in_the_surprise"),
        "P2 top-minus-bottom spread positive (Bonferroni)":
            ok("P2_top_minus_bottom_spread_is_positive"),
        "N1 excess over the pseudo-event control": ok("N1_excess_over_the_pseudo_event_control"),
        "N2 shuffled labels do NOT pay": ok("N2_placebo_surprise_labels_are_null"),
        "E1 survives costs": ok("E1_spread_survives_costs"),
    }
    passed = all(conditions.values())
    return {
        "effect_is_real_and_tradeable": passed,
        "conditions": conditions,
        "long_only_leg_survives": ok("E2_long_only_leg_survives_costs"),
        "decision_rule": DECISION_RULE,
        "recommendation": (
            "The repricing is real, exceeds its non-announcement control, and "
            "survives modelled frictions. Proceed to portfolio construction: "
            "capacity by liquidity tier, borrow feasibility on the short leg, "
            "and overlap with the existing momentum book."
            if passed else
            "Do not trade this as specified. Read the tier table before "
            "concluding anything general - a null at the liquid end is not a "
            "null everywhere, and the cost share of gross says which end could "
            "ever have worked."
        ),
    }
