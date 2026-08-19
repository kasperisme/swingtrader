"""Time-series momentum.

TSMOM exists here as a DIVERSIFIER, so the tests that matter are the ones that
would let it quietly fail to be one: look-ahead in the sizing, a signal that
does not actually follow the trend, and a combiner that reports diversification
it did not achieve.
"""

import numpy as np
import pandas as pd
import pytest

from strategylab.data.prices import Panel
from strategylab.factor.tsmom import build_tsmom, combine


def _panel(paths: np.ndarray, names=None) -> Panel:
    n, m = paths.shape
    return Panel(dates=pd.bdate_range("2005-01-01", periods=n).values.astype("datetime64[D]"),
                 symbols=names or [f"I{i}" for i in range(m)],
                 open=paths.copy(), high=paths * 1.005, low=paths * 0.995,
                 close=paths, volume=np.full((n, m), 1e9))


def test_goes_long_an_uptrend_and_short_a_downtrend():
    # Noise is required, not cosmetic: a noiseless path has zero realised
    # volatility, and volatility targeting correctly refuses to size it.
    n = 900
    rng = np.random.default_rng(7)
    up = 100 * np.exp(np.cumsum(rng.normal(0.0010, 0.008, n)))
    down = 100 * np.exp(np.cumsum(rng.normal(-0.0010, 0.008, n)))
    res = build_tsmom(_panel(np.column_stack([up, down])), cost_bps=0.0)
    late = res.positions[-1]
    assert late[0] > 0, "did not go long a persistent uptrend"
    assert late[1] < 0, "did not go short a persistent downtrend"
    assert res.returns[300:].sum() > 0, "lost money on two clean trends"


def test_sizing_cannot_see_the_day_it_sizes():
    """The volatility used to size at t must come from data before t. Without
    the shift, the book would shrink on exactly the days it was about to be
    hurt — a look-ahead that looks like brilliant risk management."""
    rng = np.random.default_rng(0)
    n = 800
    base = 100 * np.exp(np.cumsum(rng.normal(0.0004, 0.01, (n, 3)), axis=0))
    a = build_tsmom(_panel(base.copy()), cost_bps=0.0)

    shocked = base.copy()
    shocked[600:] *= 1.0 + rng.normal(0, 0.05, (n - 600, 3))
    b = build_tsmom(_panel(shocked), cost_bps=0.0)
    # Positions BEFORE the divergence must be identical.
    assert np.allclose(a.positions[:600], b.positions[:600], equal_nan=True), \
        "future prices changed past positions"


def test_volatility_targeting_shrinks_the_book_when_vol_rises():
    n = 1000
    rng = np.random.default_rng(1)
    calm = np.cumsum(rng.normal(0.0008, 0.004, (n // 2, 2)), axis=0)
    wild = np.cumsum(rng.normal(0.0008, 0.040, (n // 2, 2)), axis=0)
    path = 100 * np.exp(np.vstack([calm, calm[-1] + wild]))
    res = build_tsmom(_panel(path), cost_bps=0.0)
    early = np.abs(res.positions[300:480]).sum(axis=1).mean()
    late = np.abs(res.positions[700:]).sum(axis=1).mean()
    assert late < early, f"book did not shrink into the volatile regime: {late} vs {early}"


def test_costs_reduce_returns():
    rng = np.random.default_rng(2)
    path = 100 * np.exp(np.cumsum(rng.normal(0.0004, 0.012, (900, 4)), axis=0))
    free = build_tsmom(_panel(path), cost_bps=0.0)
    dear = build_tsmom(_panel(path), cost_bps=50.0)
    assert dear.returns.sum() < free.returns.sum()


def test_can_be_net_short_which_a_long_only_book_cannot():
    """The structural reason TSMOM might diversify an equity screen."""
    n = 900
    rng = np.random.default_rng(11)
    down = 100 * np.exp(np.cumsum(rng.normal(-0.0010, 0.008, (n, 3)), axis=0))
    res = build_tsmom(_panel(down), cost_bps=0.0)
    assert res.stats()["avg_net_exposure"] < 0
    assert res.stats()["share_short"] > res.stats()["share_long"]


def test_combine_reports_diversification_honestly():
    """A correlated 'portfolio' must not be able to present itself as
    diversified — the measured 18-strategy book combined to a Sharpe WORSE than
    its best member at median correlation 0.75."""
    rng = np.random.default_rng(3)
    base = rng.normal(0.0005, 0.01, 2000)
    clones = {f"c{i}": base + rng.normal(0, 0.001, 2000) for i in range(4)}
    _c, info = combine(clones)
    assert info["median_correlation"] > 0.9
    assert info["diversification_captured"] < 0.35, \
        "claimed real diversification from near-identical streams"

    independents = {f"i{i}": rng.normal(0.0005, 0.01, 2000) for i in range(4)}
    _c2, info2 = combine(independents)
    assert info2["median_correlation"] < 0.2
    assert info2["combined_sharpe"] > max(info2["components"].values()), \
        "uncorrelated streams failed to beat their best member"
    assert info2["diversification_captured"] > 0.5
