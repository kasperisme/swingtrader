"""Step 1 — does re-anchoring rescue the mean reversion, or manufacture it?

The frozen design converged 29.0% against a 32.8% driftless random-walk
benchmark: BELOW a coin flip, t = -4.91 clustered over windows. Either the
anchor was stale (D2's finding: the spread's level moves and it is not
hedge-ratio error), or there is no daily-frequency mean reversion here to find.
Those two have completely different consequences and one cheap experiment
separates them.

**The gate is excess over a matched null, not the raw rate.** A rolling anchor
will report far more "convergence" than a frozen one no matter what the data
does, because subtracting a trailing mean makes anything oscillate around zero.
So each anchor is scored against random walks pushed through that same anchor
and the same screens. The registered decision is about the EXCESS.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from .anchor import AnchorSpec, quartile_table, synthetic_null

# --- the pre-registered variant list ---------------------------------------
ANCHORS = {
    "A0_frozen": AnchorSpec(mode="formation"),
    "A1_rolling_60": AnchorSpec(mode="rolling", window=60),
    "A2_rolling_60_rolling_beta": AnchorSpec(mode="rolling", window=60, rolling_beta=True),
    "A3_rolling_120": AnchorSpec(mode="rolling", window=120),
}
PRIMARY = "A1_rolling_60"

PREREGISTERED_TESTS = [
    "G0_null_reproduces_the_analytic_random_walk_rate",
    "G1_excess_convergence_over_matched_null",
    "G2_excess_is_positive_in_a_majority_of_windows",
    "G3_discriminator_survives_the_new_anchor",
]

DECISION_RULE = (
    "The anchor repair SUCCEEDS only if, for the primary anchor A1: (G1) realised "
    "convergence exceeds the matched synthetic null by a margin significant at the "
    "Bonferroni-adjusted one-sided level, clustered on the trading window; AND (G2) "
    "the excess is positive in more than half the windows. G0 is a validity check "
    "on the simulation, not a result. G3 is reported but cannot rescue a failed G1. "
    "If A1 fails, the conclusion registered IN ADVANCE is that daily-frequency mean "
    "reversion is absent in this universe and the reversion line is closed - not "
    "that a further anchor should be tried. A2/A3 are registered here precisely so "
    "that running them is not a post-hoc widening of the search."
)


@dataclass
class AnchorResult:
    protocol: dict = field(default_factory=dict)
    anchors: dict = field(default_factory=dict)
    verdict: dict = field(default_factory=dict)
    preregistration: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return dict(self.__dict__)


def preregister(out_dir: Path, protocol: dict, notes: str = "") -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "registered_at": datetime.now().isoformat(timespec="seconds"),
        "step": "FDP Step 1 - re-anchoring",
        "anchors": {k: v.label for k, v in ANCHORS.items()},
        "primary": PRIMARY,
        "tests": list(PREREGISTERED_TESTS),
        "n_variants": len(ANCHORS) * len(PREREGISTERED_TESTS),
        "decision_rule": DECISION_RULE,
        "prior_result_being_repaired": {
            "frozen_anchor_realised_convergence": 0.290,
            "analytic_random_walk_benchmark": 0.328,
            "gap_t_clustered_over_20_windows": -4.91,
        },
        "protocol": protocol,
        "notes": notes,
    }
    path = out_dir / "preregistration.json"
    if path.exists():
        try:
            prev = json.loads(path.read_text())
            if all(prev.get(k) == payload.get(k)
                   for k in ("anchors", "tests", "decision_rule", "primary")):
                payload["registered_at"] = prev.get("registered_at", payload["registered_at"])
                payload["last_run_at"] = datetime.now().isoformat(timespec="seconds")
        except Exception:
            pass
    path.write_text(json.dumps(payload, indent=2))
    return payload


# ----------------------------------------------------------------------
def analytic_rw_benchmark(df: pd.DataFrame) -> dict:
    """Driftless first passage, from each event's own realised z-volatility.

    Only meaningful for the frozen anchor, where z really is close to a random
    walk under the null. It is the independent check that `synthetic_null` is
    not itself broken: the two should agree there.
    """
    d = df.dropna(subset=["z_vol_post", "z_entry", "horizon_used"])
    d = d[d["z_vol_post"] > 0]
    if len(d) < 100:
        return {"available": False}
    p = 2 * stats.norm.cdf(-d["z_entry"].abs()
                           / (d["z_vol_post"] * np.sqrt(d["horizon_used"])))
    return {"available": True, "mean": float(np.minimum(p, 1.0).mean()), "n": int(len(d))}


def excess_over_null(df: pd.DataFrame, null_rate: float, value: str = "converged",
                     cluster: str = "window", boot: int = 4000, seed: int = 5) -> dict:
    """Realised minus the matched null, clustered on the trading window."""
    d = df.dropna(subset=[value])
    per = d.groupby(cluster)[value].mean().astype(float) - null_rate
    k = len(per)
    if k < 4:
        return {"available": False, "reason": f"only {k} clusters"}
    arr = per.to_numpy()
    mean = float(arr.mean())
    se = float(arr.std(ddof=1) / np.sqrt(k))
    t = mean / se if se > 0 else float("nan")
    rng = np.random.default_rng(seed)
    draws = arr[rng.integers(0, k, size=(boot, k))].mean(axis=1)
    return {
        "available": True,
        "realised": float(d[value].mean()),
        "null": float(null_rate),
        "excess": mean,
        "se": se, "t": float(t),
        "p_one_sided": float(stats.t.sf(t, df=k - 1)) if np.isfinite(t) else float("nan"),
        "boot_ci95": [float(np.quantile(draws, 0.025)), float(np.quantile(draws, 0.975))],
        "clusters": k,
        "windows_positive": int((arr > 0).sum()),
        "share_windows_positive": float((arr > 0).mean()),
        "n": int(len(d)),
    }


def run_anchor(df: pd.DataFrame, null: dict, alpha: float = 0.05,
               n_variants: int = 16) -> dict:
    """The registered battery for one anchor."""
    adj = alpha / n_variants
    out = {"alpha_bonferroni": adj, "null": null}
    if not null.get("available"):
        out["error"] = "no matched null"
        return out

    g1 = excess_over_null(df, null["convergence"], "converged")
    if g1.get("available"):
        g1["threshold"] = adj
        g1["pass"] = bool(g1["p_one_sided"] < adj and g1["excess"] > 0)
    out["G1_excess_convergence_over_matched_null"] = g1

    g1s = excess_over_null(df, null["convergence_soft"], "converged_soft")
    if g1s.get("available"):
        g1s["threshold"] = adj
        g1s["pass"] = bool(g1s["p_one_sided"] < adj and g1s["excess"] > 0)
    out["G1_soft_excess_over_matched_null"] = g1s

    out["G2_excess_is_positive_in_a_majority_of_windows"] = {
        "share_windows_positive": g1.get("share_windows_positive"),
        "windows_positive": g1.get("windows_positive"),
        "clusters": g1.get("clusters"),
        "pass": bool((g1.get("share_windows_positive") or 0) > 0.5),
    }

    # G3 - does the news discriminator still separate under this anchor?
    from .study import cluster_diff
    g3 = cluster_diff(df, "converged", "regime", "L", "N")
    if g3.get("available"):
        g3["p_used"] = g3["p_one_sided_hi_gt_lo"]
        g3["threshold"] = adj
        g3["pass"] = bool(g3["p_used"] < adj and g3["diff"] > 0)
    out["G3_discriminator_survives_the_new_anchor"] = g3

    # POST-HOC robustness check, not a registered test. It asks whether the
    # negative survives inside the most strongly cointegrated pairs — i.e.
    # whether a loophole rescues the result. It can only ever strengthen a null,
    # never create one, which is why running it after the fact is safe.
    if "adf_t" in df.columns:
        real_q = quartile_table(df["adf_t"].to_numpy(),
                                df["converged"].astype(float).to_numpy())
        null_q = null.get("by_adf_quartile") or {}
        rows = {}
        for k in real_q:
            if k in null_q:
                rows[k] = {"real": real_q[k]["convergence"],
                           "null": null_q[k]["convergence"],
                           "excess": real_q[k]["convergence"] - null_q[k]["convergence"],
                           "real_median_adf": real_q[k]["median_adf"],
                           "null_median_adf": null_q[k]["median_adf"],
                           "n": real_q[k]["n"]}
        out["POSTHOC_by_cointegration_strength"] = {
            "note": ("Not pre-registered. Checks whether the strongest pairs escape "
                     "the null. The gradient exists in the NULL too — selecting on "
                     "in-sample ADF selects paths that oscillated, and that persists "
                     "briefly even for random walks."),
            "quartiles": rows,
        }

    out["economics"] = {
        "events": int(len(df)),
        "events_per_window": round(len(df) / max(1, df["window"].nunique()), 1),
        "gross_return_per_event": float(df["gross_return"].mean()),
        "net_return_per_event": float(df["net_return"].mean()),
        "gross_clustered": float(df.groupby("window")["gross_return"].mean().mean()),
        "net_clustered": float(df.groupby("window")["net_return"].mean().mean()),
        "median_holding_days": float(df["holding_days"].median()),
    }
    return out


def verdict(anchors: dict) -> dict:
    """Apply the registered decision rule to the PRIMARY anchor only."""
    p = anchors.get(PRIMARY, {})
    g1 = bool(p.get("G1_excess_convergence_over_matched_null", {}).get("pass"))
    g2 = bool(p.get("G2_excess_is_positive_in_a_majority_of_windows", {}).get("pass"))
    passed = g1 and g2

    others = {k: bool(v.get("G1_excess_convergence_over_matched_null", {}).get("pass"))
              for k, v in anchors.items() if k != PRIMARY}
    return {
        "anchor_repair_succeeds": passed,
        "primary": PRIMARY,
        "conditions": {
            "G1 excess over matched null (Bonferroni)": g1,
            "G2 excess positive in a majority of windows": g2,
        },
        "secondary_anchors_passing_G1": others,
        "decision_rule": DECISION_RULE,
        "recommendation": (
            "Re-anchoring restores measurable mean reversion. Proceed to Step 2: "
            "generalise the hedge from one name to a factor basket, where the "
            "hedge costs net across the book."
            if passed else
            "Re-anchoring does NOT restore mean reversion beyond what the same "
            "anchor manufactures from random walks. Per the pre-registered rule, "
            "close the reversion line rather than trying a further anchor. The "
            "negative is now general - it holds for a frozen anchor against an "
            "analytic benchmark AND for rolling anchors against their own "
            "matched nulls."
        ),
    }
