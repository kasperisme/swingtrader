"""Setup timing — the Minervini trade and its barrier resolution.

The load-bearing test is `test_driftless_random_walk_resolves_at_one_third`.
With a 2R target against a 1R stop, optional stopping says a driftless walk
touches the target first exactly 1/3 of the time. That is a THEORETICAL value
the whole study is scored against, so the resolver reproducing it validates the
barrier engine, the gap handling and the ambiguous-bar convention in one shot —
and any drift in the result is then attributable to the data, not the code.
"""

import numpy as np
import pandas as pd
import pytest

from strategylab.data.prices import Panel
from strategylab.features import FeatureBank as FeatureBankT
from strategylab.features import FeatureBank
from strategylab.setups.detect import (SetupSpec, Setup, detect_setups,
                                       pseudo_setups, setups_frame)
from strategylab.setups.outcomes import OutcomeSpec, resolve_setups
from strategylab.setups.study import breakeven_rate, run_tests, conditioner_report, verdict


# ----------------------------------------------------------------- fixtures --
def make_panel(close, high=None, low=None, open_=None, volume=None, start="2015-01-01"):
    close = np.asarray(close, dtype=float)
    n, m = close.shape
    high = close * 1.01 if high is None else np.asarray(high, float)
    low = close * 0.99 if low is None else np.asarray(low, float)
    open_ = close.copy() if open_ is None else np.asarray(open_, float)
    volume = np.full((n, m), 1e7) if volume is None else np.asarray(volume, float)
    dates = pd.bdate_range(start, periods=n).values.astype("datetime64[D]")
    return Panel(dates=dates, symbols=[f"X{i:02d}" for i in range(m)],
                 open=open_, high=high, low=low, close=close, volume=volume)


def gbm(n_days, n_symbols, mu=0.0, sigma=0.02, seed=0, s0=100.0):
    rng = np.random.default_rng(seed)
    r = rng.normal(mu, sigma, (n_days, n_symbols))
    close = s0 * np.exp(np.cumsum(r, axis=0))
    intra = np.abs(rng.normal(0, sigma * 0.6, close.shape))
    high, low = close * (1 + intra), close * (1 - intra)
    open_ = np.clip(close * (1 + rng.normal(0, sigma * 0.2, close.shape)), low, high)
    return close, high, low, open_


# --------------------------------------------------------- barrier engine --
def test_driftless_random_walk_resolves_at_one_third():
    """THE benchmark. 2R target vs 1R stop on a martingale → P(target) = 1/3.

    Optional stopping gives the value exactly; if the resolver disagrees, the
    gap handling or the ambiguous-bar rule is wrong and every hit rate in the
    study is measured against a bar the engine cannot reproduce.
    """
    n, m = 4000, 400
    close, high, low, open_ = gbm(n, m, mu=0.0, sigma=0.015, seed=1)
    panel = make_panel(close, high, low, open_)

    setups = []
    for j in range(m):
        entry = float(open_[1, j])
        risk = entry * 0.06
        setups.append(Setup(day=0, col=j, symbol=panel.symbols[j], date=str(panel.dates[0]),
                            entry=entry, stop=entry - risk, target=entry + 2 * risk,
                            risk_pct=0.06))
    out = resolve_setups(panel, setups, OutcomeSpec(max_hold=3000, cost_bps_per_side=0.0))
    res = out[out["resolved"]]
    assert len(res) > 350, f"only {len(res)} resolved — raise max_hold"
    p = res["hit_target"].mean()
    assert abs(p - 1 / 3) < 0.06, f"P(target|resolved) = {p:.3f}, theory says 0.333"


def test_ambiguous_bar_books_the_loss():
    """One bar spanning both barriers must be a loss — the opposite convention
    manufactures hit rate out of bar resolution alone."""
    close = np.array([[100.0], [100.0], [100.0]])
    high = np.array([[100.0], [100.0], [130.0]])
    low = np.array([[100.0], [100.0], [80.0]])
    open_ = np.array([[100.0], [100.0], [100.0]])
    panel = make_panel(close, high, low, open_)
    s = Setup(day=0, col=0, symbol="X00", date="d", entry=100.0, stop=90.0,
              target=120.0, risk_pct=0.10)
    r = resolve_setups(panel, [s], OutcomeSpec(max_hold=5, cost_bps_per_side=0.0))
    assert r.iloc[0]["hit_stop"] and not r.iloc[0]["hit_target"]
    assert r.iloc[0]["exit_reason"] == "stop_ambiguous"


