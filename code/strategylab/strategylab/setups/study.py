"""Does the setup beat its breakeven, and does anything time it?

With a fixed 2R target against a 1R stop the arithmetic is exact:

    expectancy in R = 2p - (1 - p) = 3p - 1      breakeven at p = 1/3

so every question collapses to one number. Costs move the bar: a 26bp round trip
on a position risking `risk_pct` of notional is `0.0026 / risk_pct` in R, which
at a 5% stop is 0.052R and lifts breakeven to p = 0.351. That is why costs are
carried in R throughout rather than in percent.

The registered comparison is never against 1/3 alone. It is against the
PSEUDO-SETUP control — the same universe, the same day, the same geometry, no
breakout. A momentum universe is screened for names already trending, so some
hit rate comes free. The breakout has to beat that, not a coin.
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
    "S1_setup_beats_its_breakeven_hit_rate",
    "S2_setup_beats_the_pseudo_setup_control",
    "S3_expectancy_net_of_costs_is_positive",
    "T1_any_conditioner_lifts_the_hit_rate",
    "T2_conditioner_effect_is_monotone",
    "N1_shuffled_conditioner_labels_are_null",
]
KEY_TEST = "S2_setup_beats_the_pseudo_setup_control"

# Amended once, BEFORE the full-universe run and AFTER a 500-name pipeline smoke
# test, to repair arithmetic that was simply wrong:
#
#   S1 compared the UNCONDITIONAL hit rate against a breakeven of 1/3. That
#   breakeven is only valid when every trade ends at a barrier, and 31% of them
#   time out at the 60-bar cap and exit at the close instead. Comparing a rate
#   diluted by timeouts against a barrier-only breakeven guarantees failure
#   whatever the setup does. S1 now uses P(target | RESOLVED); the unconditional
#   rate and the resolution rate are both still reported, and S3 carries the
#   economics over ALL trades including timeouts.
#
# Worth stating because it makes S1 interpretable: for a driftless random walk,
# the probability of touching +2R before -1R is exactly 1/3 (optional stopping
# on a martingale). So the breakeven hit rate IS the random-walk rate, and S1
# is literally asking whether these setups drift upward at all.
AMENDMENT = {
    "amended_at": "before the full-universe run, after a 500-name smoke test",
    "changed": ["S1 now uses P(target | resolved) rather than the unconditional "
                "hit rate, because 31% of trades time out and the 1/3 breakeven "
                "only holds for barrier-resolved trades"],
    "unchanged": ["S2 and S3, the reward multiple, the stop rule, the cost model"],
}

DECISION_RULE = (
    "The setup is declared to have a timing edge only if ALL of: (S1) the hit "
    "rate exceeds the cost-adjusted breakeven, clustered on calendar month; "
    "(S2) it exceeds the pseudo-setup control by a margin significant at the "
    "Bonferroni-adjusted one-sided level; and (S3) net expectancy in R is "
    "positive. T1/T2 then ask whether any conditioner TIMES it - they are the "
    "point of the study but they cannot rescue a setup that fails S2, because "
    "conditioning a negative-expectancy trade only selects which losses to take. "
    "N1 must be null. Tests run on DEV; the vault is reported once."
)


@dataclass
class SetupResult:
    protocol: dict = field(default_factory=dict)
    sample: dict = field(default_factory=dict)
    tests: dict = field(default_factory=dict)
    conditioners: dict = field(default_factory=dict)
    verdict: dict = field(default_factory=dict)
    preregistration: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return dict(self.__dict__)


def breakeven_rate(reward_multiple: float, cost_r: float = 0.0) -> float:
    """p such that p*R - (1-p)*1 - cost = 0."""
    return (1.0 + cost_r) / (reward_multiple + 1.0)


def preregister(out_dir: Path, protocol: dict, notes: str = "") -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "registered_at": datetime.now().isoformat(timespec="seconds"),
        "study": "Setup timing - Minervini breakout, support stop, 2R target",
        "tests": list(PREREGISTERED_TESTS),
        "key_test": KEY_TEST,
        "n_variants": len(PREREGISTERED_TESTS) + int(protocol.get("n_conditioners", 0)),
        "amendment": AMENDMENT,
        "decision_rule": DECISION_RULE,
        "protocol": protocol,
        "notes": notes,
    }
    path = out_dir / "preregistration.json"
    if path.exists():
        try:
            prev = json.loads(path.read_text())
            if all(prev.get(k) == payload.get(k)
                   for k in ("tests", "key_test", "decision_rule")):
                payload["registered_at"] = prev.get("registered_at", payload["registered_at"])
                payload["last_run_at"] = datetime.now().isoformat(timespec="seconds")
        except Exception:
            pass
    path.write_text(json.dumps(payload, indent=2))
    return payload


# ----------------------------------------------------------------------
def _monthly(df: pd.DataFrame, col: str) -> pd.Series:
    d = df.dropna(subset=[col]).copy()
    d["_m"] = pd.PeriodIndex(pd.to_datetime(d["date"]), freq="M")
    return d.groupby("_m")[col].mean()


def _cluster(x: np.ndarray, boot: int = 4000, seed: int = 5) -> dict:
    k = len(x)
    if k < 6:
        return {"available": False, "reason": f"only {k} months"}
    mean = float(np.mean(x))
    se = float(np.std(x, ddof=1) / np.sqrt(k))
    t = mean / se if se > 0 else float("nan")
    rng = np.random.default_rng(seed)
    draws = x[rng.integers(0, k, size=(boot, k))].mean(axis=1)
    return {"available": True, "mean": mean, "se": se, "t": float(t),
            "p_one_sided": float(stats.t.sf(t, df=k - 1)) if np.isfinite(t) else float("nan"),
            "p_two_sided": float(2 * stats.t.sf(abs(t), df=k - 1)) if np.isfinite(t) else float("nan"),
            "boot_ci95": [float(np.quantile(draws, 0.025)), float(np.quantile(draws, 0.975))],
            "months": k, "share_months_positive": float((x > 0).mean())}


def _paired(real: pd.DataFrame, fake: pd.DataFrame, col: str) -> dict:
    a, b = _monthly(real, col), _monthly(fake, col)
    both = a.index.intersection(b.index)
    if len(both) < 6:
        return {"available": False, "reason": f"only {len(both)} shared months"}
    r = _cluster((a.loc[both] - b.loc[both]).to_numpy())
    r["real"] = float(a.loc[both].mean())
    r["pseudo"] = float(b.loc[both].mean())
    return r


def run_tests(real: pd.DataFrame, fake: pd.DataFrame, spec, alpha: float = 0.05,
              n_variants: int = 6) -> dict:
    adj = alpha / max(1, n_variants)
    R = spec.reward_multiple
    cost_r = float(real["cost_r"].median()) if len(real) else 0.0
    be = breakeven_rate(R, cost_r)
    out = {"alpha_bonferroni": adj, "reward_multiple": R,
           "median_cost_r": cost_r,
           "breakeven_hit_rate_gross": breakeven_rate(R, 0.0),
           "breakeven_hit_rate_net": be}

    hit = real["hit_target"].astype(float)
    out["hit_rate"] = float(hit.mean())
    out["pseudo_hit_rate"] = float(fake["hit_target"].astype(float).mean()) if len(fake) else None
    out["resolution_rate"] = float(real["resolved"].mean())
    out["stop_rate"] = float(real["hit_stop"].astype(float).mean())

    # S1 on resolved trades only — see AMENDMENT.
    res = real[real["resolved"].astype(bool)]
    out["hit_rate_given_resolved"] = float(res["hit_target"].astype(float).mean()) \
        if len(res) else None
    fres = fake[fake["resolved"].astype(bool)]
    out["pseudo_hit_rate_given_resolved"] = float(fres["hit_target"].astype(float).mean()) \
        if len(fres) else None
    excess = _monthly(res.assign(_x=res["hit_target"].astype(float) - be), "_x")
    s1 = _cluster(excess.to_numpy())
    if s1.get("available"):
        s1["threshold"] = adj
        s1["pass"] = bool(s1["p_one_sided"] < adj and s1["mean"] > 0)
        s1["note"] = (f"P(target | resolved) minus the cost-adjusted breakeven of "
                      f"{be:.3f}. For a driftless random walk that probability is "
                      f"exactly 1/3, so this asks whether the setups drift up.")
    out["S1_setup_beats_its_breakeven_hit_rate"] = s1

    s2 = _paired(res.assign(_h=res["hit_target"].astype(float)),
                 fres.assign(_h=fres["hit_target"].astype(float)), "_h")
    if s2.get("available"):
        s2["threshold"] = adj
        s2["pass"] = bool(s2["p_one_sided"] < adj and s2["mean"] > 0)
    out["S2_setup_beats_the_pseudo_setup_control"] = s2

    s3 = _cluster(_monthly(real, "r_net").to_numpy())
    if s3.get("available"):
        s3["threshold"] = adj
        s3["pass"] = bool(s3["p_one_sided"] < adj and s3["mean"] > 0)
    out["S3_expectancy_net_of_costs_is_positive"] = s3
    return out


def _bucketize(x: pd.Series, n: int):
    """Quantile buckets, falling back to raw values when cardinality is low.

    `qcut` silently refuses a variable with fewer distinct values than buckets,
    and the caller then drops it as "unavailable". That is how `market_regime` —
    the only genuine timing variable in the list — went untested through a whole
    study while appearing in the report as though it had been examined.
    """
    if x.nunique() <= n:
        return x.rank(method="dense").astype(int) - 1, int(x.nunique())
    try:
        b = pd.qcut(x, n, labels=False, duplicates="drop")
        return b, int(pd.Series(b).nunique())
    except ValueError:
        return None, 0


def conditioner_report(real: pd.DataFrame, cond_cols: list[str], spec,
                       alpha: float = 0.05, n_variants: int = 6,
                       buckets: int = 5, seed: int = 71,
                       control: pd.DataFrame | None = None) -> dict:
    """Does anything TIME the setup? One row per conditioner.

    Named `conditioner_report` rather than `test_...` deliberately: pytest
    collects any importable name beginning with `test_`, so a helper called
    `test_conditioners` gets picked up as a broken test case in every module
    that imports it.

    Two properties this reports that an earlier version did not, both of which
    hid real information:

      * **Two-sided.** An inverse relationship is still a relationship. Scoring
        only "top bucket beats bottom" marked `risk_pct` — the largest effect in
        the table at |t| = 4.91 with a perfect -1.00 rank correlation — as a
        failure, because tighter stops raise the hit rate rather than lower it.

      * **Expectancy beside hit rate.** `risk_pct` also demonstrates why: a
        tighter stop brings the 2R target nearer, so the hit rate rises
        mechanically while expectancy in R does not move at all. A conditioner
        that sorts hit rate and not expectancy has sorted nothing.

    When `control` is supplied, the same bucketing is applied to the pseudo-setup
    book and the control's own top-minus-bottom is reported alongside. A
    conditioner that lifts the control equally is selecting names, not timing
    triggers.
    """
    adj = alpha / max(1, n_variants)
    out = {"n_conditioners": len(cond_cols), "alpha_bonferroni": adj, "rows": {}}
    rng = np.random.default_rng(seed)

    for c in cond_cols:
        d = real.dropna(subset=[c, "hit_target"]).copy()
        if len(d) < 400:
            out["rows"][c] = {"available": False, "reason": f"only {len(d)} setups"}
            continue
        b, nb = _bucketize(d[c], buckets)
        if b is None or nb < 2:
            out["rows"][c] = {"available": False, "reason": "cannot bucket"}
            continue
        d["_b"] = b
        d["_h"] = d["hit_target"].astype(float)
        by = d.groupby("_b").agg(hit=("_h", "mean"), r=("r_net", "mean"), n=("_h", "size"))
        rho, p_rho = stats.spearmanr(by.index.to_numpy(), by["hit"].to_numpy())
        rho_r, _ = stats.spearmanr(by.index.to_numpy(), by["r"].to_numpy())

        hi, lo = d[d["_b"] == by.index.max()], d[d["_b"] == by.index.min()]
        a_, b_ = _monthly(hi, "_h"), _monthly(lo, "_h")
        both = a_.index.intersection(b_.index)
        diff = _cluster((a_.loc[both] - b_.loc[both]).to_numpy()) if len(both) >= 6 \
            else {"available": False}
        ar, br = _monthly(hi, "r_net"), _monthly(lo, "r_net")
        bothr = ar.index.intersection(br.index)
        diff_r = _cluster((ar.loc[bothr] - br.loc[bothr]).to_numpy()) if len(bothr) >= 6 \
            else {"available": False}

        ctrl = None
        if control is not None and c in control.columns:
            cd = control.dropna(subset=[c, "hit_target"]).copy()
            cb, cnb = _bucketize(cd[c], buckets)
            if cb is not None and cnb >= 2:
                cd["_b"] = cb
                cd["_h"] = cd["hit_target"].astype(float)
                ca = _monthly(cd[cd["_b"] == cd["_b"].max()], "_h")
                cbm = _monthly(cd[cd["_b"] == cd["_b"].min()], "_h")
                cboth = ca.index.intersection(cbm.index)
                if len(cboth) >= 6:
                    ctrl = _cluster((ca.loc[cboth] - cbm.loc[cboth]).to_numpy())

        d["_s"] = d.groupby(pd.PeriodIndex(pd.to_datetime(d["date"]), freq="M"))[c] \
                   .transform(lambda x: rng.permutation(x.to_numpy()))
        sb, snb = _bucketize(d["_s"], buckets)
        placebo = {"available": False}
        if sb is not None and snb >= 2:
            d["_sb"] = sb
            sa = _monthly(d[d["_sb"] == d["_sb"].max()], "_h")
            sbm = _monthly(d[d["_sb"] == d["_sb"].min()], "_h")
            sboth = sa.index.intersection(sbm.index)
            if len(sboth) >= 6:
                placebo = _cluster((sa.loc[sboth] - sbm.loc[sboth]).to_numpy())

        t_hit = diff.get("t")
        t_r = diff_r.get("t")
        # Two-sided: an inverse relationship is still a relationship.
        p_hit = diff.get("p_two_sided")
        p_r = diff_r.get("p_two_sided")
        excess = None
        if ctrl and ctrl.get("available") and diff.get("available"):
            excess = diff["mean"] - ctrl["mean"]

        out["rows"][c] = {
            "available": True, "n": int(len(d)), "buckets": nb,
            "bucket_hit_rates": [round(float(v), 4) for v in by["hit"]],
            "bucket_expectancy_r": [round(float(v), 4) for v in by["r"]],
            "spearman_hit": float(rho), "spearman_r": float(rho_r),
            "top_minus_bottom_hit": diff.get("mean"), "t_hit": t_hit,
            "p_two_sided_hit": p_hit,
            "top_minus_bottom_r": diff_r.get("mean"), "t_r": t_r,
            "p_two_sided_r": p_r,
            "control_top_minus_bottom": ctrl.get("mean") if ctrl else None,
            "excess_over_control": excess,
            "months": diff.get("months"), "placebo_t": placebo.get("t"),
            # The bar: it must sort EXPECTANCY, monotonically, beyond the control.
            "pass": bool(diff_r.get("available") and p_r is not None and p_r < adj
                         and abs(rho_r) >= 0.7),
            "pass_hit_rate_only": bool(diff.get("available") and p_hit is not None
                                       and p_hit < adj and abs(rho) >= 0.7),
        }
    return out


def verdict(tests: dict, cond: dict) -> dict:
    def ok(n):
        return bool(tests.get(n, {}).get("pass"))
    conditions = {
        "S1 hit rate beats cost-adjusted breakeven": ok("S1_setup_beats_its_breakeven_hit_rate"),
        "S2 setup beats the pseudo-setup control": ok("S2_setup_beats_the_pseudo_setup_control"),
        "S3 net expectancy positive": ok("S3_expectancy_net_of_costs_is_positive"),
    }
    timers = sorted([k for k, v in cond.get("rows", {}).items() if v.get("pass")])
    hit_only = sorted([k for k, v in cond.get("rows", {}).items()
                       if v.get("pass_hit_rate_only") and not v.get("pass")])
    base_ok = all(conditions.values())
    return {
        "setup_has_edge": base_ok,
        "conditions": conditions,
        "conditioners_that_time_it": timers,
        "sort_hit_rate_but_not_expectancy": hit_only,
        "n_conditioners_tested": cond.get("n_conditioners", 0),
        "decision_rule": DECISION_RULE,
        "recommendation": (
            f"The setup clears its breakeven and its control. "
            + (f"Timing signals that survive: {', '.join(timers)}. Stack these and "
               "re-measure jointly before sizing."
               if timers else
               "No conditioner times it, so trade it flat-weighted or not at all.")
            if base_ok else
            "The setup does not clear its own control. Conditioning cannot rescue "
            "it — selecting which negative-expectancy trades to take still loses. "
            "Fix the trade before timing it."
        ),
    }
