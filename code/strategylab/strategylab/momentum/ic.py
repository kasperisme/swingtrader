"""Information coefficients, and the only version of them that decides anything.

Three numbers per signal, in increasing order of how much they are worth:

  **IC** — the daily cross-sectional rank correlation between the score and the
  forward return. Easy to produce and easy to be fooled by.

  **Incremental IC** — the Fama-MacBeth coefficient on that signal with the
  momentum controls in the same regression. On a universe that IS a momentum
  screen, almost everything correlates with momentum, so a standalone IC mostly
  measures how much of the screen a signal has re-encoded. This is the number
  that says whether a signal adds anything.

  **Placebo IC** — the same pipeline with scores shuffled within each day. It
  must come out at zero. It catches alignment bugs, look-ahead in the forward
  return, and survivorship leaking through the mask, none of which announce
  themselves in the headline IC.

Overlap is handled explicitly. A 21-day forward return computed every day
produces an IC series with ~21 days of autocorrelation, so a naive t-stat on it
overstates significance by roughly sqrt(21) — a factor of four and a half. Every
t here is Newey-West with lags set to the horizon.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd
from scipy import stats

from ..flow.panel import _newey_west_t

log = logging.getLogger(__name__)

MIN_NAMES = 30


def forward_returns(panel, horizon: int, tradeable: bool = True) -> np.ndarray:
    """Return earned by acting on the close of day t.

    A score computed on the close of t is filled at the OPEN of t+1 and exited
    at the open of t+1+horizon. That one-session lag is the difference between
    a backtest and a fantasy, and it is why this is not `close[t+h]/close[t]`.
    """
    n, m = panel.close.shape
    out = np.full((n, m), np.nan)
    src = panel.open if tradeable else panel.close
    lo = 1 if tradeable else 0
    hi = lo + horizon
    if hi >= n:
        return out
    a = src[lo:n - horizon]
    b = src[lo + horizon:n]
    with np.errstate(invalid="ignore", divide="ignore"):
        out[:n - horizon - lo] = b / a - 1.0
    return out


def _rank_normalise(row: np.ndarray) -> np.ndarray:
    """Cross-sectional rank mapped to roughly N(0,1). Robust to the outliers
    that a raw z-score lets dominate a 240-name cross-section."""
    ok = np.isfinite(row)
    out = np.full(row.shape, np.nan)
    k = int(ok.sum())
    if k < MIN_NAMES:
        return out
    r = stats.rankdata(row[ok]) / (k + 1.0)
    out[ok] = stats.norm.ppf(r)
    return out


def daily_ic(score: np.ndarray, fwd: np.ndarray, mask: np.ndarray,
             min_names: int = MIN_NAMES) -> np.ndarray:
    """Spearman IC per session, NaN on days with too thin a cross-section."""
    n = score.shape[0]
    out = np.full(n, np.nan)
    for t in range(n):
        ok = mask[t] & np.isfinite(score[t]) & np.isfinite(fwd[t])
        k = int(ok.sum())
        if k < min_names:
            continue
        s, f = score[t, ok], fwd[t, ok]
        if np.all(s == s[0]) or np.all(f == f[0]):
            continue
        out[t] = stats.spearmanr(s, f).statistic
    return out


def ic_summary(ic: np.ndarray, horizon: int) -> dict:
    """IC statistics with an overlap correction that degrades honestly.

    Newey-West with `lags = horizon` is the standard choice and it silently
    stops working when the sample is only a few multiples of the horizon: the
    estimator needs lags to be a small fraction of T, and at 21 lags on 101
    observations it UNDER-states the standard error badly. That produced a
    t = 2.95 on the news holdout where the effective sample was 4.8 independent
    observations and the honest figure was 1.09.

    So the lag count is capped at a tenth of the sample, and when the cap binds
    the result carries `overlap_unreliable` plus a block t-statistic computed
    from non-overlapping blocks — which cannot be fooled by the lag choice
    because it does not make one.
    """
    x = ic[np.isfinite(ic)]
    if x.size < 50:
        return {"available": False, "days": int(x.size)}
    wanted = max(1, horizon)
    lags = min(wanted, max(1, x.size // 10))
    mu, se, t = _newey_west_t(x, lags=lags)
    naive_t = float(x.mean() / (x.std(ddof=1) / np.sqrt(x.size)))
    # Non-overlapping block mean: one observation per horizon, no lag choice to
    # get wrong. The conservative cross-check on the NW figure.
    nb = max(1, x.size // wanted)
    blocks = np.array([x[i * wanted:(i + 1) * wanted].mean() for i in range(nb)])
    # Eight blocks is already thin; below that a t-statistic is theatre and is
    # not reported at all. The news holdout at a 21-day horizon yields four,
    # and four blocks produced a "+3.40" that means nothing.
    block_t = (float(blocks.mean() / (blocks.std(ddof=1) / np.sqrt(nb)))
               if nb >= 8 and blocks.std(ddof=1) > 0 else float("nan"))
    return {
        "available": True,
        "ic_mean": float(mu),
        "nw_lags_used": int(lags), "nw_lags_wanted": int(wanted),
        "overlap_unreliable": bool(lags < wanted),
        "effective_independent_obs": round(x.size / wanted, 1),
        "t_block": block_t, "n_blocks": int(nb),
        "too_few_blocks": bool(nb < 8),
        "ic_std": float(x.std(ddof=1)),
        "t_newey_west": float(t),
        "t_naive_overstated": naive_t,
        "overstatement_factor": float(naive_t / t) if t not in (0.0,) else None,
        "ir_annualised": float(mu / x.std(ddof=1) * np.sqrt(252 / max(1, horizon)))
        if x.std(ddof=1) > 0 else None,
        "hit_rate": float((x > 0).mean()),
        "days": int(x.size),
    }


def placebo_ic(score: np.ndarray, fwd: np.ndarray, mask: np.ndarray,
               horizon: int, seeds: int = 5, seed0: int = 19) -> dict:
    """Shuffle scores within each day. Must come out at zero.

    Run over several seeds rather than one. A single draw of a mean-zero
    statistic lands beyond |t| = 2 about one time in twenty, and with sixteen
    signals in the table that is a near-certainty somewhere — which reads as a
    broken control when it is just a draw. The distribution across seeds is the
    honest check; one seed is a coin flip.
    """
    ts, ics = [], []
    for k in range(seeds):
        rng = np.random.default_rng(seed0 + k)
        sh = score.copy()
        for t in range(sh.shape[0]):
            ok = mask[t] & np.isfinite(sh[t])
            if ok.sum() >= MIN_NAMES:
                sh[t, ok] = rng.permutation(sh[t, ok])
        r = ic_summary(daily_ic(sh, fwd, mask), horizon)
        if r.get("available"):
            ts.append(r["t_newey_west"])
            ics.append(r["ic_mean"])
    if not ts:
        return {"available": False}
    a = np.asarray(ts)
    return {"available": True, "seeds": len(ts),
            "ic_mean": float(np.mean(ics)),
            "t_mean": float(a.mean()), "t_max_abs": float(np.abs(a).max()),
            "t_newey_west": float(a.mean()),
            "clean": bool(np.abs(a.mean()) < 1.5 and np.abs(a).max() < 3.0)}


def ic_report(scores: dict, panel, mask: np.ndarray, horizon: int,
              with_placebo: bool = True) -> dict:
    fwd = forward_returns(panel, horizon)
    out = {}
    for name, s in scores.items():
        ic = daily_ic(s, fwd, mask)
        row = ic_summary(ic, horizon)
        if with_placebo and row.get("available"):
            p = placebo_ic(s, fwd, mask, horizon)
            row["placebo_ic_mean"] = p.get("ic_mean")
            row["placebo_t"] = p.get("t_mean")
            row["placebo_t_max_abs"] = p.get("t_max_abs")
            row["placebo_clean"] = p.get("clean")
        out[name] = row
    return out


def incremental_ic(scores: dict, panel, mask: np.ndarray, horizon: int,
                   controls: list[str]) -> dict:
    """Fama-MacBeth: forward return on rank-normalised signals, day by day.

    The coefficient on a signal is its contribution AFTER everything else in the
    regression, which on a momentum-screened universe is the only honest measure
    of whether it is new information or a re-encoding of the screen.
    """
    fwd = forward_returns(panel, horizon)
    names = list(scores)
    n = panel.close.shape[0]
    coefs = {k: [] for k in names}
    kept = 0

    for t in range(n):
        ok = mask[t] & np.isfinite(fwd[t])
        if ok.sum() < MIN_NAMES:
            continue
        cols, use = [], []
        for k in names:
            v = _rank_normalise(np.where(ok, scores[k][t], np.nan))
            if np.isfinite(v).sum() >= MIN_NAMES:
                cols.append(v)
                use.append(k)
        if not cols:
            continue
        X = np.column_stack(cols)
        good = ok & np.isfinite(X).all(axis=1)
        if good.sum() < MIN_NAMES:
            continue
        A = np.column_stack([np.ones(good.sum()), X[good]])
        y = fwd[t, good]
        try:
            beta, *_ = np.linalg.lstsq(A, y, rcond=None)
        except np.linalg.LinAlgError:
            continue
        for i, k in enumerate(use):
            coefs[k].append(float(beta[i + 1]))
        kept += 1

    out = {"days": kept, "controls": list(controls), "coefficients": {}}
    for k in names:
        arr = np.asarray(coefs[k], dtype=float)
        if arr.size < 50:
            out["coefficients"][k] = {"available": False, "days": int(arr.size)}
            continue
        mu, se, t = _newey_west_t(arr, lags=max(1, horizon))
        out["coefficients"][k] = {
            "available": True,
            "mean_bps_per_sigma": float(mu * 1e4),
            "t_newey_west": float(t),
            "hit_rate": float((arr > 0).mean()),
            "days": int(arr.size),
            "is_control": k in controls,
        }
    return out


def signal_correlations(scores: dict, mask: np.ndarray, sample: int = 400,
                        seed: int = 3) -> pd.DataFrame:
    """Average daily cross-sectional rank correlation between signals.

    "Stacking" only helps to the extent the components are not the same thing.
    On a momentum universe they usually are, so this table decides how much of
    the ensemble is real breadth and how much is one signal counted twice.
    """
    names = list(scores)
    n = mask.shape[0]
    rng = np.random.default_rng(seed)
    days = np.flatnonzero(mask.sum(axis=1) >= MIN_NAMES)
    if days.size > sample:
        days = np.sort(rng.choice(days, size=sample, replace=False))
    acc = np.zeros((len(names), len(names)))
    cnt = np.zeros((len(names), len(names)))
    for t in days:
        ok = mask[t]
        cols = []
        for k in names:
            v = np.where(ok, scores[k][t], np.nan)
            cols.append(v)
        M = np.column_stack(cols)
        good = np.isfinite(M).all(axis=1)
        if good.sum() < MIN_NAMES:
            continue
        C = pd.DataFrame(M[good], columns=names).corr(method="spearman").to_numpy()
        fin = np.isfinite(C)
        acc[fin] += C[fin]
        cnt[fin] += 1
    with np.errstate(invalid="ignore"):
        avg = np.where(cnt > 0, acc / np.maximum(cnt, 1), np.nan)
    return pd.DataFrame(avg, index=names, columns=names)