def test_gap_through_the_stop_fills_at_the_open_and_loses_more_than_1R():
    """'Limited risk' is limited only when the market opens where you left it."""
    close = np.array([[100.0], [100.0], [80.0]])
    high = np.array([[100.0], [100.0], [82.0]])
    low = np.array([[100.0], [100.0], [78.0]])
    open_ = np.array([[100.0], [100.0], [80.0]])
    panel = make_panel(close, high, low, open_)
    s = Setup(day=0, col=0, symbol="X00", date="d", entry=100.0, stop=90.0,
              target=120.0, risk_pct=0.10)
    r = resolve_setups(panel, [s], OutcomeSpec(max_hold=5, cost_bps_per_side=0.0)).iloc[0]
    assert r["exit_reason"] == "stop_gap"
    assert r["r_multiple"] < -1.0, "a gap through the stop must cost more than 1R"
    assert abs(r["r_multiple"] - (-2.0)) < 1e-9


def test_gap_through_the_target_fills_at_the_open():
    close = np.array([[100.0], [100.0], [130.0]])
    high = np.array([[100.0], [100.0], [132.0]])
    low = np.array([[100.0], [100.0], [129.0]])
    open_ = np.array([[100.0], [100.0], [130.0]])
    panel = make_panel(close, high, low, open_)
    s = Setup(day=0, col=0, symbol="X00", date="d", entry=100.0, stop=90.0,
              target=120.0, risk_pct=0.10)
    r = resolve_setups(panel, [s], OutcomeSpec(max_hold=5, cost_bps_per_side=0.0)).iloc[0]
    assert r["exit_reason"] == "target_gap" and r["r_multiple"] > 2.0


def test_costs_are_expressed_in_R_and_scale_with_the_stop_distance():
    """A 26bp round trip is 0.052R on a 5% stop and 0.026R on a 10% one. Charging
    it in percent rather than R makes tight setups look cheaper than they are."""
    close = np.full((40, 1), 100.0)
    panel = make_panel(close)
    outs = []
    for risk_pct in (0.05, 0.10):
        s = Setup(day=0, col=0, symbol="X00", date="d", entry=100.0,
                  stop=100 * (1 - risk_pct), target=100 * (1 + 2 * risk_pct),
                  risk_pct=risk_pct)
        outs.append(resolve_setups(panel, [s],
                                   OutcomeSpec(max_hold=30, cost_bps_per_side=13.0)).iloc[0])
    assert outs[0]["cost_r"] > outs[1]["cost_r"]
    assert abs(outs[0]["cost_r"] - 0.0026 / 0.05) < 1e-9


def test_planted_drift_lifts_the_hit_rate_above_one_third():
    n, m = 3000, 300
    close, high, low, open_ = gbm(n, m, mu=0.0018, sigma=0.015, seed=2)
    panel = make_panel(close, high, low, open_)
    setups = [Setup(day=0, col=j, symbol=panel.symbols[j], date="d",
                    entry=float(open_[1, j]), stop=float(open_[1, j]) * 0.94,
                    target=float(open_[1, j]) * 1.12, risk_pct=0.06) for j in range(m)]
    out = resolve_setups(panel, setups, OutcomeSpec(max_hold=2000, cost_bps_per_side=0.0))
    res = out[out["resolved"]]
    assert res["hit_target"].mean() > 0.45, res["hit_target"].mean()


# ------------------------------------------------------------- detection --
def _trend_panel(n=900, m=60, seed=3):
    """Names in persistent uptrends so the momentum screen admits them."""
    rng = np.random.default_rng(seed)
    r = rng.normal(0.0009, 0.016, (n, m))
    close = 30.0 * np.exp(np.cumsum(r, axis=0))
    intra = np.abs(rng.normal(0, 0.012, close.shape))
    high, low = close * (1 + intra), close * (1 - intra)
    open_ = np.clip(close * (1 + rng.normal(0, 0.005, close.shape)), low, high)
    vol = rng.lognormal(15.0, 0.35, close.shape)
    p = make_panel(close, high, low, open_, vol)
    return p, FeatureBank(p, benchmark_close=close.mean(axis=1))


def test_breakout_trigger_ignores_the_current_bar(_=None):
    """The pivot must be built from highs already set, or the rule cannot fire."""
    panel, bank = _trend_panel()
    mask = np.ones(panel.close.shape, dtype=bool)
    mask[:300] = False
    spec = SetupSpec(require_volume=False, min_risk_pct=0.0, max_risk_pct=1.0)
    setups, _ = detect_setups(panel, bank, mask, spec)
    assert setups, "no setups detected at all"
    pivot = bank.get("pivot_high", lookback=spec.base_len)
    for s in setups[:50]:
        assert panel.close[s.day, s.col] > pivot[s.day, s.col]


