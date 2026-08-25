"""The momentum universe and the signal-stacking harness.

Two tests carry the design:

  * `test_incremental_ic_collapses_for_a_relabelled_control` plants a noisy copy
    of a control as a "new" signal. Its standalone IC looks just as good as the
    original's; its INCREMENTAL IC must collapse. That is the whole reason the
    incremental column exists — conditioning post-announcement drift on the
    trend template tripled its raw spread purely by re-encoding momentum, and
    only an incremental measure catches that class of mistake.

  * `test_universe_verify_catches_panel_drift` pins the failure that made two
    earlier campaigns incomparable: the cached symbol set grew underneath a
    `--limit` flag and silently changed the universe.
"""

import numpy as np
import pandas as pd
import pytest

from strategylab.data.prices import Panel
from strategylab.features import FeatureBank
from strategylab.momentum import ic as icmod
from strategylab.momentum.signals import CONTROLS, REGISTRY, compute_all
from strategylab.momentum.universe import (UniverseSpec, load_universe,
                                           pin_universe)


def big_panel(n_days=1400, n_symbols=60, seed=0):
    """Enough history for 200-day MAs and 52-week stats, enough names for a
    cross-section."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2015-01-01", periods=n_days).values.astype("datetime64[D]")
    mkt = rng.normal(0.0004, 0.009, n_days)
    drift = rng.normal(0.0003, 0.0006, n_symbols)
    r = np.outer(mkt, np.ones(n_symbols)) + rng.normal(drift, 0.018, (n_days, n_symbols))
    close = 40.0 * np.exp(np.cumsum(r, axis=0))
    spread = np.abs(rng.normal(0, 0.01, close.shape))
    high, low = close * (1 + spread), close * (1 - spread)
    open_ = np.clip(close * (1 + rng.normal(0, 0.004, close.shape)), low, high)
    vol = rng.lognormal(14.5, 0.4, close.shape)
    bench = 100.0 * np.exp(np.cumsum(mkt))
    return Panel(dates=dates, symbols=[f"N{i:03d}" for i in range(n_symbols)],
                 open=open_, high=high, low=low, close=close, volume=vol), bench


@pytest.fixture(scope="module")
def env():
    panel, bench = big_panel()
    return panel, FeatureBank(panel, benchmark_close=bench)


def _loose_spec(**kw):
    d = dict(min_price=0.0, min_adv_usd=0.0, min_bars=252, rs_min=30.0)
    d.update(kw)
    return UniverseSpec(**d)


# ---------------------------------------------------------------- universe --
def test_universe_is_point_in_time(env):
    """Scrambling prices after day K must not change eligibility before K.

    Note how the scramble is applied: one multiplicative factor per bar, to
    open/high/low/close ALIKE, and only after K. An earlier version of this test
    rebuilt high and low as close*1.01 for every row, which changed the inputs
    to the 52-week high everywhere and then reported the resulting mismatch as
    a look-ahead in the feature bank. The rolling helpers are backward-looking;
    the test was not.
    """
    panel, bank = env
    uni = pin_universe(panel, bank, _loose_spec())
    K = 900
    rng = np.random.default_rng(4)
    factor = np.ones(panel.close.shape)
    factor[K + 1:] = np.exp(np.cumsum(rng.normal(0, 0.05, factor[K + 1:].shape), axis=0))
    later = Panel(dates=panel.dates, symbols=list(panel.symbols),
                  open=panel.open * factor, high=panel.high * factor,
                  low=panel.low * factor, close=panel.close * factor,
                  volume=panel.volume)
    _, bench = big_panel()
    uni2 = pin_universe(later, FeatureBank(later, benchmark_close=bench), _loose_spec())
    assert np.array_equal(uni.mask[:K], uni2.mask[:K]), "the screen peeked at the future"


def test_universe_fingerprint_tracks_the_spec(env):
    panel, bank = env
    a = pin_universe(panel, bank, _loose_spec(rs_min=30.0))
    b = pin_universe(panel, bank, _loose_spec(rs_min=60.0))
    c = pin_universe(panel, bank, _loose_spec(rs_min=30.0))
    assert a.fingerprint == c.fingerprint, "same spec must fingerprint identically"
    assert a.fingerprint != b.fingerprint, "a different screen must fingerprint differently"
    assert b.mask.sum() <= a.mask.sum(), "a stricter RS bar cannot qualify more"


def test_universe_verify_catches_panel_drift(env):
    """THE reproducibility test. A pin is only meaningful against the panel it
    was built on; two campaigns became incomparable because the cached symbol
    set grew underneath a --limit flag."""
    panel, bank = env
    uni = pin_universe(panel, bank, _loose_spec())
    assert uni.verify(panel)["valid"]

    keep = list(range(panel.close.shape[1] - 5))
    smaller = Panel(dates=panel.dates, symbols=[panel.symbols[i] for i in keep],
                    open=panel.open[:, keep], high=panel.high[:, keep],
                    low=panel.low[:, keep], close=panel.close[:, keep],
                    volume=panel.volume[:, keep])
    rep = uni.verify(smaller)
    assert not rep["valid"] and not rep["symbols_match"]
    assert rep["pinned_symbols"] != rep["panel_symbols"]


def test_universe_round_trips_through_disk(env, tmp_path):
    panel, bank = env
    uni = pin_universe(panel, bank, _loose_spec())
    uni.save(tmp_path)
    manifest, mask = load_universe(tmp_path)
    assert manifest["fingerprint"] == uni.fingerprint
    assert np.array_equal(mask, uni.mask)


# ----------------------------------------------------------------- signals --
def test_every_registered_signal_computes(env):
    """A signal that raises is dropped from the report and reads as 'tested and
    found wanting'. `extension_from_sma50` asked for a feature name that did not
    exist and vanished from a whole IC table before anyone noticed."""
    panel, bank = env
    scores = compute_all(bank)
    missing = sorted(set(REGISTRY) - set(scores))
    assert not missing, f"signals failed to compute: {missing}"
    for name, v in scores.items():
        assert v.shape == panel.close.shape, name
        assert np.isfinite(v[400:]).mean() > 0.3, f"{name} is almost entirely NaN"


def test_controls_are_registered():
    assert set(CONTROLS) == {"mom_12_1", "rs_rank"}
    for c in CONTROLS:
        assert REGISTRY[c].is_control


def test_masking_confines_scores_to_the_universe(env):
    panel, bank = env
    uni = pin_universe(panel, bank, _loose_spec())
    scores = compute_all(bank, ["mom_12_1"], mask=uni.mask)
    assert not np.isfinite(scores["mom_12_1"][~uni.mask]).any()


# ---------------------------------------------------------------------- IC --
def test_forward_returns_are_filled_at_the_next_open(env):
    panel, _ = env
    fwd = icmod.forward_returns(panel, horizon=5)
    t = 300
    want = panel.open[t + 6, 0] / panel.open[t + 1, 0] - 1.0
    assert abs(fwd[t, 0] - want) < 1e-12
    # The tail must be NaN, not silently wrapped.
    assert not np.isfinite(fwd[-1]).any()


def _mask_for(panel, keep_from=300):
    m = np.zeros(panel.close.shape, dtype=bool)
    m[keep_from:-70] = True
    return m


def test_ic_detects_a_planted_signal(env):
    panel, _ = env
    mask = _mask_for(panel)
    fwd = icmod.forward_returns(panel, 21)
    rng = np.random.default_rng(5)
    score = np.where(np.isfinite(fwd), fwd + rng.normal(0, 0.25, fwd.shape), np.nan)
    r = icmod.ic_summary(icmod.daily_ic(score, fwd, mask), 21)
    assert r["available"] and r["ic_mean"] > 0.15, r
    assert r["t_newey_west"] > 4.0, r


def test_ic_is_zero_on_a_random_signal(env):
    panel, _ = env
    mask = _mask_for(panel)
    fwd = icmod.forward_returns(panel, 21)
    rng = np.random.default_rng(6)
    score = np.where(mask, rng.normal(size=fwd.shape), np.nan)
    r = icmod.ic_summary(icmod.daily_ic(score, fwd, mask), 21)
    assert abs(r["ic_mean"]) < 0.05, r
    assert abs(r["t_newey_west"]) < 3.0, r


def test_placebo_is_clean_across_seeds(env):
    """Regression: a ONE-seed placebo hit t = +2.68 on a real signal and read as
    a broken control. It was a draw. Several seeds is the honest check."""
    panel, bank = env
    mask = _mask_for(panel)
    fwd = icmod.forward_returns(panel, 21)
    score = compute_all(bank, ["mom_12_1"], mask=mask)["mom_12_1"]
    p = icmod.placebo_ic(score, fwd, mask, 21, seeds=5)
    assert p["available"] and p["seeds"] == 5
    assert abs(p["t_mean"]) < 2.0, p
    assert p["clean"], p


def test_newey_west_matters_on_overlapping_returns(env):
    """A 21-day forward return sampled daily autocorrelates, so a naive t-stat
    on the IC series overstates significance badly — 3.2x on the real panel.

    The score has to be PERSISTENT for this to bite, which is the realistic
    case: a signal that barely changes day to day produces an IC series driven
    by whatever the overlapping forward window does, and that is where the
    autocorrelation lives. A freshly-drawn score each day would not show it.
    """
    panel, _ = env
    mask = _mask_for(panel)
    fwd = icmod.forward_returns(panel, 21)
    rng = np.random.default_rng(7)
    per_name = rng.normal(size=(1, panel.close.shape[1]))
    score = np.where(mask, np.repeat(per_name, panel.close.shape[0], axis=0), np.nan)
    r = icmod.ic_summary(icmod.daily_ic(score, fwd, mask), 21)
    assert r["available"]
    assert abs(r["t_naive_overstated"]) > abs(r["t_newey_west"])
    assert r["overstatement_factor"] > 1.5, r


def test_incremental_ic_collapses_for_a_relabelled_control(env):
    """THE test. A noisy copy of a control looks as good as the original on a
    standalone IC and must add nothing incrementally."""
    panel, bank = env
    mask = _mask_for(panel)
    base = compute_all(bank, ["mom_12_1", "rs_rank"], mask=mask)
    rng = np.random.default_rng(8)
    clone = base["mom_12_1"] + rng.normal(0, 1e-6, base["mom_12_1"].shape)
    scores = dict(base)
    scores["mom_clone"] = np.where(mask, clone, np.nan)

    fwd = icmod.forward_returns(panel, 21)
    solo_orig = icmod.ic_summary(icmod.daily_ic(scores["mom_12_1"], fwd, mask), 21)
    solo_clone = icmod.ic_summary(icmod.daily_ic(scores["mom_clone"], fwd, mask), 21)
    assert abs(solo_orig["ic_mean"] - solo_clone["ic_mean"]) < 0.01, (
        "the clone should look identical standalone")

    inc = icmod.incremental_ic(scores, panel, mask, 21, CONTROLS)
    c = inc["coefficients"]["mom_clone"]
    assert c["available"]
    assert abs(c["t_newey_west"]) < 2.0, (
        f"a relabelled control must add nothing incrementally, got t="
        f"{c['t_newey_west']:.2f}")


def test_signal_correlations_are_symmetric_with_unit_diagonal(env):
    panel, bank = env
    mask = _mask_for(panel)
    scores = compute_all(bank, ["mom_12_1", "rs_rank", "reversal_5d"], mask=mask)
    c = icmod.signal_correlations(scores, mask, sample=120)
    assert list(c.index) == list(c.columns)
    assert np.allclose(np.diag(c.to_numpy()), 1.0, atol=0.05)
    assert np.allclose(c.to_numpy(), c.to_numpy().T, atol=1e-9, equal_nan=True)


# ------------------------------------------------------------ hold the screen --
from strategylab.momentum.hold import (HoldSpec, buy_and_hold, run_hold,
                                       stats_of, survivorship_report)


def _flat_panel(n=600, m=10, daily=0.001, start="2015-01-01"):
    """Every name compounds at exactly `daily` per session."""
    px = np.outer(np.cumprod(np.full(n, 1.0 + daily)), np.ones(m))
    dates = pd.bdate_range(start, periods=n).values.astype("datetime64[D]")
    return Panel(dates=dates, symbols=[f"H{i:02d}" for i in range(m)],
                 open=px, high=px, low=px, close=px, volume=np.full((n, m), 1e7))


def test_hold_reproduces_the_constituent_return_when_costs_are_zero():
    panel = _flat_panel(daily=0.001)
    mask = np.ones(panel.close.shape, dtype=bool)
    r, diag = run_hold(panel, mask, HoldSpec(cost_bps_per_side=0.0), start=5)
    # Nothing is held until the first month-end rebalance, so the opening
    # stretch is legitimately flat; the invested period must track exactly.
    assert np.allclose(r[:20], 0.0, atol=1e-12), "invested before the first rebalance"
    live = r[60:-1]
    assert np.allclose(live, 0.001, atol=1e-9), live[:5]
    assert diag["avg_exposure"] > 0.90


def test_costs_reduce_the_return_and_scale_with_turnover():
    panel = _flat_panel(daily=0.001, m=20)
    mask = np.zeros(panel.close.shape, dtype=bool)
    # Alternate which half of the universe qualifies each month → real turnover.
    months = pd.DatetimeIndex(panel.dates).to_period("M").astype(str)
    flip = pd.factorize(months)[0] % 2 == 0
    mask[flip, :10] = True
    mask[~flip, 10:] = True
    free = run_hold(panel, mask, HoldSpec(cost_bps_per_side=0.0), start=5)[0].sum()
    paid, diag = run_hold(panel, mask, HoldSpec(cost_bps_per_side=13.0), start=5)
    assert paid.sum() < free
    assert diag["annual_turnover"] > 1.0


def test_hold_does_not_use_the_signal_before_it_exists():
    """Weights set on the close of t are executed at the open of t+1, so
    scrambling prices after K cannot change returns earned before K."""
    panel = _flat_panel(n=600, m=8, daily=0.001)
    mask = np.ones(panel.close.shape, dtype=bool)
    base = run_hold(panel, mask, HoldSpec(cost_bps_per_side=0.0), start=5)[0]
    K = 400
    px = panel.close.copy()
    rng = np.random.default_rng(2)
    px[K + 1:] *= np.exp(np.cumsum(rng.normal(0, 0.05, px[K + 1:].shape), axis=0))
    later = Panel(dates=panel.dates, symbols=list(panel.symbols), open=px, high=px,
                  low=px, close=px, volume=panel.volume)
    after = run_hold(later, mask, HoldSpec(cost_bps_per_side=0.0), start=5)[0]
    assert np.allclose(base[:K - 1], after[:K - 1], atol=1e-12)


def test_breadth_scaling_cuts_exposure_when_the_screen_empties():
    """The screen's breadth collapses in bear markets — 2008 median 63 names
    against 206 overall. A rule that stays fully invested on one qualifying name
    discards exactly that information."""
    n, m = 900, 40
    panel = _flat_panel(n=n, m=m, daily=0.0)
    mask = np.zeros((n, m), dtype=bool)
    mask[:600, :] = True                       # broad
    mask[600:, :2] = True                      # collapsed to 2 names
    always = run_hold(panel, mask, HoldSpec(cost_bps_per_side=0.0,
                                            breadth_scaled=False), start=5)[1]
    scaled = run_hold(panel, mask, HoldSpec(cost_bps_per_side=0.0,
                                            breadth_scaled=True), start=5)[1]
    assert always["avg_exposure"] > 0.98
    assert scaled["avg_exposure"] < always["avg_exposure"] - 0.05


def test_buy_and_hold_matches_the_open_to_open_return():
    panel = _flat_panel(daily=0.002, m=3)
    r = buy_and_hold(panel, panel.symbols[0])
    assert np.allclose(r[:-1], 0.002, atol=1e-12)


def test_stats_of_recovers_known_quantities():
    r = np.full(252 * 4, 0.0005)
    s = stats_of(r)
    assert abs(s["cagr"] - ((1.0005 ** 252) - 1)) < 1e-6
    assert s["max_drawdown"] == 0.0
    assert s["years"] == pytest.approx(4.0, abs=0.01)

    down = np.concatenate([np.full(50, 0.01), np.full(50, -0.01)])
    assert stats_of(down)["max_drawdown"] < -0.3


def test_survivorship_report_sees_a_name_that_stops_trading():
    panel = _flat_panel(n=600, m=4)
    close = panel.close.copy()
    close[300:, 0] = np.nan
    dead = Panel(dates=panel.dates, symbols=list(panel.symbols), open=close,
                 high=close, low=close, close=close, volume=panel.volume)
    mask = np.ones(close.shape, dtype=bool)
    rep = survivorship_report(dead, mask)
    assert rep["of_which_stop_trading"] == 1
    assert rep["share_of_holding_days_in_names_that_stop"] > 0.2


# ------------------------------------------------------------- signal tilt --
from strategylab.momentum.hold import _tilt_weights


def test_tilt_weights_sum_to_one_and_default_to_flat():
    rng = np.random.default_rng(0)
    picks = np.arange(20)
    sig = rng.normal(size=50)
    for mode in ("none", "top_half", "rank_weight"):
        w = _tilt_weights(picks, sig, mode)
        assert w.shape == picks.shape
        assert abs(w.sum() - 1.0) < 1e-12
    assert np.allclose(_tilt_weights(picks, sig, "none"), 1 / 20)


def test_top_half_cuts_at_the_median_of_the_COVERED_names():
    """Regression. 62% of the universe has no news; giving those the middle rank
    and cutting at the overall median makes the median equal that rank, so
    `>= median` keeps everyone and the tilt is a no-op. 13 of 15 months came
    back as exactly zero difference, which read as 'the tilt does not help'."""
    picks = np.arange(10)
    sig = np.full(10, np.nan)
    sig[:4] = [1.0, 2.0, 3.0, 4.0]          # only 4 of 10 have a signal
    w = _tilt_weights(picks, sig, "top_half")
    assert w[0] == 0.0 and w[1] == 0.0, "the weak covered half must be dropped"
    assert w[2] > 0 and w[3] > 0
    assert all(w[4:] > 0), "names with no signal are neutral, not excluded"
    assert not np.allclose(w, 1 / 10), "the tilt must actually change the weights"


def test_tilt_is_flat_when_almost_nothing_is_covered():
    picks = np.arange(12)
    sig = np.full(12, np.nan)
    sig[0] = 5.0
    w = _tilt_weights(picks, sig, "top_half")
    assert np.allclose(w, 1 / 12), "too few covered names to tilt on"


def test_run_hold_reports_whether_the_tilt_actually_bit():
    """A tilt that never changes the weights produces a perfect null about the
    TILT, not the signal. `news_attention` is an integer count with heavy ties
    and its median split selected nothing on 93% of rebalances."""
    panel = _flat_panel(n=800, m=30, daily=0.0004)
    mask = np.ones(panel.close.shape, dtype=bool)
    rng = np.random.default_rng(3)

    real = np.tile(rng.normal(size=(1, 30)), (800, 1))
    _, d_real = run_hold(panel, mask, HoldSpec(cost_bps_per_side=0.0,
                                               tilt_mode="rank_weight"),
                         start=5, tilt_signal=real)
    assert d_real["tilt_rebalances"] > 5
    assert d_real["tilt_effective_share"] > 0.9

    ties = np.ones((800, 30))               # every name identical -> no tilt possible
    _, d_ties = run_hold(panel, mask, HoldSpec(cost_bps_per_side=0.0,
                                               tilt_mode="top_half"),
                         start=5, tilt_signal=ties)
    assert d_ties["tilt_effective_share"] == 0.0, (
        "a fully tied signal cannot tilt and must be reported as such")


def test_untilted_book_is_unchanged_by_a_signal_argument():
    panel = _flat_panel(n=400, m=12, daily=0.0005)
    mask = np.ones(panel.close.shape, dtype=bool)
    rng = np.random.default_rng(4)
    sig = rng.normal(size=panel.close.shape)
    a, _ = run_hold(panel, mask, HoldSpec(cost_bps_per_side=0.0), start=5)
    b, _ = run_hold(panel, mask, HoldSpec(cost_bps_per_side=0.0, tilt_mode="none"),
                    start=5, tilt_signal=sig)
    assert np.allclose(a, b)


# ----------------------------------------------------------- concentration --
from strategylab.momentum.hold import _select_top


def test_select_top_takes_the_best_by_score():
    picks = np.arange(10)
    sig = np.array([1., 9., 3., 8., 2., 7., 4., 6., 5., 0.])
    assert list(_select_top(picks, sig, np.array([]), HoldSpec(top_n=1))) == [1]
    assert sorted(_select_top(picks, sig, np.array([]), HoldSpec(top_n=3))) == [1, 3, 5]


def test_hysteresis_keeps_an_incumbent_inside_the_band():
    """Without it a one-stock book churns every time two names swap places, and
    a full round trip on 100% of capital costs 26bp a switch."""
    picks = np.arange(10)
    sig = np.array([1., 9., 3., 8., 2., 7., 4., 6., 5., 0.])
    # 3 is rank 2, inside top_n * 2 -> retained
    assert list(_select_top(picks, sig, np.array([3]), HoldSpec(top_n=1,
                                                               hysteresis_mult=2.0))) == [3]
    # 9 is the worst -> replaced by the leader
    assert list(_select_top(picks, sig, np.array([9]), HoldSpec(top_n=1,
                                                               hysteresis_mult=2.0))) == [1]
    # with no hysteresis the incumbent is dropped for the leader
    assert list(_select_top(picks, sig, np.array([3]), HoldSpec(top_n=1,
                                                               hysteresis_mult=1.0))) == [1]


def test_top_n_zero_holds_everything():
    picks = np.arange(8)
    sig = np.arange(8, dtype=float)
    assert list(_select_top(picks, sig, np.array([]), HoldSpec(top_n=0))) == list(picks)


def test_unscored_names_cannot_be_selected():
    """'Hold the best' needs a best; a name with no score is not a candidate."""
    picks = np.arange(6)
    sig = np.array([np.nan, np.nan, 5.0, 4.0, 3.0, np.nan])
    sel = _select_top(picks, sig, np.array([]), HoldSpec(top_n=2))
    assert set(sel) == {2, 3}


def test_concentration_raises_volatility_without_a_skilful_score():
    """The measured result, in miniature: with a score that carries no
    information, concentrating adds variance and nothing else."""
    rng = np.random.default_rng(11)
    n, m = 900, 40
    r = rng.normal(0.0004, 0.02, (n, m))
    px = 50.0 * np.exp(np.cumsum(r, axis=0))
    dates = pd.bdate_range("2015-01-01", periods=n).values.astype("datetime64[D]")
    panel = Panel(dates=dates, symbols=[f"C{i:02d}" for i in range(m)], open=px,
                  high=px, low=px, close=px, volume=np.full((n, m), 1e7))
    mask = np.ones((n, m), dtype=bool)
    score = rng.normal(size=(n, m))          # pure noise, no skill

    conc, _ = run_hold(panel, mask, HoldSpec(cost_bps_per_side=0.0, top_n=2),
                       start=5, score=score)
    wide, _ = run_hold(panel, mask, HoldSpec(cost_bps_per_side=0.0), start=5)
    assert conc[60:].std() > 2.0 * wide[60:].std(), (
        "concentration must show up as variance when the score is noise")


def test_daily_rebalance_reconsiders_every_session():
    panel = _flat_panel(n=300, m=10, daily=0.0)
    from strategylab.momentum.hold import _rebalance_days
    assert len(_rebalance_days(panel.dates, "D")) == len(panel.dates)
    assert len(_rebalance_days(panel.dates, "M")) < 20


def test_run_hold_reports_switches_and_holding_period():
    """The book must be able to show what it DID, not what it was configured to
    do — 'hold one name' reads as buy-and-hold until the switch count says
    otherwise."""
    rng = np.random.default_rng(21)
    n, m = 900, 25
    px = 50.0 * np.exp(np.cumsum(rng.normal(0.0004, 0.02, (n, m)), axis=0))
    dates = pd.bdate_range("2015-01-01", periods=n).values.astype("datetime64[D]")
    panel = Panel(dates=dates, symbols=[f"S{i:02d}" for i in range(m)], open=px,
                  high=px, low=px, close=px, volume=np.full((n, m), 1e7))
    mask = np.ones((n, m), dtype=bool)
    score = rng.normal(size=(n, m))

    _, d = run_hold(panel, mask, HoldSpec(cost_bps_per_side=0.0, top_n=1,
                                          rebalance="M"), start=5, score=score)
    assert d["switches"] > 5, "a top-1 book on a changing score must rotate"
    assert d["median_hold_days"] is not None
    assert d["holdings_log"] and len(d["holdings_log"][0][1]) == 1


def test_looking_more_often_switches_more_and_costs_more():
    rng = np.random.default_rng(22)
    n, m = 900, 25
    px = 50.0 * np.exp(np.cumsum(rng.normal(0.0004, 0.02, (n, m)), axis=0))
    dates = pd.bdate_range("2015-01-01", periods=n).values.astype("datetime64[D]")
    panel = Panel(dates=dates, symbols=[f"S{i:02d}" for i in range(m)], open=px,
                  high=px, low=px, close=px, volume=np.full((n, m), 1e7))
    mask = np.ones((n, m), dtype=bool)
    score = rng.normal(size=(n, m))

    _, daily = run_hold(panel, mask, HoldSpec(cost_bps_per_side=13.0, top_n=1,
                                              rebalance="D"), start=5, score=score)
    _, monthly = run_hold(panel, mask, HoldSpec(cost_bps_per_side=13.0, top_n=1,
                                                rebalance="M"), start=5, score=score)
    assert daily["switches_per_year"] > monthly["switches_per_year"]
    assert daily["annual_turnover"] > monthly["annual_turnover"]


def test_hysteresis_reduces_switching():
    rng = np.random.default_rng(23)
    n, m = 900, 25
    px = 50.0 * np.exp(np.cumsum(rng.normal(0.0004, 0.02, (n, m)), axis=0))
    dates = pd.bdate_range("2015-01-01", periods=n).values.astype("datetime64[D]")
    panel = Panel(dates=dates, symbols=[f"S{i:02d}" for i in range(m)], open=px,
                  high=px, low=px, close=px, volume=np.full((n, m), 1e7))
    mask = np.ones((n, m), dtype=bool)
    score = rng.normal(size=(n, m))
    _, tight = run_hold(panel, mask, HoldSpec(cost_bps_per_side=0.0, top_n=1,
                                              rebalance="D", hysteresis_mult=1.0),
                        start=5, score=score)
    _, loose = run_hold(panel, mask, HoldSpec(cost_bps_per_side=0.0, top_n=1,
                                              rebalance="D", hysteresis_mult=5.0),
                        start=5, score=score)
    assert loose["switches"] < tight["switches"]
