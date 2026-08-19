"""Time-series momentum — a mechanically different bet.

Cross-sectional momentum asks "which names are beating their peers?". Time-series
momentum (Moskowitz, Ooi & Pedersen 2012) asks a separate question of each
instrument on its own: "is this thing going up?" — long if its own trailing
return is positive, short if negative, sized to a constant volatility target.

Why it belongs here: the measured correlation across every strategy this search
produced was a median of 0.75, so 18 "different" configurations combined to a
Sharpe WORSE than the best single one. There was nothing to diversify across.
TSMOM is the standard escape because it is a different mechanism on a different
universe — it has no cross-sectional ranking, no relative comparison, and it can
be net short the whole book, which a long-only equity screen structurally cannot.

Implemented on liquid ETF proxies rather than the futures themselves. That is a
real compromise: ETFs carry management fees, borrow costs on the short side, and
their roll behaviour differs from the underlying futures. The direction of the
bias is unfavourable, which is the right way round for a test.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

TRADING_DAYS = 252


@dataclass
class TSMOMResult:
    dates: np.ndarray
    returns: np.ndarray                    # daily portfolio return
    positions: np.ndarray                  # (n_days, n_instruments) signed weights
    instruments: list[str]
    per_instrument: np.ndarray | None = None
    label: str = "TSMOM"
    meta: dict = field(default_factory=dict)

    def stats(self) -> dict:
        from .wml import WMLResult
        stub = WMLResult(self.dates, self.returns, self.returns,
                         np.zeros_like(self.returns), np.ones_like(self.returns),
                         np.zeros_like(self.returns), [], self.label)
        s = stub.stats()
        pos = self.positions
        s["avg_gross_leverage"] = float(np.nanmean(np.abs(pos).sum(axis=1)))
        s["avg_net_exposure"] = float(np.nanmean(pos.sum(axis=1)))
        s["share_long"] = float(np.nanmean(pos > 0))
        s["share_short"] = float(np.nanmean(pos < 0))
        return s


def build_tsmom(panel, lookback_days: int = 252, vol_target: float = 0.40,
                vol_lookback: int = 60, rebalance_days: int = 21,
                max_leverage_per_instrument: float = 2.0,
                cost_bps: float = 10.0, label: str = "TSMOM") -> TSMOMResult:
    """Sign of trailing return, sized to constant volatility, per instrument.

    Every quantity used at rebalance date t is computed from data up to and
    including t, and the resulting position earns returns from t+1 onward — the
    same signal-then-fill discipline as the equity engine.
    """
    close = panel.close
    n, m = close.shape
    prev = np.vstack([np.full((1, m), np.nan), close[:-1]])
    daily = close / np.where(prev > 0, prev, np.nan) - 1.0

    df = pd.DataFrame(daily)
    # Ex-ante volatility, shifted so the weight at t cannot see day t.
    vol = (df.rolling(vol_lookback, min_periods=max(20, vol_lookback // 2))
             .std(ddof=1).shift(1).to_numpy() * np.sqrt(TRADING_DAYS))

    trail = close / np.vstack([np.full((lookback_days, m), np.nan),
                               close[:-lookback_days]]) - 1.0

    positions = np.zeros((n, m))
    held = np.zeros(m)
    turnover = np.zeros(n)

    for t in range(1, n):
        if (t % rebalance_days) == 0 or t == lookback_days + 1:
            sig = np.sign(np.nan_to_num(trail[t], nan=0.0))
            v = vol[t]
            size = np.where(np.isfinite(v) & (v > 1e-6), vol_target / v, 0.0)
            size = np.clip(size, 0.0, max_leverage_per_instrument)
            tradable = np.isfinite(close[t]) & np.isfinite(trail[t]) & np.isfinite(v)
            new = np.where(tradable, sig * size, 0.0)
            k = max(1, int(tradable.sum()))
            new = new / k                     # equal risk budget across instruments
            turnover[t] = float(np.abs(new - held).sum())
            held = new
        positions[t] = held

    gross = np.abs(positions).sum(axis=1)
    per = positions * np.nan_to_num(daily, nan=0.0)
    ret = per.sum(axis=1)
    ret -= turnover * (cost_bps / 10_000.0)

    return TSMOMResult(dates=panel.dates, returns=ret, positions=positions,
                       instruments=list(panel.symbols), per_instrument=per,
                       label=label,
                       meta={"lookback_days": lookback_days, "vol_target": vol_target,
                             "rebalance_days": rebalance_days,
                             "avg_gross": float(np.nanmean(gross)),
                             "total_turnover": float(turnover.sum())})


def combine(series: dict[str, np.ndarray], weights: dict[str, float] | None = None
            ) -> tuple[np.ndarray, dict]:
    """Combine strategy return streams and report what diversification bought.

    Reports the realised combined Sharpe against the naive sqrt(N) ideal, so a
    correlated 'portfolio' cannot present itself as diversified.
    """
    names = list(series)
    n = min(len(series[k]) for k in names)
    M = np.column_stack([np.asarray(series[k])[:n] for k in names])
    w = np.array([(weights or {}).get(k, 1.0 / len(names)) for k in names])
    w = w / np.abs(w).sum()
    combo = M @ w

    def sr(x):
        sd = x.std(ddof=1)
        return float(x.mean() / sd * np.sqrt(TRADING_DAYS)) if sd > 1e-12 else 0.0

    sharpes = {k: sr(M[:, i]) for i, k in enumerate(names)}
    C = np.corrcoef(M, rowvar=False) if M.shape[1] > 1 else np.array([[1.0]])
    off = C[np.triu_indices_from(C, k=1)] if M.shape[1] > 1 else np.array([1.0])
    med_sr = float(np.median(list(sharpes.values())))
    k_n = M.shape[1]
    rho = float(np.median(off))
    ceiling = (med_sr * np.sqrt(k_n / (1 + (k_n - 1) * rho))
               if rho > -1 / max(k_n - 1, 1) else float("nan"))
    return combo, {
        "components": sharpes,
        "combined_sharpe": sr(combo),
        "median_correlation": rho,
        "min_correlation": float(off.min()),
        "max_correlation": float(off.max()),
        "theoretical_ceiling_at_median_rho": ceiling,
        "uncorrelated_ideal": med_sr * np.sqrt(k_n),
        "diversification_captured": (
            (sr(combo) - med_sr) / (med_sr * np.sqrt(k_n) - med_sr)
            if med_sr * np.sqrt(k_n) - med_sr > 1e-9 else 0.0),
    }
