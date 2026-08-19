"""Flow-inertia estimators.

The load-bearing test here is `test_ema_smoothing_manufactures_persistence`:
it demonstrates on white noise that the source spec's smoothed rho estimator
reports the filter's own memory. That is the finding the whole Stage 1 result
turns on, so it is pinned rather than left as a note.
"""

import numpy as np
import pandas as pd
import pytest

from strategylab.data.prices import Panel
from strategylab.flow.panel import (build_dataset, fama_macbeth, month_end_indices,
                                    prepare_cross_sections, _newey_west_t)
from strategylab.flow.signals import compute_flow_signals, placebo_flow_signals
from strategylab.flow.stage1 import CAP_BANDS, check_inertia_exists, verdict


def white_noise_panel(n_days=1500, n_symbols=40, seed=0) -> Panel:
    """Prices with NO flow persistence by construction: iid returns."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2016-01-01", periods=n_days).values.astype("datetime64[D]")
    r = rng.normal(0.0002, 0.02, (n_days, n_symbols))
    close = 50.0 * np.exp(np.cumsum(r, axis=0))
    spread = np.abs(rng.normal(0, 0.01, (n_days, n_symbols)))
    high, low = close * (1 + spread), close * (1 - spread)
    open_ = np.clip(close * (1 + rng.normal(0, 0.005, close.shape)), low, high)
    vol = rng.lognormal(14.0, 0.5, close.shape)
    return Panel(dates=dates, symbols=[f"S{i:03d}" for i in range(n_symbols)],
                 open=open_, high=high, low=low, close=close, volume=vol)


@pytest.fixture(scope="module")
def noise_signals():
    return compute_flow_signals(white_noise_panel())


def test_ema_smoothing_manufactures_persistence(noise_signals):
    """THE finding: on iid returns, raw rho is ~0 but the spec's smoothed rho
    is strongly positive. Any inertia measured that way is the filter's."""
    rho = noise_signals.rho[np.isfinite(noise_signals.rho)]
    rho_ema = noise_signals.rho_ema[np.isfinite(noise_signals.rho_ema)]
    assert rho.size > 1000 and rho_ema.size > 1000

    assert abs(rho.mean()) < 0.10, (
        f"raw rho should be ~0 on white noise, got {rho.mean():+.3f}")
    assert rho_ema.mean() > 0.35, (
        f"the EMA variant should look persistent on noise, got {rho_ema.mean():+.3f}")
    assert rho_ema.mean() - rho.mean() > 0.30, "the artefact gap should be large"


def test_t0_flags_the_artefact(noise_signals):
    t0 = check_inertia_exists(noise_signals, unsigned_ar1=0.7)
    assert t0["available"]
    assert not t0["pass"], "T0 must fail when there is no inertia to measure"
    assert "smoothing_artefact_warning" in t0, "T0 must name the artefact"


def test_estimator_discriminates_real_persistence_from_noise(noise_signals):
    """Control: without this, T0 failing proves nothing — the estimator might
    simply never detect anything.

    It also measures the estimator's SENSITIVITY, which matters for reading the
    Stage 1 result: strongly autocorrelated daily returns (AR=0.55, far beyond
    anything real equities show) survive the sign-and-aggregate transform as
    only a modest rho. The proxy attenuates persistence heavily, so a null
    result is weaker evidence against the thesis than it first looks.
    """
    rng = np.random.default_rng(1)
    n, m = 1500, 40
    e = rng.normal(0, 0.02, (n, m))
    r = np.zeros_like(e)
    for t in range(1, n):
        r[t] = 0.55 * r[t - 1] + e[t]          # strongly persistent returns
    dates = pd.bdate_range("2016-01-01", periods=n).values.astype("datetime64[D]")
    close = 50.0 * np.exp(np.cumsum(r, axis=0))
    sp = np.abs(rng.normal(0, 0.01, (n, m)))
    panel = Panel(dates=dates, symbols=[f"S{i:03d}" for i in range(m)],
                  open=close, high=close * (1 + sp), low=close * (1 - sp),
                  close=close, volume=rng.lognormal(14.0, 0.5, (n, m)))
    sig = compute_flow_signals(panel)
    rho = sig.rho[np.isfinite(sig.rho)]
    rho_noise = noise_signals.rho[np.isfinite(noise_signals.rho)]

    assert rho.mean() > 0.05, (
        f"estimator failed to detect genuine persistence (rho={rho.mean():+.3f})")
    assert rho.mean() > rho_noise.mean() + 0.08, (
        "estimator does not discriminate persistence from noise: "
        f"{rho.mean():+.3f} vs {rho_noise.mean():+.3f}")
    # Attenuation: AR(0.55) in daily returns arrives as a much smaller rho.
    assert rho.mean() < 0.55, "unexpectedly lossless — check the transform"