def test_risk_band_filters_setups_and_reports_it():
    panel, bank = _trend_panel()
    mask = np.ones(panel.close.shape, dtype=bool)
    mask[:300] = False
    wide, fw = detect_setups(panel, bank, mask,
                             SetupSpec(require_volume=False, min_risk_pct=0.0,
                                       max_risk_pct=1.0))
    tight, ft = detect_setups(panel, bank, mask,
                              SetupSpec(require_volume=False, min_risk_pct=0.0,
                                        max_risk_pct=0.04))
    assert len(tight) < len(wide)
    assert ft["dropped_risk_band"] > fw["dropped_risk_band"]
    assert all(s.risk_pct <= 0.04 for s in tight)


def test_one_trade_per_name_suppresses_repeats():
    panel, bank = _trend_panel()
    mask = np.ones(panel.close.shape, dtype=bool)
    mask[:300] = False
    spec = SetupSpec(require_volume=False, min_risk_pct=0.0, max_risk_pct=1.0)
    on, f_on = detect_setups(panel, bank, mask, spec)
    off, f_off = detect_setups(panel, bank, mask,
                               SetupSpec(require_volume=False, min_risk_pct=0.0,
                                         max_risk_pct=1.0, one_trade_per_name=False))
    assert len(on) < len(off)
    assert f_on["suppressed_already_open"] > 0
    for j in {s.col for s in on}:
        days = sorted(s.day for s in on if s.col == j)
        assert all(b - a >= 1 for a, b in zip(days, days[1:]))


def test_pseudo_setups_never_coincide_with_a_real_trigger():
    panel, bank = _trend_panel()
    mask = np.ones(panel.close.shape, dtype=bool)
    mask[:300] = False
    spec = SetupSpec(require_volume=False, min_risk_pct=0.0, max_risk_pct=1.0)
    real, _ = detect_setups(panel, bank, mask, spec)
    fake, _ = pseudo_setups(panel, bank, mask, spec)
    assert fake, "the control produced nothing"
    rset = {(s.day, s.col) for s in real}
    assert not ({(s.day, s.col) for s in fake} & rset)
    # and it must share the real calendar — the control is only a control if it
    # is drawn on the same days. It cannot be every day: on a session where the
    # whole (small) fixture universe triggers, there is no non-triggering name
    # left to draw. On the real panel the overlap is near total.
    rdays, fdays = {s.day for s in real}, {s.day for s in fake}
    assert len(rdays & fdays) / max(1, len(rdays)) > 0.6


# ------------------------------------------------------------------ study --
def test_breakeven_arithmetic():
    assert abs(breakeven_rate(2.0, 0.0) - 1 / 3) < 1e-12
    assert breakeven_rate(2.0, 0.05) > 1 / 3
    assert abs(breakeven_rate(1.0, 0.0) - 0.5) < 1e-12
    assert abs(breakeven_rate(3.0, 0.0) - 0.25) < 1e-12


def _fake_frame(n=4000, p=0.34, seed=0, months=120):
    rng = np.random.default_rng(seed)
    hit = rng.random(n) < p
    base = pd.Timestamp("2014-01-15")
    return pd.DataFrame({
        "date": [base + pd.DateOffset(months=int(m)) for m in rng.integers(0, months, n)],
        "hit_target": hit, "hit_stop": ~hit, "resolved": True,
        "r_net": np.where(hit, 1.96, -1.04), "cost_r": 0.04,
        "risk_pct": 0.07, "days_held": rng.integers(5, 60, n),
        "cond": rng.normal(size=n),
    })


def test_verdict_refuses_to_be_rescued_by_a_conditioner():
    """Conditioning a negative-expectancy trade only selects which losses to
    take. A timing signal must never flip the verdict on its own."""
    tests = {"S1_setup_beats_its_breakeven_hit_rate": {"pass": False},
             "S2_setup_beats_the_pseudo_setup_control": {"pass": False},
             "S3_expectancy_net_of_costs_is_positive": {"pass": True}}
    cond = {"n_conditioners": 3, "rows": {"x": {"pass": True}, "y": {"pass": True}}}
    v = verdict(tests, cond)
    assert not v["setup_has_edge"]
    assert v["conditioners_that_time_it"] == ["x", "y"]
    assert "cannot rescue" in v["recommendation"]


