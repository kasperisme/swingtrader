"""
Cointegration statistics for a ticker pair — pure functions, no I/O.

Given two aligned price series A and B:

  hedge_ratio   beta from OLS  A = alpha + beta * B
  spread        A - beta * B
  coint_pvalue  Engle-Granger p-value (ADF on the spread, MacKinnon p-values
                via statsmodels.tsa.stattools.coint) — p < 0.05 => cointegrated
  half_life     Ornstein-Uhlenbeck mean-reversion half-life in trading days
                (None when the spread does not revert)
  spread_mean,  rolling-window mean / sample std of the spread; the live
  spread_std    z-score refresh reads these STORED values and never recomputes
                a mean over a window that includes the current bar (this is
                what keeps look-ahead bias out of the signal).

Kept deliberately I/O-free so it is unit-testable without a DB or FMP.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd
from statsmodels.tsa.stattools import coint

# Minimum aligned observations before a fit is meaningful. Below this the
# Engle-Granger p-value and half-life are too noisy to act on.
MIN_OBS = 60


@dataclass
class PairStats:
    hedge_ratio: float
    coint_pvalue: Optional[float]
    half_life_days: Optional[float]
    spread_mean: float
    spread_std: float
    n_obs: int
    window_days: int


def _ou_half_life(spread: np.ndarray) -> Optional[float]:
    """Half-life of mean reversion from an OU fit: regress Δs_t on s_{t-1}.

    half_life = -ln(2) / lambda, where lambda is the AR(1)-style coefficient.
    Returns None when the spread is not mean-reverting (lambda >= 0).
    """
    s = np.asarray(spread, dtype=float)
    if s.size < 3:
        return None
    lag = s[:-1]
    delta = s[1:] - s[:-1]
    design = np.column_stack([np.ones_like(lag), lag])
    coef, *_ = np.linalg.lstsq(design, delta, rcond=None)
    lam = coef[1]
    if lam >= 0:
        return None
    hl = -np.log(2.0) / lam
    if not np.isfinite(hl) or hl <= 0:
        return None
    return float(hl)


def compute_pair_stats(
    prices_a: pd.Series,
    prices_b: pd.Series,
    window_days: int = 252,
) -> Optional[PairStats]:
    """Compute calibration stats for a pair from two date-indexed price series.

    The series are inner-joined on date and truncated to the most recent
    ``window_days`` aligned observations. Returns None when there is not enough
    overlapping history (< MIN_OBS) or the spread is degenerate.
    """
    df = pd.concat(
        [pd.Series(prices_a).rename("a"), pd.Series(prices_b).rename("b")],
        axis=1,
    ).dropna()
    if window_days and len(df) > window_days:
        df = df.iloc[-window_days:]
    if len(df) < MIN_OBS:
        return None

    a = df["a"].to_numpy(dtype=float)
    b = df["b"].to_numpy(dtype=float)
    if np.allclose(b.std(), 0.0) or np.allclose(a.std(), 0.0):
        return None

    # Hedge ratio: OLS with intercept (A ~ alpha + beta*B).
    design = np.column_stack([np.ones_like(b), b])
    coef, *_ = np.linalg.lstsq(design, a, rcond=None)
    hedge_ratio = float(coef[1])

    spread = a - hedge_ratio * b
    spread_mean = float(np.mean(spread))
    spread_std = float(np.std(spread, ddof=1))
    if not np.isfinite(spread_std) or spread_std <= 0:
        return None

    # Engle-Granger cointegration p-value (constant trend, MacKinnon p-values).
    coint_pvalue: Optional[float]
    try:
        _tstat, pvalue, _crit = coint(a, b, trend="c")
        coint_pvalue = float(pvalue) if np.isfinite(pvalue) else None
    except (ValueError, np.linalg.LinAlgError):
        coint_pvalue = None

    return PairStats(
        hedge_ratio=hedge_ratio,
        coint_pvalue=coint_pvalue,
        half_life_days=_ou_half_life(spread),
        spread_mean=spread_mean,
        spread_std=spread_std,
        n_obs=len(df),
        window_days=window_days,
    )


def live_zscore(
    price_a: float,
    price_b: float,
    hedge_ratio: float,
    spread_mean: float,
    spread_std: float,
) -> Optional[tuple[float, float]]:
    """Return (current_spread, z_score) from stored calibration, or None.

    Deliberately dumb and cheap: one arithmetic pass against the STORED
    spread_mean / spread_std. No regression, no history pull — this is what
    lets the fast clock run every few minutes.
    """
    if spread_std is None or spread_std <= 0:
        return None
    try:
        spread = float(price_a) - float(hedge_ratio) * float(price_b)
    except (TypeError, ValueError):
        return None
    z = (spread - float(spread_mean)) / float(spread_std)
    if not np.isfinite(z):
        return None
    return spread, float(z)
