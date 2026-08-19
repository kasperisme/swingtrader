import numpy as np

from strategylab.metrics import (deflated_sharpe, expected_max_sharpe, max_drawdown,
                                 probabilistic_sharpe,
                                 probability_of_backtest_overfitting, sharpe, tail_ratio)


def test_sharpe_matches_hand_calculation():
    rng = np.random.default_rng(0)
    r = rng.normal(0.001, 0.01, 2000)
    expected = r.mean() / r.std(ddof=1) * np.sqrt(252)
    assert abs(sharpe(r) - expected) < 1e-9


def test_sharpe_is_zero_on_degenerate_input():
    assert sharpe(np.zeros(500)) == 0.0
    assert sharpe(np.array([0.01, 0.02])) == 0.0


def test_max_drawdown():
    eq = np.array([100.0, 120.0, 60.0, 90.0])
    assert abs(max_drawdown(eq) - 0.5) < 1e-12


def test_expected_max_sharpe_grows_with_trials():
    a = expected_max_sharpe(10, 0.25)
    b = expected_max_sharpe(1000, 0.25)
    assert 0 < a < b


def test_deflated_sharpe_falls_as_the_search_widens():
    kw = dict(observed_sr=1.2, n_obs=2000, skew=-0.2, kurt=5.0, sr_variance=0.25)
    few = deflated_sharpe(n_trials=5, **kw)
    many = deflated_sharpe(n_trials=2000, **kw)
    assert few > many
    assert 0.0 <= many <= few <= 1.0


def test_psr_penalises_negative_skew_and_fat_tails():
    clean = probabilistic_sharpe(1.0, 1000, 0.0, 3.0)
    ugly = probabilistic_sharpe(1.0, 1000, -1.5, 12.0)
    assert clean > ugly


def test_pbo_is_near_half_for_pure_noise():
    rng = np.random.default_rng(3)
    R = rng.normal(0, 0.01, (1200, 20))     # 20 worthless configurations
    pbo = probability_of_backtest_overfitting(R, n_splits=8)
    assert 0.25 < pbo < 0.75


def test_pbo_is_low_when_one_config_is_genuinely_better():
    rng = np.random.default_rng(4)
    R = rng.normal(0, 0.01, (1200, 10))
    R[:, 0] += 0.0025                       # a real, persistent edge
    assert probability_of_backtest_overfitting(R, n_splits=8) < 0.25


def test_tail_ratio_flags_left_tails():
    rng = np.random.default_rng(5)
    sym = rng.normal(0, 0.01, 3000)
    assert 0.8 < tail_ratio(sym) < 1.25


def test_moments_degrade_gracefully_on_near_constant_returns():
    """Skew and kurtosis feed PSR and the deflated Sharpe. On a near-constant
    series they are not estimable, and emitting an unstable value there would
    silently corrupt the selection-bias correction."""
    from strategylab.backtest import BacktestResult
    from strategylab.metrics import summarize

    n = 300
    res = BacktestResult(
        dates=(np.datetime64("2020-01-01") + np.arange(n)).astype("datetime64[D]"),
        equity=np.full(n, 100_000.0), cash=np.full(n, 100_000.0),
        exposure=np.zeros(n), n_positions=np.zeros(n),
        returns=np.full(n, 1e-15), trades=[], initial_equity=100_000.0)
    m = summarize(res)
    assert np.isfinite(m["skew"]) and np.isfinite(m["kurtosis"])
    assert m["skew"] == 0.0 and m["kurtosis"] == 3.0
    assert 0.0 <= m["psr"] <= 1.0