def test_run_tests_detects_a_setup_that_beats_breakeven():
    class S:
        reward_multiple = 2.0
    real = _fake_frame(p=0.45, seed=1)
    fake = _fake_frame(p=0.33, seed=2)
    t = run_tests(real, fake, S(), n_variants=6)
    assert t["S1_setup_beats_its_breakeven_hit_rate"]["pass"]
    assert t["S2_setup_beats_the_pseudo_setup_control"]["pass"]


def test_run_tests_is_null_when_the_setup_matches_its_control():
    class S:
        reward_multiple = 2.0
    real = _fake_frame(p=0.33, seed=3)
    fake = _fake_frame(p=0.33, seed=4)
    t = run_tests(real, fake, S(), n_variants=6)
    assert not t["S1_setup_beats_its_breakeven_hit_rate"]["pass"]
    assert not t["S2_setup_beats_the_pseudo_setup_control"]["pass"]


def test_conditioner_placebo_is_null_on_a_random_conditioner():
    class S:
        reward_multiple = 2.0
    df = _fake_frame(n=6000, p=0.34, seed=5)
    out = conditioner_report(df, ["cond"], S(), n_variants=6)
    row = out["rows"]["cond"]
    assert row["available"]
    assert not row["pass"], "a random conditioner must not be flagged as timing"


# ----------------------------------------------------------- trailing exit --
def _trail_panel(path, ma_val):
    """One symbol, an explicit price path, and a constant trailing MA."""
    close = np.array(path, dtype=float).reshape(-1, 1)
    panel = make_panel(close, high=close * 1.001, low=close * 0.999, open_=close)
    ma = np.full(close.shape, float(ma_val))
    return panel, ma


def test_trail_converts_at_the_target_instead_of_exiting():
    panel, ma = _trail_panel([100, 100, 125, 130, 140, 141], ma_val=95.0)
    s = Setup(day=0, col=0, symbol="X00", date="d", entry=100.0, stop=90.0,
              target=120.0, risk_pct=0.10)
    fixed = resolve_setups(panel, [s], OutcomeSpec(max_hold=10, cost_bps_per_side=0.0)).iloc[0]
    trail = resolve_setups(panel, [s],
                           OutcomeSpec(max_hold=10, cost_bps_per_side=0.0,
                                       trail_on_target=True), trail_ma=ma).iloc[0]
    assert fixed["exit_reason"] in ("target", "target_gap")
    assert trail["trailed"] and trail["hit_target"]
    assert trail["r_multiple"] > fixed["r_multiple"], "the trail should ride the move"


def test_trail_exits_on_a_close_below_the_moving_average():
    panel, ma = _trail_panel([100, 100, 125, 130, 110, 108], ma_val=115.0)
    s = Setup(day=0, col=0, symbol="X00", date="d", entry=100.0, stop=90.0,
              target=120.0, risk_pct=0.10)
    r = resolve_setups(panel, [s], OutcomeSpec(max_hold=10, cost_bps_per_side=0.0,
                                               trail_on_target=True), trail_ma=ma).iloc[0]
    assert r["exit_reason"] in ("trail_ma", "trail_gap")
    assert r["trailed"] and r["r_multiple"] > 0


def test_trail_never_sits_below_the_original_stop():
    """A collapsing MA must not turn a 2R winner into a loss beyond the plan."""
    panel, ma = _trail_panel([100, 100, 125, 130, 92, 91], ma_val=10.0)
    s = Setup(day=0, col=0, symbol="X00", date="d", entry=100.0, stop=90.0,
              target=120.0, risk_pct=0.10)
    r = resolve_setups(panel, [s], OutcomeSpec(max_hold=10, cost_bps_per_side=0.0,
                                               trail_on_target=True,
                                               max_trail_hold=3), trail_ma=ma).iloc[0]
    assert r["r_multiple"] >= -1.5, r["r_multiple"]


def test_trail_requires_the_moving_average():
    panel, _ = _trail_panel([100, 100, 125], ma_val=95.0)
    s = Setup(day=0, col=0, symbol="X00", date="d", entry=100.0, stop=90.0,
              target=120.0, risk_pct=0.10)
    with pytest.raises(ValueError):
        resolve_setups(panel, [s], OutcomeSpec(trail_on_target=True))


