"""H1 — the EGJ replication, pre-registered.

The hypothesis, in the spec's words: convergence probability and speed run
L-bucket > all-divergences > N-bucket. It is a POSITIVE CONTROL. If it fails,
the pair formation or the data is broken and the flow axis is not worth
building; if it passes, the machinery is known to be able to detect a real
discrimination effect, which is precisely what the flow Stage-1 could never
demonstrate about itself.

Inference is clustered on the trading window. Every event inside one window
shares a market regime and the pairs overlap heavily by construction (a name may
appear in up to three pairs), so pooled standard errors would be badly
overstated. The window-level statistic is the Fama-MacBeth analogue: compute the
L-minus-N difference inside each window, then test the ~20 window differences.
That costs a lot of nominal power and is the honest price of the design.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

# --- the pre-registered variant list ---------------------------------------
# Anything not on this list, run later and reported, is a post-hoc variant and
# inflates the effective trial count. The Bonferroni divisor is len(this).
PREREGISTERED_TESTS = [
    "P0_baseline_pairs_converge",           # sanity: the base rate exists at all
    "H1a_convergence_rate_L_gt_N",          # THE test
    "H1a_soft_convergence_rate_L_gt_N",     # ... on the "halved" outcome
    "H1b_net_return_L_gt_N",
    "H1c_rmst_L_faster_than_N",
    "H1d_break_rate_concentrates_in_N",
    "F1_placebo_labels_null",               # falsification
    "F2_stale_announcements_null",          # falsification (timing placebo)
    "F3_common_news_behaves_like_L",        # mechanism check
]

# Amended once, BEFORE the study was run on the full universe and AFTER a
# pipeline smoke test on a 500-name subset. Both changes fix defects visible
# without reference to any hypothesis test, and both were made in the direction
# that costs power (the Bonferroni divisor rose from 8 to 9):
#
#  * `converged_soft` (|z| back below 1.0) was added because zero-crossing is
#    the strictest possible convergence definition and its absence left the L/N
#    contrast measurable on one outcome only.
#  * H1c was changed from mean days-to-convergence AMONG CONVERGED EVENTS to
#    restricted mean survival time over all events. The original conditions on
#    the outcome: the slowest N divergences are the ones that never converge,
#    so they drop out of the average and bias the comparison toward the null.
#
# What the smoke test showed and what was NOT changed because of it: the
# unconditional 60-day convergence rate came in at 27.9%, below P0's registered
# 50% threshold. That threshold was left exactly as written. An OU-implied
# benchmark (D1) is reported ALONGSIDE it so the reader can see what the
# formation fits themselves predicted, but it is a diagnostic and has no vote.
AMENDMENT = {
    "amended_at": "before the full-universe run, after a 500-name pipeline smoke test",
    "added": ["H1a_soft_convergence_rate_L_gt_N",
              "D1_ou_implied_vs_realized (diagnostic, not a gate)"],
    "changed": ["H1c now uses restricted mean survival time instead of mean "
                "days-to-convergence among converged events"],
    "not_changed": ["P0's 50% convergence threshold, despite the smoke test "
                    "landing at 27.9%"],
}
KEY_TEST = "H1a_convergence_rate_L_gt_N"

DECISION_RULE = (
    "H1 is declared replicated only if ALL of: (P0) the unconditional "
    "convergence rate exceeds 50% and unconditional gross return is positive; "
    "(H1a) the L-minus-N convergence-rate difference is positive and "
    "significant at the Bonferroni-adjusted one-sided level; (F1) the placebo "
    "label split is insignificant at the NOMINAL level; and (F2) the stale-"
    "announcement split is insignificant at the NOMINAL level. H1b/H1c/H1d are "
    "corroborating and cannot rescue a failed H1a. A verdict is reported on DEV "
    "only; the 2024-2026 window is a single confirmation and is not permitted "
    "to change the verdict."
)


@dataclass
class StudyResult:
    protocol: dict = field(default_factory=dict)
    universe: dict = field(default_factory=dict)
    formation: dict = field(default_factory=dict)
    baseline: dict = field(default_factory=dict)
    tests: dict = field(default_factory=dict)
    exploratory: dict = field(default_factory=dict)
    verdict: dict = field(default_factory=dict)
    preregistration: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return dict(self.__dict__)


def preregister(out_dir: Path, protocol: dict, notes: str = "") -> dict:
    """Write the variant list and the decision rule BEFORE the data is touched.

    A pre-registration that is silently rewritten on every run is not one. If a
    registration already exists, its original timestamp is preserved when the
    substance is unchanged; when the substance HAS changed the old file is kept
    as `preregistration.superseded.<timestamp>.json` and the change is logged
    loudly, so an amendment leaves a trail instead of overwriting the evidence.
    """
    import logging as _logging
    _log = _logging.getLogger(__name__)
    out_dir.mkdir(parents=True, exist_ok=True)
    existing = None
    path = out_dir / "preregistration.json"
    if path.exists():
        try:
            existing = json.loads(path.read_text())
        except Exception:
            existing = None

    payload = {
        "registered_at": datetime.now().isoformat(timespec="seconds"),
        "tests": list(PREREGISTERED_TESTS),
        "key_test": KEY_TEST,
        "n_variants": len(PREREGISTERED_TESTS),
        "amendment": AMENDMENT,
        "decision_rule": DECISION_RULE,
        "protocol": protocol,
        "not_tested": [
            "H2 (flow axis) — needs 13F breadth differentials or index "
            "reconstitution dates; neither is wired up.",
            "H3 (inertia timing) — same dependency.",
            "H4 (ownership-overlap prior) — the ETF snapshot is CURRENT, not "
            "historical, so it is reported as an exploratory covariate only.",
        ],
        "notes": notes,
    }
    if existing is not None:
        substantive = ("tests", "key_test", "decision_rule", "amendment")
        changed = [k for k in substantive if existing.get(k) != payload.get(k)]
        if changed:
            stamp = payload["registered_at"].replace(":", "").replace("-", "")
            (out_dir / f"preregistration.superseded.{stamp}.json").write_text(
                json.dumps(existing, indent=2))
            _log.warning("PRE-REGISTRATION CHANGED (%s). The previous one has been kept "
                         "as preregistration.superseded.%s.json — any result reported "
                         "under the new list is an amended registration, not the "
                         "original.", ", ".join(changed), stamp)
            payload["supersedes"] = existing.get("registered_at")
        else:
            # Same substance: keep the ORIGINAL timestamp so a re-run does not
            # look like a fresh registration made after seeing the results.
            payload["registered_at"] = existing.get("registered_at", payload["registered_at"])
            payload["last_run_at"] = datetime.now().isoformat(timespec="seconds")
    path.write_text(json.dumps(payload, indent=2))
    return payload


# ----------------------------------------------------------------------
# Clustered inference.
# ----------------------------------------------------------------------
def cluster_diff(df: pd.DataFrame, value: str, group: str,
                 hi: str, lo: str, cluster: str = "window",
                 min_per_cell: int = 3, boot: int = 4000,
                 seed: int = 5) -> dict:
    """Mean(value | group==hi) - Mean(value | group==lo), clustered on `cluster`.

    Each cluster contributes ONE difference; the test is a one-sample t over
    clusters. Clusters missing either cell are dropped rather than imputed, and
    the number dropped is reported — a difference computed on eight of twenty
    windows is a different claim from one computed on all twenty.
    """
    sub = df[df[group].isin([hi, lo])]
    d = sub.dropna(subset=[value])
    rows, dropped = [], 0
    for c, g in d.groupby(cluster):
        a = g.loc[g[group] == hi, value]
        b = g.loc[g[group] == lo, value]
        if len(a) < min_per_cell or len(b) < min_per_cell:
            dropped += 1
            continue
        rows.append({"cluster": c, "hi": a.mean(), "lo": b.mean(),
                     "diff": a.mean() - b.mean(), "n_hi": len(a), "n_lo": len(b)})
    if len(rows) < 4:
        return {"available": False, "reason": f"only {len(rows)} usable clusters",
                "clusters_dropped": dropped}

    w = pd.DataFrame(rows)
    diffs = w["diff"].to_numpy()
    k = len(diffs)
    mean = float(diffs.mean())
    se = float(diffs.std(ddof=1) / np.sqrt(k))
    t = mean / se if se > 0 else float("nan")
    p_two = float(2 * stats.t.sf(abs(t), df=k - 1)) if np.isfinite(t) else float("nan")
    p_one = float(stats.t.sf(t, df=k - 1)) if np.isfinite(t) else float("nan")

    rng = np.random.default_rng(seed)
    draws = diffs[rng.integers(0, k, size=(boot, k))].mean(axis=1)
    ci = [float(np.quantile(draws, 0.025)), float(np.quantile(draws, 0.975))]

    return {
        "available": True,
        "value": value, "hi": hi, "lo": lo,
        "mean_hi": float(w["hi"].mean()), "mean_lo": float(w["lo"].mean()),
        "diff": mean, "se": se, "t": float(t),
        "p_two_sided": p_two, "p_one_sided_hi_gt_lo": p_one,
        "boot_ci95": ci,
        "clusters": k, "clusters_dropped": dropped,
        "n_hi": int(w["n_hi"].sum()), "n_lo": int(w["n_lo"].sum()),
        "pooled_hi": float(d.loc[d[group] == hi, value].mean()),
        "pooled_lo": float(d.loc[d[group] == lo, value].mean()),
    }


def cluster_mean(df: pd.DataFrame, value: str, cluster: str = "window",
                 boot: int = 4000, seed: int = 5) -> dict:
    """One-sample clustered mean — used for the unconditional baseline."""
    d = df.dropna(subset=[value])
    per = d.groupby(cluster)[value].mean().to_numpy()
    k = len(per)
    if k < 4:
        return {"available": False, "reason": f"only {k} clusters"}
    mean = float(per.mean())
    se = float(per.std(ddof=1) / np.sqrt(k))
    t = mean / se if se > 0 else float("nan")
    rng = np.random.default_rng(seed)
    draws = per[rng.integers(0, k, size=(boot, k))].mean(axis=1)
    return {"available": True, "value": value, "mean": mean, "se": se, "t": float(t),
            "p_two_sided": float(2 * stats.t.sf(abs(t), df=k - 1)),
            "boot_ci95": [float(np.quantile(draws, 0.025)), float(np.quantile(draws, 0.975))],
            "clusters": k, "n": int(len(d)), "pooled": float(d[value].mean())}


# ----------------------------------------------------------------------
# The battery.
# ----------------------------------------------------------------------
def run_tests(df: pd.DataFrame, alpha: float = 0.05) -> dict:
    """Every pre-registered test, at the Bonferroni-adjusted level."""
    n_var = len(PREREGISTERED_TESTS)
    adj = alpha / n_var
    out: dict = {"alpha_nominal": alpha, "n_variants": n_var, "alpha_bonferroni": adj}

    df = df.copy()
    for c in ("converged", "converged_soft", "converged_short"):
        if c in df.columns:
            df[c] = df[c].astype(float)

    # P0 — the base rate has to exist before conditioning on anything.
    conv = cluster_mean(df, "converged")
    gross = cluster_mean(df, "gross_return")
    net = cluster_mean(df, "net_return")
    out["P0_baseline_pairs_converge"] = {
        "convergence_rate": conv, "gross_return": gross, "net_return": net,
        "pass": bool(conv.get("available") and conv["mean"] > 0.5
                     and gross.get("available") and gross["mean"] > 0),
    }

    def _test(name, value, hi="L", lo="N", group="regime", one_sided=True, adjusted=True):
        r = cluster_diff(df, value, group, hi, lo)
        if r.get("available"):
            p = r["p_one_sided_hi_gt_lo"] if one_sided else r["p_two_sided"]
            r["p_used"] = p
            r["threshold"] = adj if adjusted else alpha
            r["pass"] = bool(p < r["threshold"] and r["diff"] > 0)
        out[name] = r
        return r

    _test("H1a_convergence_rate_L_gt_N", "converged")
    _test("H1a_soft_convergence_rate_L_gt_N", "converged_soft")
    _test("H1b_net_return_L_gt_N", "net_return")

    # H1c is stated as L < N, so the sign is flipped to keep every reported
    # `diff` "hi minus lo" and every `pass` mean the same thing.
    r = cluster_diff(df, "rmst_days", "regime", "N", "L")
    if r.get("available"):
        r["p_used"] = r["p_one_sided_hi_gt_lo"]
        r["threshold"] = adj
        r["pass"] = bool(r["p_used"] < adj and r["diff"] > 0)
        r["note"] = ("hi=N, lo=L on restricted mean survival time: a positive diff "
                     "means N takes LONGER, as predicted. Censored events enter at "
                     "the full horizon rather than dropping out.")
    out["H1c_rmst_L_faster_than_N"] = r

    df["broke"] = 1.0 - df["converged"]
    r = cluster_diff(df, "broke", "regime", "N", "L")
    if r.get("available"):
        r["p_used"] = r["p_one_sided_hi_gt_lo"]
        r["threshold"] = adj
        r["pass"] = bool(r["p_used"] < adj and r["diff"] > 0)
        r["note"] = "hi=N: breaks should concentrate in the information bucket."
    out["H1d_break_rate_concentrates_in_N"] = r

    # F1 / F2 — falsifications. These must FAIL to reject at the NOMINAL level;
    # holding them to the Bonferroni level would make them trivially easy to
    # pass, which is the wrong direction for a placebo.
    df["placebo_group"] = np.where(df["placebo_flag"], "N", "L")
    df["stale_group"] = np.where(df["stale_flag"], "N", "L")
    for name, group in (("F1_placebo_labels_null", "placebo_group"),
                        ("F2_stale_announcements_null", "stale_group")):
        r = cluster_diff(df, "converged", group, "L", "N")
        if r.get("available"):
            r["p_used"] = r["p_two_sided"]
            r["threshold"] = alpha
            r["pass"] = bool(r["p_used"] >= alpha)
            r["note"] = "PASS means no effect — a placebo that separates the buckets "
            r["note"] += "invalidates the real split."
        out[name] = r

    # F3 — the mechanism. EGJ's story is that IDIOSYNCRATIC news breaks a pair;
    # news hitting both legs is common information and should not.
    r = cluster_diff(df, "converged", "regime_detail", "N_both_legs", "N_one_leg")
    if r.get("available"):
        r["p_used"] = r["p_one_sided_hi_gt_lo"]
        r["threshold"] = alpha
        r["pass"] = bool(r["diff"] > 0)
        r["note"] = ("directional only: common news (both legs) should converge more "
                     "readily than one-legged news. Small-N; not a gate.")
    out["F3_common_news_behaves_like_L"] = r

    return out


def ou_implied_convergence(df: pd.DataFrame, horizon: int = 60,
                           paths: int = 4000, seed: int = 17) -> dict:
    """D1 — what the formation fits THEMSELVES predicted, versus what happened.

    P0's 50% threshold is a judgement call. This is not: each pair arrives with
    a formation-estimated half-life, which pins an Ornstein-Uhlenbeck process
    with kappa = ln2/h and (since the spread was standardised) unit stationary
    variance, hence instantaneous vol sqrt(2*kappa). Simulating that process
    forward from the event's own entry z gives the convergence rate the fit
    implied. The gap between implied and realised is the quantity of interest:
    it is a direct measure of how much of the estimated mean reversion survives
    the formation boundary.

    A diagnostic, deliberately not a gate — it uses no hypothesis and casts no
    vote in the verdict.
    """
    d = df.dropna(subset=["half_life", "z_entry"])
    if len(d) < 50:
        return {"available": False, "reason": "too few events"}

    rng = np.random.default_rng(seed)
    cache: dict[tuple, float] = {}

    def implied(h: float, z0: float) -> float:
        key = (round(float(h)), round(abs(float(z0)) * 4) / 4)
        if key in cache:
            return cache[key]
        hh, zz = max(1.0, float(key[0])), max(0.1, float(key[1]))
        kappa = np.log(2.0) / hh
        sigma = np.sqrt(2.0 * kappa)
        z = np.full(paths, zz)
        alive = np.ones(paths, dtype=bool)
        hit = np.zeros(paths, dtype=bool)
        for _ in range(horizon):
            z = z - kappa * z + sigma * rng.standard_normal(paths)
            newly = alive & (z <= 0.0)
            hit |= newly
            alive &= ~newly
        cache[key] = float(hit.mean())
        return cache[key]

    imp = np.array([implied(h, z) for h, z in zip(d["half_life"], d["z_entry"])])
    realised = float(d["converged"].astype(float).mean())
    per_window = (d.assign(_imp=imp)
                   .groupby("window")
                   .apply(lambda g: g["converged"].astype(float).mean() - g["_imp"].mean(),
                          include_groups=False))
    gap = per_window.to_numpy(dtype=float)
    k = len(gap)
    t = float(gap.mean() / (gap.std(ddof=1) / np.sqrt(k))) if k > 3 and gap.std(ddof=1) > 0 else float("nan")

    by_regime = {}
    for r, g in d.assign(_imp=imp).groupby("regime"):
        by_regime[str(r)] = {
            "implied": float(g["_imp"].mean()),
            "realised": float(g["converged"].astype(float).mean()),
            "gap": float(g["converged"].astype(float).mean() - g["_imp"].mean()),
            "n": int(len(g)),
        }

    return {
        "available": True,
        "ou_implied_convergence": float(imp.mean()),
        "realised_convergence": realised,
        "gap": realised - float(imp.mean()),
        "gap_t_over_windows": t,
        "by_regime": by_regime,
        "interpretation": (
            "A large negative gap means the mean reversion measured during "
            "formation did not survive into the trading window — the pairs are "
            "selected on an OU fit that decays at the boundary. It bounds how "
            "much of the low convergence rate is a property of the market rather "
            "than of the event definition."
        ),
    }


def drift_attribution(panel, pairs) -> dict:
    """D2 — WHY the spreads drift, decomposed rather than asserted.

    If the cointegrating relationship is real and only the hedge ratio is
    mismeasured, the algebra is exact. Write the formation fit as
    x_A = alpha + beta*x_B + s and the truth as x_A = alpha* + beta**x_B + s*
    with s* stationary. The trading-window level shift of the traded spread is

        E_T[s] - E_F[s]  =  (beta* - beta) * (E_T[x_B] - E_F[x_B])

    i.e. **hedge-ratio error times how far leg B travelled between the two
    windows**. Nothing else survives. That gives a falsifiable prediction: the
    SIZE of the drift should scale with the size of leg B's move, with a slope
    that estimates the average |hedge-ratio error|.

    If instead the drift is unrelated to leg B's move, the relationship itself
    broke and no amount of better estimation would have helped. The two have
    very different implications, so the study measures which it is.
    """
    from .events import _spread_z
    rows = []
    for p in pairs:
        try:
            f0 = panel.date_index(p.formation_start)
            f1 = panel.date_index(p.formation_end) + 1
            t0 = panel.date_index(p.trade_start)
            t1 = panel.date_index(p.trade_end) + 1
        except Exception:
            continue
        z = _spread_z(p, panel.close)
        zt = z[t0:t1]
        zt = zt[np.isfinite(zt)]
        if zt.size < 20:
            continue
        xb = np.log(panel.close[:, p.ib])
        bf, bt = xb[f0:f1], xb[t0:t1]
        bf, bt = bf[np.isfinite(bf)], bt[np.isfinite(bt)]
        if bf.size < 20 or bt.size < 20:
            continue
        rows.append({"drift": float(zt.mean()),
                     "leg_b_move": float(bt.mean() - bf.mean()) / max(p.sigma, 1e-9)})
    if len(rows) < 100:
        return {"available": False, "reason": f"only {len(rows)} pairs"}

    d = pd.DataFrame(rows)
    x = d["leg_b_move"].abs().to_numpy()
    y = d["drift"].abs().to_numpy()
    slope = float((x * y).sum() / max((x * x).sum(), 1e-12))       # through the origin
    resid = y - slope * x
    # Uncentred R^2, which is the right one for a through-origin fit; the
    # centred version can go negative here purely because the slope is set by
    # high-leverage points, and would read as a result rather than an artefact.
    uncentred_r2 = float(1.0 - (resid ** 2).sum() / max((y ** 2).sum(), 1e-12))
    corr = float(np.corrcoef(x, y)[0, 1])
    r, p_corr = stats.pearsonr(x, y)
    return {
        "available": True,
        "pairs": int(len(d)),
        "mean_abs_drift_z": float(y.mean()),
        "mean_abs_leg_b_move_z": float(x.mean()),
        "implied_mean_abs_hedge_ratio_error": slope,
        "corr_drift_vs_leg_b_move": corr,
        "corr_p_value": float(p_corr),
        "uncentred_r2_through_origin": uncentred_r2,
        "verdict": ("hedge-ratio error" if corr > 0.3 else
                    "relationship breakdown" if corr < 0.15 else "mixed"),
        "interpretation": (
            "The exact algebra says the drift must equal (hedge-ratio error) x "
            "(leg B's travel between windows) IF the cointegrating relationship "
            "still holds. A near-zero correlation therefore rules that mechanism "
            "out: the relationship itself broke between formation and trading, "
            "and no better estimator would have recovered it."
        ),
    }


def exploratory(df: pd.DataFrame) -> dict:
    """Everything NOT pre-registered, fenced off and labelled as such."""
    out: dict = {}

    # The EGJ time-decay ("puke rule") — profits should fall with time since
    # divergence. Measured on the events themselves: converged trades that took
    # longer should have earned less per day.
    d = df[df["converged"].astype(bool)].copy()
    if len(d) > 50:
        bins = pd.cut(d["days_to_converge"], [0, 5, 10, 20, 40, 61])
        out["net_return_by_days_to_converge"] = {
            str(k): {"mean_net": float(v["net_return"].mean()), "n": int(len(v))}
            for k, v in d.groupby(bins, observed=True)}

    # H4's buildable half: does the linkage prior sort anything at all?
    d = df.dropna(subset=["etf_overlap"])
    if len(d) > 200:
        q = pd.qcut(d["etf_overlap"], 4, labels=["Q1_low", "Q2", "Q3", "Q4_high"],
                    duplicates="drop")
        out["by_etf_ownership_overlap"] = {
            str(k): {"convergence": float(v["converged"].mean()),
                     "net_return": float(v["net_return"].mean()),
                     "news_rate": float((v["regime"] == "N").mean()),
                     "n": int(len(v))}
            for k, v in d.groupby(q, observed=True)}
        out["_etf_overlap_caveat"] = (
            "The ETF exposure snapshot is CURRENT, not historical — this sort "
            "carries look-ahead and is reported for direction only.")

    # Half-life is a formation-period estimate, so sorting on it is legitimate.
    if len(df) > 200:
        q = pd.qcut(df["half_life"], 3, labels=["fast", "mid", "slow"], duplicates="drop")
        out["by_formation_half_life"] = {
            str(k): {"convergence": float(v["converged"].mean()),
                     "net_return": float(v["net_return"].mean()), "n": int(len(v))}
            for k, v in df.groupby(q, observed=True)}

    # The spec promises that even a null on flow leaves "a working L-bucket
    # pairs book" behind. That is a claim about the L bucket ALONE, not about
    # the L-minus-N difference, so it needs its own one-sample test.
    for label, sub in (("L", df[df["regime"] == "L"]), ("N", df[df["regime"] == "N"])):
        if len(sub) > 100:
            out[f"standalone_book_{label}"] = {
                "net_return_per_event": cluster_mean(sub, "net_return"),
                "gross_return_per_event": cluster_mean(sub, "gross_return"),
                "convergence_rate": cluster_mean(sub, "converged"),
                "events": int(len(sub)),
                "events_per_year": round(len(sub) / max(1, sub["window"].nunique() / 2.0), 1),
            }

    # Widening before reversal, by bucket — the spread-space shape H3 predicts
    # for flow-driven divergences. With no flow measure this cannot test H3; it
    # records the quantity so the flow version has a baseline to beat.
    out["widening_by_regime"] = {
        str(k): {"mean_widening_z": float(v["widening"].mean()),
                 "mean_max_adverse_z": float(v["max_adverse_z"].mean()), "n": int(len(v))}
        for k, v in df.groupby("regime", observed=True)}
    return out


def verdict(tests: dict, baseline_ok: bool | None = None) -> dict:
    """Apply the pre-registered decision rule. Deliberately hard to pass."""
    def ok(name):
        return bool(tests.get(name, {}).get("pass"))

    conditions = {
        "P0 base rate exists": ok("P0_baseline_pairs_converge"),
        "H1a L converges more than N (Bonferroni)": ok("H1a_convergence_rate_L_gt_N"),
        "F1 placebo labels do NOT separate": ok("F1_placebo_labels_null"),
        "F2 stale announcements do NOT separate": ok("F2_stale_announcements_null"),
    }
    corroborating = {
        "H1a_soft L reverts halfway more often": ok("H1a_soft_convergence_rate_L_gt_N"),
        "H1b net return higher in L": ok("H1b_net_return_L_gt_N"),
        "H1c L converges faster (RMST)": ok("H1c_rmst_L_faster_than_N"),
        "H1d breaks concentrate in N": ok("H1d_break_rate_concentrates_in_N"),
        "F3 common news behaves like L": ok("F3_common_news_behaves_like_L"),
    }
    passed = all(conditions.values())
    return {
        "h1_replicated": passed,
        "conditions": conditions,
        "corroborating": corroborating,
        "n_corroborating_passed": int(sum(corroborating.values())),
        "n_corroborating": len(corroborating),
        "decision_rule": DECISION_RULE,
        "recommendation": (
            "Proceed to the flow axis (H2/H3): build the reconstitution + 13F "
            "breadth differential event set."
            if passed else
            "Do NOT build the flow axis on this panel. The news discriminator is "
            "the positive control; without it, a null on flow would be "
            "uninterpretable and a positive would not be believable."
        ),
    }
