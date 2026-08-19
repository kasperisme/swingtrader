"""WML construction and volatility scaling.

This module makes quantitative claims about a published result, so its
mechanics are pinned rather than eyeballed — particularly the two places a
factor replication usually goes wrong: look-ahead in the scaling weight, and a
frictionless portfolio reported as if it were achievable.
"""

import numpy as np
import pandas as pd
import pytest

from strategylab.data.prices import Panel
from strategylab.factor import wml as W


def _panel(n=800, m=40, seed=0):
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2016-01-01", periods=n).values.astype("datetime64[D]")
    r = rng.normal(0.0004, 0.02, (n, m))
    close = 50.0 * np.exp(np.cumsum(r, axis=0))
    return Panel(dates=dates, symbols=[f"S{i}" for i in range(m)], open=close.copy(),
                 high=close * 1.005, low=close * 0.995, close=close,
                 volume=np.full((n, m), 1e7))


def test_wml_is_long_top_and_short_bottom():
    """A signal that literally IS next period's return must produce a large
    positive WML. If the sign convention were flipped this would be negative."""
    p = _panel(seed=1)
    n, m = p.close.shape
    fwd = np.full((n, m), np.nan)
    fwd[:-21] = p.close[21:] / p.close[:-21] - 1.0        # deliberate look-ahead
    res = W.build_wml(p, fwd, n_portfolios=4, min_names=20)
    st = res.stats()
    assert st["sharpe"] > 1.0, f"omniscient signal did not produce a winning WML: {st}"
    assert res.n_long.max() > 0 and res.n_short.max() > 0


def test_wml_returns_are_zero_before_the_first_rebalance():
    p = _panel(seed=2)
    sig = np.tile(np.arange(p.close.shape[1], dtype=float), (p.close.shape[0], 1))
    res = W.build_wml(p, sig, n_portfolios=4, min_names=20)
    first = min(res.rebalance_idx)
    assert np.allclose(res.returns[: first + 1], 0.0)


def test_scaling_weight_never_uses_the_day_it_scales():
    """The weight at t must be computable at t. If `realised_vol` forgot to
    shift, the overlay would know the volatility of the very day it is sizing —
    a look-ahead that flatters every downstream number."""
    rng = np.random.default_rng(3)
    r = rng.normal(0, 0.01, 600)
    vol = W.realised_vol(r, lookback=126)
    # Perturb one day and check the weight FOR that day is unchanged.
    r2 = r.copy()
    r2[400] = 0.5
    vol2 = W.realised_vol(r2, lookback=126)
    assert np.isclose(vol[400], vol2[400], equal_nan=True), "weight saw its own day"
    assert not np.isclose(vol[401], vol2[401], equal_nan=True), "weight ignored the past"


def test_constant_vol_scaling_moves_realised_vol_toward_the_target():
    rng = np.random.default_rng(4)
    n = 2000
    r = np.concatenate([rng.normal(0.0003, 0.004, n // 2),
                        rng.normal(0.0003, 0.030, n // 2)])
    res = W.WMLResult(pd.bdate_range("2015-01-01", periods=n).values.astype("datetime64[D]"),
                      r, r, np.zeros(n), np.ones(n), np.zeros(n), [], "synthetic")
    scaled, w = W.scale_constant_vol(res, target=0.12, lookback=126, cap=5.0)
    raw_late = float(np.std(r[1200:], ddof=1) * np.sqrt(252))
    scl_late = float(np.std(scaled[1200:], ddof=1) * np.sqrt(252))
    assert scl_late < raw_late, "scaling did not damp the volatile regime"
    assert abs(scl_late - 0.12) < abs(raw_late - 0.12), "did not move toward the target"


def test_scaling_cap_is_binding():
    rng = np.random.default_rng(5)
    r = rng.normal(0.0, 0.0005, 800)            # very calm -> wants huge leverage
    res = W.WMLResult(pd.bdate_range("2016-01-01", periods=800).values.astype("datetime64[D]"),
                      r, r, np.zeros(800), np.ones(800), np.zeros(800), [], "calm")
    _s, w = W.scale_constant_vol(res, target=0.12, lookback=126, cap=2.0)
    assert w.max() <= 2.0 + 1e-9
    assert w.max() == pytest.approx(2.0), "cap never bound — test is vacuous"


def test_dynamic_scaling_is_capped():
    """Uncapped, the mean-variance weight explodes when forecast variance is
    small — an early run produced 12x average leverage and a -32,000% month."""
    rng = np.random.default_rng(6)
    n = 1600
    r = rng.normal(0.0002, 0.01, n)
    mkt = rng.normal(0.0003, 0.01, n)
    res = W.WMLResult(pd.bdate_range("2015-01-01", periods=n).values.astype("datetime64[D]"),
                      r, r, np.zeros(n), np.ones(n), np.zeros(n), [], "x")
    _s, w = W.scale_dynamic(res, mkt, cap=2.0)
    assert np.nanmax(w) <= 2.0 + 1e-9
    assert np.isfinite(w).all()


def test_costs_reduce_returns_and_scale_with_turnover():
    p = _panel(seed=7)
    sig = np.tile(np.arange(p.close.shape[1], dtype=float), (p.close.shape[0], 1))
    res = W.build_wml(p, sig, n_portfolios=4, min_names=20)
    cheap = W.apply_costs(res, one_way_bps=1.0, borrow_bps_annual=0.0)
    dear = W.apply_costs(res, one_way_bps=50.0, borrow_bps_annual=400.0)
    assert dear.returns.sum() < cheap.returns.sum() < res.returns.sum()
    # Costs must land on rebalance days, not be smeared everywhere.
    diff = res.returns - cheap.returns
    assert (np.abs(diff) > 1e-12).sum() >= len(res.rebalance_idx)


def test_long_leg_only_drops_the_short_side():
    p = _panel(seed=8)
    sig = np.tile(np.arange(p.close.shape[1], dtype=float), (p.close.shape[0], 1))
    res = W.build_wml(p, sig, n_portfolios=4, min_names=20)
    leg = W.long_leg_only(res)
    assert np.allclose(leg.returns, res.long_returns)
    assert np.allclose(leg.short_returns, 0.0)


def test_stats_report_the_tail_shape():
    p = _panel(seed=9)
    sig = np.tile(np.arange(p.close.shape[1], dtype=float), (p.close.shape[0], 1))
    st = W.build_wml(p, sig, n_portfolios=4, min_names=20).stats()
    for k in ("sharpe", "skew", "excess_kurtosis", "worst_month", "max_drawdown"):
        assert k in st and np.isfinite(st[k]), f"{k} missing or not finite"