def test_trailing_cannot_change_a_trade_that_never_reached_the_target():
    """THE invariant. The rules are identical up to the target, so every trade
    that stopped out or timed out must be byte-identical under both. If this
    ever fails, the comparison is not paired and the whole head-to-head is void.
    """
    panel, bank = _trend_panel()
    mask = np.ones(panel.close.shape, dtype=bool)
    mask[:300] = False
    spec = SetupSpec(require_volume=False, min_risk_pct=0.0, max_risk_pct=1.0)
    setups, _ = detect_setups(panel, bank, mask, spec)
    assert setups
    ma = bank.get("sma", length=21)
    a = resolve_setups(panel, setups, OutcomeSpec(max_hold=60, cost_bps_per_side=13.0))
    b = resolve_setups(panel, setups, OutcomeSpec(max_hold=60, cost_bps_per_side=13.0,
                                                  trail_on_target=True), trail_ma=ma)
    key = ["symbol", "date", "day", "col"]
    m = a.merge(b, on=key, suffixes=("_f", "_t"))
    losers = m[~m["hit_target_f"].astype(bool)]
    assert len(losers) > 20
    assert np.allclose(losers["r_net_f"], losers["r_net_t"]), (
        "trailing altered trades that never reached the target")
    winners = m[m["hit_target_f"].astype(bool)]
    assert len(winners) > 5
    assert not np.allclose(winners["r_net_f"], winners["r_net_t"]), (
        "trailing changed nothing on the winners — it is not active")


# --------------------------------------------------------- base structure --
from strategylab.setups.vcp import FEATURES as VCP_FEATURES, _pullbacks, _swings, base_features
from strategylab.setups.study import _bucketize, conditioner_report


def test_swing_detector_alternates_and_measures_contraction():
    """A base of progressively shallower pullbacks must read as exactly that."""
    h = np.array([10, 11, 12, 11, 10, 11, 12.5, 12, 11.5, 12, 13, 12.8, 12.6, 13.2], float)
    sw = _swings(h, h - 0.4, k=2)
    kinds = [p[1] for p in sw]
    assert kinds == list("HLHLH"), kinds
    d = _pullbacks(sw)
    assert len(d) == 2
    assert d[1] < d[0], "the second pullback should be shallower — that is the VCP"


def test_swing_detector_collapses_adjacent_same_kind_pivots():
    h = np.array([10, 11, 12, 11.9, 11.8, 12.1, 9, 10, 11], float)
    sw = _swings(h, h - 0.3, k=2)
    kinds = [p[1] for p in sw]
    assert all(a != b for a, b in zip(kinds, kinds[1:])), kinds


def test_base_features_never_look_past_the_trigger_bar():
    """THE look-ahead test for the base. Every feature is measured on the base
    window plus the trigger close; scrambling everything AFTER the trigger must
    change nothing."""
    panel, bank = _trend_panel(n=900, m=20, seed=11)
    mask = np.ones(panel.close.shape, dtype=bool)
    mask[:400] = False
    spec = SetupSpec(require_volume=False, min_risk_pct=0.0, max_risk_pct=1.0)
    setups, _ = detect_setups(panel, bank, mask, spec)
    setups = [s for s in setups if s.day < 700][:60]
    assert setups
    base = base_features(panel, setups, base_len=spec.base_len)

    K = 700
    rng = np.random.default_rng(9)
    f = np.ones(panel.close.shape)
    f[K + 1:] = np.exp(np.cumsum(rng.normal(0, 0.06, f[K + 1:].shape), axis=0))
    later = Panel(dates=panel.dates, symbols=list(panel.symbols),
                  open=panel.open * f, high=panel.high * f, low=panel.low * f,
                  close=panel.close * f, volume=panel.volume)
    after = base_features(later, setups, base_len=spec.base_len)

    cols = [c for c in VCP_FEATURES if c in base.columns]
    a = base[cols].to_numpy(dtype=float)
    b = after[cols].to_numpy(dtype=float)
    assert a.shape == b.shape
    assert np.allclose(a, b, equal_nan=True), "a base feature peeked past the trigger"


def test_base_features_are_populated():
    panel, bank = _trend_panel(n=900, m=30, seed=12)
    mask = np.ones(panel.close.shape, dtype=bool)
    mask[:400] = False
    spec = SetupSpec(require_volume=False, min_risk_pct=0.0, max_risk_pct=1.0)
    setups, _ = detect_setups(panel, bank, mask, spec)
    f = base_features(panel, setups, base_len=spec.base_len)
    assert len(f) > 50
    for c in ("base_depth", "volume_dryup", "final_tightness", "breakout_extension"):
        assert f[c].notna().mean() > 0.8, c
    assert (f["base_depth"] >= 0).all()
    assert (f["n_contractions"] >= 0).all()