def test_placebo_preserves_magnitude_and_destroys_direction():
    panel = white_noise_panel(seed=3)
    real = compute_flow_signals(panel)
    fake = placebo_flow_signals(panel, seed=3)
    assert np.allclose(np.abs(real.flow), np.abs(fake.flow), equal_nan=True), \
        "the placebo must change only the sign"
    same = (np.sign(real.flow) == np.sign(fake.flow))
    assert 0.3 < np.nanmean(same[np.isfinite(real.flow)]) < 0.7, \
        "signs should be roughly half flipped"


def test_forward_returns_never_use_past_information():
    """The panel's target must be strictly forward-looking."""
    panel = white_noise_panel(seed=5)
    sig = compute_flow_signals(panel)
    df = build_dataset(sig, horizon_days=21, min_names=10)
    assert not df.empty
    dates = pd.DatetimeIndex(sig.dates)
    ends = month_end_indices(sig.dates)
    d0 = dates[ends[3]]
    row = df[(df["date"] == d0)].iloc[0]
    j = sig.symbols.index(row["symbol"])
    t = int(np.flatnonzero(dates == d0)[0])
    expected = panel.close[t + 21, j] / panel.close[t, j] - 1.0
    assert abs(row["fwd_ret"] - expected) < 1e-6


def test_cross_sections_are_standardised_independently():
    panel = white_noise_panel(seed=7)
    sig = compute_flow_signals(panel)
    df = build_dataset(sig, min_names=10)
    prep = prepare_cross_sections(df, ["F", "sigma"], [("F", "sigma")])
    for _d, g in prep.groupby("date"):
        z = g["F_z"].dropna()
        if len(z) > 20:
            assert abs(z.mean()) < 1e-8 and abs(z.std(ddof=1) - 1.0) < 1e-6


def test_newey_west_widens_errors_for_autocorrelated_series():
    rng = np.random.default_rng(0)
    n = 300
    e = rng.normal(0, 1, n)
    x = np.zeros(n)
    for t in range(1, n):
        x[t] = 0.7 * x[t - 1] + e[t]
    _mu, se_nw, _t = _newey_west_t(x, lags=6)
    se_iid = x.std(ddof=1) / np.sqrt(n)
    assert se_nw > se_iid, "NW must not understate error on autocorrelated data"


def test_verdict_blocks_on_failed_precondition():
    """A failed T0 must sink the verdict even if every other check passes."""
    class M:
        r2_mean = 0.2
        coefficients = {"rho_x_F_z": {"coef": 0.01, "t": 5.0, "p": 1e-6}}
    models = {"M5_add_interaction": M(), "M2_momentum_controls": type("M2", (), {"r2_mean": 0.1})()}
    tests = {"T0": {"pass": False, "rho_mean": 0.0},
             "T1": {"pass": True}, "T4": {"pass": True}, "T5": {"pass": True}}
    v = verdict(models, tests, n_variants=11)
    assert v["proceed_to_stage_2"] is False
    assert "PRECONDITION FAILED" in v["statement"]


def test_cap_bands_are_disjoint_and_ordered():
    lo_mid, hi_mid = CAP_BANDS["mid_cap_target"]
    assert CAP_BANDS["small_cap_control"][1] == lo_mid
    assert CAP_BANDS["mega_cap_control"][0] == hi_mid
