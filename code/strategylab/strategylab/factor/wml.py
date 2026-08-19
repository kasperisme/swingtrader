"""WML construction and volatility-scaled variants.

Barroso & Santa-Clara (2015) report that scaling momentum by the inverse of its
own realised volatility lifts the Sharpe from 0.53 to 0.97 and collapses excess
kurtosis from 18.2 to 2.7. Both halves of that claim are testable here:

  * the *unmanaged* WML's Sharpe, skew and kurtosis — is the crash-prone object
    they describe even present in this universe and period?
  * the *managed* version's improvement, on the same series.

The second number is meaningless without the first. If our WML has kurtosis of 4
rather than 18, there is no crash to manage, and the overlay cannot reproduce a
benefit that came from removing one.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy import stats

TRADING_DAYS = 252


@dataclass
class WMLResult:
    dates: np.ndarray             # daily
    returns: np.ndarray           # daily WML return
    long_returns: np.ndarray
    short_returns: np.ndarray
    n_long: np.ndarray
    n_short: np.ndarray
    rebalance_idx: list[int] = field(default_factory=list)
    label: str = "WML"

    def stats(self, rf_annual: float = 0.0) -> dict:
        r = self.returns[np.isfinite(self.returns)]
        if r.size < 60:
            return {"n": int(r.size)}
        eq = np.cumprod(1.0 + r)
        peak = np.maximum.accumulate(eq)
        dd = float(np.nanmax(1.0 - eq / peak))
        sd = r.std(ddof=1)
        nz = r[r != 0]
        years = r.size / TRADING_DAYS
        return {
            "n_days": int(r.size),
            "sharpe": float((r.mean() - rf_annual / TRADING_DAYS) / sd * np.sqrt(TRADING_DAYS))
            if sd > 1e-12 else 0.0,
            "annual_return": float(eq[-1] ** (1 / max(years, 1e-9)) - 1.0),
            "annual_vol": float(sd * np.sqrt(TRADING_DAYS)),
            "max_drawdown": dd,
            "skew": float(stats.skew(nz)) if nz.size > 10 else 0.0,
            "excess_kurtosis": float(stats.kurtosis(nz, fisher=True)) if nz.size > 10 else 0.0,
            "worst_day": float(r.min()),
            "worst_month": float(pd.Series(r, index=pd.DatetimeIndex(self.dates[:r.size]))
                                 .resample("ME").apply(lambda x: (1 + x).prod() - 1).min()),
            "total_return": float(eq[-1] - 1.0),
        }


def _month_ends(dates: np.ndarray) -> list[int]:
    idx = pd.DatetimeIndex(dates)
    df = pd.DataFrame({"i": np.arange(len(idx))}, index=idx)
    return df.groupby([idx.year, idx.month])["i"].max().tolist()


def build_wml(panel, signal: np.ndarray, eligible: np.ndarray | None = None,
              n_portfolios: int = 10, weights: np.ndarray | None = None,
              min_names: int = 100, label: str = "WML") -> WMLResult:
    """Long the top `1/n` of `signal`, short the bottom, rebalanced monthly.

    `signal` is evaluated at each month end using only information available
    then; the resulting portfolio is held through the following month, and its
    daily returns are accumulated. Positions are fixed in SHARE terms over the
    month, so the weights drift exactly as an unrebalanced book would.
    """
    close = panel.close
    n, m = close.shape
    prev = np.vstack([np.full((1, m), np.nan), close[:-1]])
    daily = close / np.where(prev > 0, prev, np.nan) - 1.0

    ends = [i for i in _month_ends(panel.dates) if i < n - 1]
    out_r = np.zeros(n)
    out_l = np.zeros(n)
    out_s = np.zeros(n)
    nl = np.zeros(n)
    ns = np.zeros(n)
    used = []

    for k, t in enumerate(ends):
        nxt = ends[k + 1] if k + 1 < len(ends) else n - 1
        sig_t = signal[t].copy()
        ok = np.isfinite(sig_t) & np.isfinite(close[t])
        if eligible is not None:
            ok &= eligible[t]
        if ok.sum() < min_names:
            continue
        vals = sig_t[ok]
        idx = np.flatnonzero(ok)
        lo_c, hi_c = np.quantile(vals, [1.0 / n_portfolios, 1.0 - 1.0 / n_portfolios])
        longs = idx[vals >= hi_c]
        shorts = idx[vals <= lo_c]
        if longs.size < 5 or shorts.size < 5:
            continue
        used.append(t)

        w_l = (weights[t, longs] if weights is not None else np.ones(longs.size))
        w_s = (weights[t, shorts] if weights is not None else np.ones(shorts.size))
        w_l = np.nan_to_num(w_l, nan=0.0); w_s = np.nan_to_num(w_s, nan=0.0)
        if w_l.sum() <= 0:
            w_l = np.ones(longs.size)
        if w_s.sum() <= 0:
            w_s = np.ones(shorts.size)
        w_l = w_l / w_l.sum()
        w_s = w_s / w_s.sum()

        # Hold in share terms: weights drift with price over the month, which is
        # what an unrebalanced portfolio actually does.
        dl, ds = w_l.copy(), w_s.copy()
        for u in range(t + 1, nxt + 1):
            rl = np.nan_to_num(daily[u, longs], nan=0.0)
            rs = np.nan_to_num(daily[u, shorts], nan=0.0)
            ret_l = float(dl @ rl)
            ret_s = float(ds @ rs)
            out_l[u], out_s[u] = ret_l, ret_s
            out_r[u] = ret_l - ret_s
            nl[u], ns[u] = longs.size, shorts.size
            dl = dl * (1.0 + rl); ds = ds * (1.0 + rs)
            if dl.sum() > 0:
                dl /= dl.sum()
            if ds.sum() > 0:
                ds /= ds.sum()

    return WMLResult(dates=panel.dates, returns=out_r, long_returns=out_l,
                     short_returns=out_s, n_long=nl, n_short=ns,
                     rebalance_idx=used, label=label)


def apply_costs(res: WMLResult, one_way_bps: float = 13.0,
                borrow_bps_annual: float = 100.0,
                turnover_per_rebalance: float = 1.6) -> WMLResult:
    """Charge the frictions the academic construction ignores.

    A decile WML rebalanced monthly replaces most of both legs every month. At
    roughly 160% two-sided turnover per rebalance and 13bps a side, that is
    ~2.5%/yr before borrow — which is the same order as the entire raw Sharpe on
    this sample. Reporting a frictionless factor Sharpe as if it were achievable
    is the single largest gap between a paper and a portfolio.
    """
    r = res.returns.copy()
    per_rebalance = turnover_per_rebalance * (one_way_bps / 10_000.0)
    for t in res.rebalance_idx:
        u = min(t + 1, len(r) - 1)
        r[u] -= per_rebalance
    # Borrow accrues daily on the short leg, which is always fully invested.
    active = np.abs(res.short_returns) > 0
    r -= np.where(active, borrow_bps_annual / 10_000.0 / TRADING_DAYS, 0.0)
    return WMLResult(res.dates, r, res.long_returns, res.short_returns,
                     res.n_long, res.n_short, res.rebalance_idx,
                     label=res.label + " (after costs)")


def long_leg_only(res: WMLResult) -> WMLResult:
    """The long decile on its own — no borrow, no short-side capacity limit,
    and the only version most accounts can actually run."""
    return WMLResult(res.dates, res.long_returns, res.long_returns,
                     np.zeros_like(res.short_returns), res.n_long,
                     np.zeros_like(res.n_short), res.rebalance_idx,
                     label=res.label + " long leg only")


# ----------------------------------------------------------------------
def realised_vol(returns: np.ndarray, lookback: int = 126,
                 downside_only: bool = False) -> np.ndarray:
    """Trailing annualised volatility, strictly backward-looking.

    The value at t uses returns up to and including t-1, so the weight applied
    at t is knowable at t. Using the window through t would let the scaling see
    the very day it is scaling.
    """
    s = pd.Series(returns)
    if downside_only:
        s = s.where(s < 0, 0.0)
        # Semi-deviation of a one-sided series: rescale so the target is
        # comparable to the two-sided case for a symmetric distribution.
        vol = s.rolling(lookback, min_periods=lookback // 2).std(ddof=1) * np.sqrt(2.0)
    else:
        vol = s.rolling(lookback, min_periods=lookback // 2).std(ddof=1)
    return (vol.shift(1) * np.sqrt(TRADING_DAYS)).to_numpy()


def scale_constant_vol(res: WMLResult, target: float = 0.12, lookback: int = 126,
                       cap: float = np.inf, downside_only: bool = False
                       ) -> tuple[np.ndarray, np.ndarray]:
    """Barroso & Santa-Clara: w_t = sigma_target / sigma_hat_t."""
    vol = realised_vol(res.returns, lookback, downside_only)
    with np.errstate(divide="ignore", invalid="ignore"):
        w = np.where(np.isfinite(vol) & (vol > 1e-9), target / vol, np.nan)
    w = np.clip(np.nan_to_num(w, nan=1.0), 0.0, cap)
    return w * res.returns, w


def scale_dynamic(res: WMLResult, market_returns: np.ndarray, lookback: int = 126,
                  bear_lookback: int = 504, gamma: float = 0.10,
                  cap: float = 2.0) -> tuple[np.ndarray, np.ndarray]:
    """Daniel & Moskowitz style: scale on forecast MEAN as well as variance.

    Momentum's expected return is not constant — it is sharply negative in a
    bear market that has begun to rebound, which is when momentum crashes. A
    forecast using a bear-market indicator interacted with market variance
    captures that, and the optimal weight becomes mu_hat / (gamma * sigma_hat^2)
    rather than a constant numerator.
    """
    r = pd.Series(res.returns)
    mkt = pd.Series(np.nan_to_num(market_returns, nan=0.0))
    bear = (mkt.rolling(bear_lookback, min_periods=126).sum() < 0).astype(float).shift(1)
    var = r.rolling(lookback, min_periods=lookback // 2).var(ddof=1).shift(1)

    X = pd.concat([bear, bear * var * TRADING_DAYS], axis=1)
    X.columns = ["bear", "bear_var"]
    X.insert(0, "const", 1.0)
    y = r
    ok = X.notna().all(axis=1) & y.notna()
    # Expanding-window fit: the forecast at t may only use data up to t-1.
    mu = np.full(len(r), np.nan)
    idx = np.flatnonzero(ok.to_numpy())
    if idx.size > 260:
        Xv, yv = X.to_numpy(), y.to_numpy()
        start = idx[0] + 252
        for t in range(start, len(r)):
            sel = idx[idx < t]
            if sel.size < 252:
                continue
            try:
                beta, *_ = np.linalg.lstsq(Xv[sel], yv[sel], rcond=None)
            except np.linalg.LinAlgError:
                continue
            mu[t] = float(Xv[t] @ beta)
    varr = var.to_numpy() * TRADING_DAYS
    w = np.where(np.isfinite(mu) & np.isfinite(varr) & (varr > 1e-12),
                 mu * TRADING_DAYS / (gamma * varr), np.nan)
    # The unconstrained mean-variance weight is unusable: when the forecast
    # variance is small the ratio explodes, and an uncapped run produced 12x
    # average leverage and a −32,000% month. Daniel & Moskowitz cap it, and any
    # real implementation must. The default cap is deliberately conservative.
    w = np.clip(np.nan_to_num(w, nan=1.0), 0.0, cap)
    return w * res.returns, w


def scale_variants(res: WMLResult, market_returns: np.ndarray | None = None,
                   target: float = 0.12, lookback: int = 126,
                   cap: float = np.inf) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    out = {
        "constant vol": scale_constant_vol(res, target, lookback, cap),
        "semi-vol (downside)": scale_constant_vol(res, target, lookback, cap,
                                                  downside_only=True),
    }
    if market_returns is not None:
        out["dynamic (Daniel-Moskowitz)"] = scale_dynamic(res, market_returns,
                                                          lookback, cap=cap)
    return out