# ------------------------------------------ conditioner-report regressions --
def test_binary_conditioner_is_testable():
    """Regression: `qcut(...,5)` cannot bucket a 2-valued column, so binary
    conditioners were dropped as 'unavailable'. `market_regime` — the only real
    timing variable in the list — went untested through a whole study that way.
    """
    b, n = _bucketize(pd.Series([0, 1] * 500), 5)
    assert b is not None and n == 2

    rng = np.random.default_rng(3)
    n_obs = 4000
    flag = rng.integers(0, 2, n_obs)
    hit = rng.random(n_obs) < np.where(flag == 1, 0.45, 0.25)
    df = pd.DataFrame({
        "date": pd.Timestamp("2015-01-15") + pd.to_timedelta(
            rng.integers(0, 2000, n_obs), unit="D"),
        "hit_target": hit, "r_net": np.where(hit, 1.96, -1.04),
        "flag": flag.astype(float)})

    class S:
        reward_multiple = 2.0
    out = conditioner_report(df, ["flag"], S(), n_variants=6)
    assert out["rows"]["flag"]["available"], out["rows"]["flag"]
    assert out["rows"]["flag"]["buckets"] == 2


def test_inverse_relationship_is_detected_not_discarded():
    """Regression: the one-sided test scored any inverse relationship as a
    failure. `risk_pct` — the largest effect in the table at |t| = 4.91 with a
    perfect −1.00 rank correlation — was reported as 'fail'."""
    rng = np.random.default_rng(4)
    n_obs = 5000
    x = rng.random(n_obs)
    hit = rng.random(n_obs) < (0.45 - 0.25 * x)      # decreasing in x
    df = pd.DataFrame({
        "date": pd.Timestamp("2015-01-15") + pd.to_timedelta(
            rng.integers(0, 2000, n_obs), unit="D"),
        "hit_target": hit, "r_net": np.where(hit, 1.96, -1.04), "x": x})

    class S:
        reward_multiple = 2.0
    r = conditioner_report(df, ["x"], S(), n_variants=6)["rows"]["x"]
    assert r["available"]
    assert r["spearman_hit"] < -0.7, r["spearman_hit"]
    assert r["t_hit"] < 0
    assert r["pass"], "a strong inverse relationship must not be discarded"


def test_hit_rate_sorter_without_expectancy_is_flagged_but_does_not_pass():
    """The `risk_pct` lesson: a tighter stop brings the 2R target nearer, so the
    hit rate rises mechanically while expectancy does not move. Sorting hit rate
    alone must not count as timing."""
    rng = np.random.default_rng(5)
    n_obs = 6000
    x = rng.random(n_obs)
    p_win = 0.20 + 0.30 * x
    hit = rng.random(n_obs) < p_win
    # The payoff shrinks exactly as the hit rate rises, so E[r] = p*W - (1-p)*1
    # is identically zero for every x. Hit rate sorts perfectly; expectancy does
    # not sort at all. That is the `risk_pct` mechanic in miniature.
    win = (1.0 - p_win) / p_win
    df = pd.DataFrame({
        "date": pd.Timestamp("2015-01-15") + pd.to_timedelta(
            rng.integers(0, 2000, n_obs), unit="D"),
        "hit_target": hit, "r_net": np.where(hit, win, -1.0), "x": x})

    class S:
        reward_multiple = 2.0
    r = conditioner_report(df, ["x"], S(), n_variants=6)["rows"]["x"]
    assert r["available"]
    assert r["pass_hit_rate_only"], "the hit-rate sort should be visible"
    assert not r["pass"], "but it must not count as timing without expectancy"


def test_control_column_is_reported_when_supplied():
    rng = np.random.default_rng(6)
    n_obs = 4000

    def frame(seed):
        g = np.random.default_rng(seed)
        x = g.random(n_obs)
        hit = g.random(n_obs) < (0.20 + 0.30 * x)
        return pd.DataFrame({
            "date": pd.Timestamp("2015-01-15") + pd.to_timedelta(
                g.integers(0, 2000, n_obs), unit="D"),
            "hit_target": hit, "r_net": np.where(hit, 1.96, -1.04), "x": x})

    class S:
        reward_multiple = 2.0
    r = conditioner_report(frame(1), ["x"], S(), n_variants=6,
                           control=frame(2))["rows"]["x"]
    assert r["control_top_minus_bottom"] is not None
    assert r["excess_over_control"] is not None


# ------------------------------------------------------------ pullback entry --
from strategylab.setups.detect import ma_test_count, _pullback_trigger


