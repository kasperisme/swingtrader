"""Anchoring — what the spread is measured AGAINST, and the null that goes with it.

The frozen design measures every divergence against a mean and a standard
deviation estimated once, during formation, and held for the next six months.
D2 showed that anchor goes stale: the spread's LEVEL moves, and not because the
hedge ratio was mismeasured. The obvious repair is to re-anchor continuously,
which is the actual difference between 1990s pairs trading and modern
statistical arbitrage — more so than the choice of hedge.

**The repair is also a trap.** Subtracting a trailing mean makes a series look
stationary whether or not it is. A pure random walk, demeaned on a rolling
60-day window, oscillates around zero and crosses it constantly. Measure
"convergence" on that and you will find plenty, all of it manufactured by the
filter — the identical failure mode to the EMA that manufactured flow
persistence in Stage 1, and pinned there as a test for the same reason.

So every anchoring scheme here ships with its own simulated null:
`synthetic_null()` builds spreads from two INDEPENDENT random walks, selects
them with the same cointegration and half-life screens the real book uses, and
runs the identical event scanner. Whatever convergence rate that produces is
what "no mean reversion at all" looks like under that anchor. Only the excess
over it counts.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .formation import adf_t, half_life

log = logging.getLogger(__name__)


@dataclass
class AnchorSpec:
    """How z is computed. `formation` reproduces the original frozen design."""

    mode: str = "formation"              # "formation" | "rolling"
    window: int = 60                     # trailing sessions for mu and sigma
    min_periods: int = 40
    rolling_beta: bool = False           # also re-estimate the hedge ratio
    beta_window: int = 252

    @property
    def label(self) -> str:
        if self.mode == "formation":
            return "frozen (formation mu/sigma, formation beta)"
        b = f"rolling beta {self.beta_window}d" if self.rolling_beta else "formation beta"
        return f"rolling {self.window}d mu/sigma, {b}"


def _rolling_mu_sd(s: np.ndarray, window: int, min_periods: int):
    """Trailing mean and sd, EXCLUDING the current bar.

    The `shift(1)` is the whole no-look-ahead argument: the anchor applied on
    day t is built only from days strictly before t, so the bar being scored
    never contributes to the level it is scored against.
    """
    f = pd.DataFrame(s) if s.ndim > 1 else pd.Series(s)
    r = f.rolling(window, min_periods=min_periods)
    mu = r.mean().shift(1)
    sd = r.std(ddof=1).shift(1)
    return np.asarray(mu), np.asarray(sd)


def _rolling_beta(a: np.ndarray, b: np.ndarray, window: int, min_periods: int):
    """Trailing OLS slope of a on b, excluding the current bar."""
    A = pd.DataFrame(a) if a.ndim > 1 else pd.Series(a)
    B = pd.DataFrame(b) if b.ndim > 1 else pd.Series(b)
    ra, rb = A.rolling(window, min_periods=min_periods), B.rolling(window, min_periods=min_periods)
    cov = ra.cov(B) if a.ndim == 1 else A.rolling(window, min_periods=min_periods).cov(B)
    var = rb.var(ddof=1)
    beta = (cov / var.replace(0, np.nan)).shift(1)
    return np.asarray(beta)


def anchored_z(pair, close: np.ndarray, anchor: AnchorSpec) -> np.ndarray:
    """z of the log spread under `anchor`, over the whole panel."""
    a = np.log(np.where(close[:, pair.ia] > 0, close[:, pair.ia], np.nan))
    b = np.log(np.where(close[:, pair.ib] > 0, close[:, pair.ib], np.nan))

    if anchor.rolling_beta:
        beta = _rolling_beta(a, b, anchor.beta_window, max(anchor.min_periods, 60))
        s = a - beta * b
    else:
        s = a - pair.alpha - pair.beta * b

    if anchor.mode == "formation" and not anchor.rolling_beta:
        return (s - pair.mu) / pair.sigma
    mu, sd = _rolling_mu_sd(s, anchor.window, anchor.min_periods)
    with np.errstate(invalid="ignore", divide="ignore"):
        return (s - mu) / np.where(np.isfinite(sd) & (sd > 0), sd, np.nan)


def z_from_series(s: np.ndarray, anchor: AnchorSpec, f0: int, f1: int) -> np.ndarray:
    """Anchor an already-built spread matrix, shape (T,) or (T, K).

    Used by the synthetic null, so that the null and the real book share one
    anchoring implementation rather than two that can drift apart.
    """
    if anchor.mode == "formation":
        seg = s[f0:f1]
        mu = np.nanmean(seg, axis=0)
        sd = np.nanstd(seg, axis=0, ddof=1)
        return (s - mu) / np.where(sd > 0, sd, np.nan)
    mu, sd = _rolling_mu_sd(s, anchor.window, anchor.min_periods)
    with np.errstate(invalid="ignore", divide="ignore"):
        return (s - mu) / np.where(np.isfinite(sd) & (sd > 0), sd, np.nan)


# ----------------------------------------------------------------------
def quartile_table(adf: np.ndarray, conv: np.ndarray) -> dict:
    """Convergence by in-sample cointegration strength.

    Needed because a more negative in-sample ADF mechanically selects spread
    paths that happened to oscillate, and some of that oscillation carries into
    the next window EVEN FOR RANDOM WALKS. Without this control the real book's
    "stronger pairs converge more" gradient reads as surviving edge.
    """
    adf, conv = np.asarray(adf, float), np.asarray(conv, float)
    if adf.size < 200:
        return {}
    qs = np.quantile(adf, [0.25, 0.5, 0.75])
    labels = ["Q1_strongest", "Q2", "Q3", "Q4_weakest"]
    idx = np.digitize(adf, qs)
    out = {}
    for k, lab in enumerate(labels):
        m = idx == k
        if m.sum():
            out[lab] = {"convergence": float(conv[m].mean()),
                        "median_adf": float(np.median(adf[m])), "n": int(m.sum())}
    return out


def _rolling_beta_spread(a: np.ndarray, b: np.ndarray, anchor: AnchorSpec) -> np.ndarray:
    """a - beta_t * b with beta_t a trailing OLS slope, for a matrix of pairs."""
    beta = _rolling_beta(a, b, anchor.beta_window, max(anchor.min_periods, 60))
    return a - beta * b


def synthetic_null(anchor: AnchorSpec, espec, fspec, crit: float,
                   n_keep: int = 4000, seed: int = 31,
                   block: int = 4000, max_blocks: int = 60) -> dict:
    """Convergence rate under NO mean reversion, matched to this anchor.

    Two independent Gaussian random walks per candidate, regressed on one
    another over the formation segment exactly as `form_pairs` does, then
    screened on the same ADF critical value and half-life band. The survivors
    are spurious by construction: nothing in them reverts. Running the real
    event scanner over their trading segment gives the convergence rate the
    machinery reports when there is nothing to find.

    This is the number the realised rate has to beat. For the frozen anchor it
    should land near the analytic random-walk first-passage probability, which
    is a useful check that the simulation is not itself broken.
    """
    from .events import scan_convergence

    rng = np.random.default_rng(seed)
    T_form, T_trade, H = fspec.formation_days, fspec.trading_days, espec.horizon
    T = T_form + T_trade + H
    kept = 0
    conv, conv_soft, rmst, screened, n_events = [], [], [], 0, 0
    adf_of_event: list[float] = []

    for _ in range(max_blocks):
        if kept >= n_keep:
            break
        wa = rng.standard_normal((T, block)).cumsum(axis=0)
        wb = rng.standard_normal((T, block)).cumsum(axis=0)
        af, bf = wa[:T_form], wb[:T_form]
        am, bm = af.mean(axis=0), bf.mean(axis=0)
        ac, bc = af - am, bf - bm
        var = (bc * bc).sum(axis=0)
        var = np.where(var > 0, var, np.nan)
        beta = (ac * bc).sum(axis=0) / var
        alpha = am - beta * bm
        s = wa - alpha - beta * wb

        t = adf_t(s[:T_form], lags=fspec.adf_lags)
        hl = half_life(s[:T_form])
        ok = (np.isfinite(t) & (t <= crit)
              & (hl >= fspec.min_half_life) & (hl <= fspec.max_half_life))
        screened += block
        if not ok.any():
            continue

        t_sel = t[ok]
        sel = s[:, ok]
        if anchor.rolling_beta:
            # The real book screens on the STATIC formation OLS spread and only
            # then trades a rolling-beta spread, so the null must do both in the
            # same order. Rebuilding the spread here (rather than reusing `sel`)
            # is what makes A2's null actually matched to A2 — scoring it against
            # A1's null understates it badly.
            sel = _rolling_beta_spread(wa[:, ok], wb[:, ok], anchor)
        z = z_from_series(sel, anchor, 0, T_form)
        for j in range(sel.shape[1]):
            if kept >= n_keep:
                break
            evs = scan_convergence(z[:, j], T_form, T_form + T_trade, espec, n=T)
            kept += 1
            for e in evs:
                n_events += 1
                conv.append(float(e["converged"]))
                conv_soft.append(float(e["converged_soft"]))
                rmst.append(e["rmst_days"])
                adf_of_event.append(float(t_sel[j]))

    if not conv:
        return {"available": False, "reason": "the null screen produced no events",
                "spurious_pairs": kept}
    return {
        "available": True,
        "anchor": anchor.label,
        "spurious_pairs_kept": kept,
        "candidates_screened": screened,
        "screen_pass_rate": round(kept / max(1, screened), 5),
        "events": n_events,
        "convergence": float(np.mean(conv)),
        "convergence_soft": float(np.mean(conv_soft)),
        "rmst_days": float(np.mean(rmst)),
        "by_adf_quartile": quartile_table(np.array(adf_of_event), np.array(conv)),
        "note": ("Convergence produced by pure random walks that passed the same "
                 "cointegration and half-life screens. Any realised rate at or "
                 "below this is consistent with no mean reversion whatsoever."),
    }