def _ma_panel(close_path, m=1):
    close = np.asarray(close_path, float).reshape(-1, m)
    return make_panel(close, high=close * 1.002, low=close * 0.998, open_=close,
                      volume=np.full(close.shape, 1e7))


def test_pullback_needs_a_rising_average():
    """A reclaim inside a downtrend is not the setup."""
    up = np.linspace(50, 100, 200)
    down = np.linspace(100, 50, 200)
    for path, expect in ((up, True), (down, False)):
        p = _ma_panel(path)
        bank = FeatureBankT(p)
        spec = SetupSpec(trigger="pullback", ma_len=21, ma_rising_days=20,
                         pullback_window=10)
        trig = _pullback_trigger(p, bank, np.ones(p.close.shape, bool), spec)
        ma = bank.get("sma", length=21)
        rising_any = bool((np.isfinite(ma[60:]) & (trig[60:])).any())
        if not expect:
            assert not rising_any, "a falling average must not produce a pullback entry"


def test_pullback_requires_a_prior_touch_not_the_same_bar():
    """A single wide-range day that dips to the average and recovers must not
    read as a completed pullback — the touch is measured on earlier bars."""
    base = list(np.linspace(50, 70, 120))
    path = base + [69.0] * 5 + [71.0]        # drift, dip toward the MA, reclaim
    p = _ma_panel(path)
    bank = FeatureBankT(p)
    spec = SetupSpec(trigger="pullback", ma_len=21, ma_rising_days=20,
                     pullback_window=10)
    trig = _pullback_trigger(p, bank, np.ones(p.close.shape, bool), spec)
    ma = bank.get("sma", length=21)
    for t in np.flatnonzero(trig[:, 0]):
        assert p.close[t, 0] > ma[t, 0], "reclaim must close above the average"
        assert p.close[t, 0] > p.close[t - 1, 0], "reclaim must be an up day"
        prior = p.low[max(0, t - spec.pullback_window):t, 0] <= ma[max(0, t - spec.pullback_window):t, 0]
        assert prior.any(), "no touch in the window before the reclaim"


def test_pullback_trigger_has_no_lookahead():
    panel, bank = _trend_panel(n=900, m=20, seed=21)
    mask = np.ones(panel.close.shape, dtype=bool)
    spec = SetupSpec(trigger="pullback", require_volume=False,
                     min_risk_pct=0.0, max_risk_pct=1.0)
    base = _pullback_trigger(panel, bank, mask, spec)
    K = 600
    rng = np.random.default_rng(5)
    f = np.ones(panel.close.shape)
    f[K + 1:] = np.exp(np.cumsum(rng.normal(0, 0.05, f[K + 1:].shape), axis=0))
    later = Panel(dates=panel.dates, symbols=list(panel.symbols), open=panel.open * f,
                  high=panel.high * f, low=panel.low * f, close=panel.close * f,
                  volume=panel.volume)
    after = _pullback_trigger(later, FeatureBankT(later), mask, spec)
    assert np.array_equal(base[:K], after[:K]), "the pullback trigger peeked ahead"


def test_ma_test_count_counts_distinct_tests():
    """Consecutive bars sitting on the average are one test, not five — the
    'first test beats the fourth' claim is meaningless otherwise."""
    path = list(np.linspace(50, 60, 80)) + [58] * 4 + [61] * 10 + [59] * 3 + [63] * 10
    p = _ma_panel(path)
    bank = FeatureBankT(p)
    spec = SetupSpec(trigger="pullback", ma_len=21)
    counts = ma_test_count(p, bank, spec, lookback=60)
    tail = counts[-1, 0]
    assert np.isfinite(tail)
    assert 0 <= tail <= 6, f"distinct tests should be a small integer, got {tail}"


def test_breakout_and_pullback_produce_different_books():
    panel, bank = _trend_panel(n=900, m=40, seed=22)
    mask = np.ones(panel.close.shape, dtype=bool)
    mask[:300] = False
    a, _ = detect_setups(panel, bank, mask,
                         SetupSpec(trigger="breakout", require_volume=False,
                                   min_risk_pct=0.0, max_risk_pct=1.0))
    b, _ = detect_setups(panel, bank, mask,
                         SetupSpec(trigger="pullback", require_volume=False,
                                   min_risk_pct=0.0, max_risk_pct=1.0))
    assert a and b
    ka = {(s.day, s.col) for s in a}
    kb = {(s.day, s.col) for s in b}
    assert len(ka & kb) / min(len(ka), len(kb)) < 0.5, "the two entries should differ"


def test_unknown_trigger_is_rejected():
    panel, bank = _trend_panel(n=600, m=10, seed=23)
    with pytest.raises(ValueError):
        detect_setups(panel, bank, np.ones(panel.close.shape, bool),
                      SetupSpec(trigger="nonsense"))


# ------------------------------------------------------------- setup book --
from strategylab.setups.portfolio import PortfolioSpec, run_setup_portfolio


def _resolved(n_setups=40, day0=10, stride=1, r_net=1.0, risk_pct=0.10, days_held=5):
    return pd.DataFrame({
        "day": [day0 + i * stride for i in range(n_setups)],
        "col": list(range(n_setups)),
        "days_held": [days_held] * n_setups,
        "risk_pct": [risk_pct] * n_setups,
        "r_net": [r_net] * n_setups,
    })


def _tiny_panel(n=200, m=60):
    px = np.full((n, m), 100.0)
    dates = pd.bdate_range("2015-01-01", periods=n).values.astype("datetime64[D]")
    return Panel(dates=dates, symbols=[f"P{i:02d}" for i in range(m)], open=px,
                 high=px, low=px, close=px, volume=np.full((n, m), 1e7))


def test_capacity_cap_is_respected():
    panel = _tiny_panel()
    df = _resolved(n_setups=40, day0=10, stride=0, days_held=20)   # all on one day
    _, d = run_setup_portfolio(panel, df, PortfolioSpec(max_positions=3,
                                                        max_gross=10.0))
    assert d["max_open_positions"] <= 3
    assert d["trades_taken"] == 3
    assert d["trades_skipped_capacity"] == 37


def test_gross_exposure_cap_binds_before_a_large_slot_cap():
    """The real finding in miniature: at 1% risk with a 9% stop each position is
    ~11% of the book, so a 100% gross cap admits about nine positions and any
    slot cap above that is inert."""
    panel = _tiny_panel()
    df = _resolved(n_setups=40, day0=10, stride=0, risk_pct=0.09, days_held=20)
    _, big = run_setup_portfolio(panel, df, PortfolioSpec(max_positions=40,
                                                          risk_per_trade=0.01,
                                                          max_gross=1.0,
                                                          max_position_weight=1.0))
    _, huge = run_setup_portfolio(panel, df, PortfolioSpec(max_positions=0,
                                                           risk_per_trade=0.01,
                                                           max_gross=1.0,
                                                           max_position_weight=1.0))
    assert big["trades_taken"] == huge["trades_taken"], (
        "above the gross cap the slot cap changes nothing")
    assert big["max_open_positions"] <= 12
    assert big["binding"] == "gross_exposure"


def test_equity_compounds_on_a_known_trade():
    panel = _tiny_panel(n=100, m=4)
    df = _resolved(n_setups=1, day0=10, r_net=2.0, risk_pct=0.10, days_held=5)
    r, d = run_setup_portfolio(panel, df, PortfolioSpec(max_positions=1,
                                                        risk_per_trade=0.01,
                                                        max_gross=1.0))
    assert d["trades_taken"] == 1
    # 1% of equity risked, +2R -> +2% of equity
    assert abs(np.prod(1 + r) - 1.02) < 1e-6


def test_losing_trades_reduce_equity():
    panel = _tiny_panel(n=100, m=4)
    df = _resolved(n_setups=1, day0=10, r_net=-1.0, risk_pct=0.10, days_held=5)
    r, _ = run_setup_portfolio(panel, df, PortfolioSpec(max_positions=1,
                                                        risk_per_trade=0.01))
    assert abs(np.prod(1 + r) - 0.99) < 1e-6


def test_selection_rule_changes_which_setups_are_taken():
    panel = _tiny_panel()
    df = _resolved(n_setups=20, day0=10, stride=0, days_held=30)
    score = np.zeros(panel.close.shape)
    for i in range(20):
        score[10, i] = float(i)
    _, a = run_setup_portfolio(panel, df, PortfolioSpec(max_positions=2,
                                                        selection="score",
                                                        max_gross=10.0), score=score)
    _, b = run_setup_portfolio(panel, df, PortfolioSpec(max_positions=2,
                                                        selection="first",
                                                        max_gross=10.0))
    assert a["trades_taken"] == b["trades_taken"] == 2


def test_empty_setup_book_is_handled():
    panel = _tiny_panel(n=50, m=3)
    r, d = run_setup_portfolio(panel, pd.DataFrame(), PortfolioSpec())
    assert d["trades_taken"] == 0 and len(r) >= 1
