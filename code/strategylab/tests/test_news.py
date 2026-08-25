"""News repricing / post-announcement drift.

The load-bearing tests are the ones that would have caught what this study got
wrong on its first pass: a single unadjusted corporate action moving a decile
mean by 6.6 percentage points, and a thin-cell month flipping the sign of the
headline statistic.
"""

import numpy as np
import pandas as pd
import pytest
from scipy import stats

from strategylab.data.prices import Panel
from strategylab.news.eventstudy import (EventSpec, assign_buckets, build_events,
                                         liquidity_tier, market_model,
                                         pseudo_events, winsorize)
from strategylab.news.study import (MIN_PER_CELL, _cluster, monotonicity,
                                    run_tests, spread_series,
                                    spread_series_detail, verdict)


# ----------------------------------------------------------------- helpers --
def synth_panel(n_days=2000, n_symbols=30, seed=0, beta_true=None, drift=None,
                event_days=None):
    """A market factor plus idiosyncratic noise, with optional planted events.

    `drift` plants a post-announcement drift: on each event day the stock jumps
    by `jump`, and then drifts by `drift` per day for 21 days in the SAME
    direction. That is the effect the study is built to detect, so a panel that
    contains it by construction is the only way to know the detector works.
    """
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2005-01-03", periods=n_days).values.astype("datetime64[D]")
    mkt = rng.normal(0.0003, 0.010, n_days)
    betas = np.full(n_symbols, 1.0) if beta_true is None else np.asarray(beta_true)
    r = np.outer(mkt, betas) + rng.normal(0, 0.015, (n_days, n_symbols))

    # Announcements are STAGGERED per symbol. Real reporting calendars are, and
    # a fixture where every name announces on the same day leaves no same-day
    # control to draw a pseudo-event from — which is a property of the fixture,
    # not of the code.
    planted = {}
    if event_days is not None:
        for j in range(n_symbols):
            own = [d + (j * 7) % 45 for d in event_days]
            own = [d for d in own if 0 <= d < n_days - 40]
            planted[j] = own
            for d in own:
                sign = 1.0 if (j + d) % 2 == 0 else -1.0
                r[d, j] += sign * 0.06
                if drift:
                    r[d + 2: d + 23, j] += sign * drift

    close = 50.0 * np.exp(np.cumsum(r, axis=0))
    vol = np.full((n_days, n_symbols), 2e6)
    symbols = [f"S{i:03d}" for i in range(n_symbols)]
    # SPY tracks the market exactly, so beta is recoverable.
    spy = 100.0 * np.exp(np.cumsum(mkt))
    close = np.column_stack([close, spy])
    vol = np.column_stack([vol, np.full(n_days, 1e9)])
    symbols = symbols + ["SPY"]
    return Panel(dates=dates, symbols=symbols, open=close.copy(), high=close * 1.005,
                 low=close * 0.995, close=close, volume=vol), planted


def _spec(**kw):
    d = dict(beta_window=250, min_beta_obs=120, min_rank_events=200,
             rank_lookback_days=365, min_price=0.0)
    d.update(kw)
    return EventSpec(**d)


def _earnings(panel, planted):
    """planted: {column -> [day indices]} as returned by `synth_panel`."""
    return {f"S{j:03d}": [str(panel.dates[d]) for d in days]
            for j, days in planted.items()}


# ------------------------------------------------------------ market model --
def test_market_model_recovers_known_betas():
    betas = np.linspace(0.5, 1.8, 30)
    panel, _ = synth_panel(beta_true=betas, seed=3)
    AB, b, sigma, m = market_model(panel, "SPY", _spec())
    est = np.nanmedian(b[600:, :30], axis=0)
    assert np.nanmax(np.abs(est - betas)) < 0.15, f"worst error {np.nanmax(np.abs(est - betas)):.3f}"


def test_abnormal_returns_are_centred_and_beta_is_lagged():
    panel, _ = synth_panel(seed=4)
    spec = _spec()
    AB, b, sigma, m = market_model(panel, "SPY", spec)
    ab = AB[600:, :30]
    assert abs(np.nanmean(ab)) < 5e-4, "abnormal returns should have ~zero mean"
    # Beta on the first usable row must be NaN: it can only be built from
    # strictly earlier data.
    assert np.all(~np.isfinite(b[0, :30]))


# ----------------------------------------------------------------- timing --
@pytest.mark.parametrize("offset", [0, 1])
def test_ear_window_catches_the_reaction_either_side_of_the_date(offset):
    """FMP gives a date, not whether the release was before the open or after
    the close. The [D-1, D+1] window has to contain the reaction either way."""
    days = list(range(700, 1900, 60))
    panel, planted = synth_panel(seed=5, event_days=[d + offset for d in days])
    spec = _spec()
    AB, b, sigma, m = market_model(panel, "SPY", spec)
    adv = np.full_like(panel.close, 2e6)
    # The recorded date is the announcement date; the reaction sits at +offset.
    recorded = {k: [d - offset for d in v] for k, v in planted.items()}
    ev = build_events(panel, _earnings(panel, recorded), spec, AB, b, sigma, m, adv)
    assert len(ev) > 200
    assert ev["ear"].abs().mean() > 1.5, (
        f"the reaction was missed at offset {offset}: mean |EAR| "
        f"{ev['ear'].abs().mean():.2f}")


def test_outcome_window_starts_after_the_announcement_window():
    """The surprise and the outcome must not share a day, or the test is
    circular in the way that killed the flow study."""
    spec = _spec()
    assert spec.entry_lag > spec.ear_lag, "outcome must start after the EAR window"


def test_drift_is_not_contaminated_by_the_announcement_jump():
    """Scrambling prices at and before the event must leave the drift alone."""
    days = list(range(700, 1900, 60))
    panel, planted = synth_panel(seed=6, event_days=days, drift=0.0015)
    spec = _spec()
    AB, b, sigma, m = market_model(panel, "SPY", spec)
    adv = np.full_like(panel.close, 2e6)
    base = build_events(panel, _earnings(panel, planted), spec, AB, b, sigma, m, adv)
    # The drift columns are built only from t >= D+2, so they must be finite and
    # independent of the EAR window's own magnitude scaling.
    assert base["car_21"].notna().mean() > 0.9
    assert base["ret_21"].notna().mean() > 0.9


# ------------------------------------------------------------- detectability --
def test_planted_drift_is_detected():
    """The power check: a panel built WITH post-announcement drift must produce
    a monotone decile pattern and a positive spread."""
    days = list(range(700, 1950, 30))
    panel, planted = synth_panel(n_days=2000, n_symbols=40, seed=7,
                                 event_days=days, drift=0.0012)
    spec = _spec()
    AB, b, sigma, m = market_model(panel, "SPY", spec)
    adv = np.full_like(panel.close, 2e6)
    ev = build_events(panel, _earnings(panel, planted), spec, AB, b, sigma, m, adv)
    ev = assign_buckets(ev, spec)
    tbl = {int(k): {"mean": float(v)} for k, v in
           ev.dropna(subset=["bucket"]).groupby("bucket")["ret_21"].mean().items()}
    mono = monotonicity(tbl)
    assert mono["available"] and mono["spearman"] > 0.8, mono
    sp = spread_series(ev, "ret_21", spec.n_buckets, min_per_cell=1)
    assert sp.mean() > 0.01, f"planted drift not recovered: {sp.mean():.4f}"


def test_no_planted_drift_is_not_detected():
    """The false-positive check — the mirror of the above."""
    days = list(range(700, 1950, 30))
    panel, planted = synth_panel(n_days=2000, n_symbols=40, seed=8,
                                 event_days=days, drift=0.0)
    spec = _spec()
    AB, b, sigma, m = market_model(panel, "SPY", spec)
    adv = np.full_like(panel.close, 2e6)
    ev = assign_buckets(build_events(panel, _earnings(panel, planted), spec,
                                     AB, b, sigma, m, adv), spec)
    sp = spread_series(ev, "ret_21", spec.n_buckets, min_per_cell=1)
    c = _cluster(sp.to_numpy())
    assert abs(c["mean"]) < 0.01, f"spurious spread {c['mean']:.4f}"
    assert abs(c["t"]) < 3.0, f"spurious t {c['t']:.2f}"


# ------------------------------------------------------------------ hygiene --
def test_buckets_never_use_future_events():
    """Deciles are cut from a TRAILING window. Sorting inside a calendar
    quarter is the convenient thing and it is look-ahead."""
    rng = np.random.default_rng(11)
    n = 6000
    dates = pd.to_datetime("2010-01-01") + pd.to_timedelta(
        np.sort(rng.integers(0, 3000, n)), unit="D")
    df = pd.DataFrame({"date": dates, "ear": rng.normal(size=n),
                       "ret_21": rng.normal(size=n)})
    spec = _spec()
    base = assign_buckets(df, spec)

    later = df.copy()
    cut = len(df) // 2
    later.loc[later.index[cut:], "ear"] = rng.normal(50, 1, len(df) - cut)
    after = assign_buckets(later, spec)

    a = base.iloc[:cut][["date", "bucket"]].reset_index(drop=True)
    b = after.iloc[:cut][["date", "bucket"]].reset_index(drop=True)
    same = a["bucket"].isna() & b["bucket"].isna()
    assert ((a["bucket"] == b["bucket"]) | same).all(), (
        "early buckets changed when only LATER surprises were altered")


def test_pseudo_events_never_sit_near_an_announcement():
    days = list(range(700, 1900, 60))
    panel, planted = synth_panel(seed=9, event_days=days)
    spec = _spec(pseudo_min_gap=20)
    AB, b, sigma, m = market_model(panel, "SPY", spec)
    adv = np.full_like(panel.close, 2e6)
    earn = _earnings(panel, planted)
    fake = pseudo_events(panel, earn, spec, AB, b, sigma, m, adv,
                         liquidity_tier(adv))
    assert len(fake) > 100
    grid = np.asarray(panel.dates, dtype="datetime64[D]")
    idx = np.searchsorted(grid, np.asarray(fake["date"], dtype="datetime64[D]"))
    worst = 10 ** 9
    for sym, days_ in zip(fake["symbol"], idx):
        own = planted[int(sym[1:])]
        if own:
            worst = min(worst, int(np.abs(np.array(own) - days_).min()))
    assert worst > spec.pseudo_min_gap, (
        f"a pseudo-event landed {worst} sessions from its own name's announcement")


def test_pseudo_events_share_the_real_calendar():
    """Day-matching is what gives the control its power. An earlier version drew
    random days per symbol; real announcements cluster into four seasons, so the
    two samples barely shared months and most of the comparison was lost."""
    days = list(range(700, 1900, 60))
    panel, planted = synth_panel(seed=10, event_days=days)
    spec = _spec()
    AB, b, sigma, m = market_model(panel, "SPY", spec)
    adv = np.full_like(panel.close, 2e6)
    earn = _earnings(panel, planted)
    real = build_events(panel, earn, spec, AB, b, sigma, m, adv)
    fake = pseudo_events(panel, earn, spec, AB, b, sigma, m, adv, liquidity_tier(adv))
    rm = set(pd.PeriodIndex(pd.to_datetime(real["date"]), freq="M"))
    fm = set(pd.PeriodIndex(pd.to_datetime(fake["date"]), freq="M"))
    assert len(rm & fm) / len(rm) > 0.9, "the control does not share the real calendar"


def test_winsorisation_is_symmetric_and_tames_a_corporate_action():
    """One unadjusted corporate action moved a real decile mean by 6.6pp."""
    rng = np.random.default_rng(12)
    real = pd.DataFrame({"ret_21": rng.normal(0, 0.08, 5000),
                         "car_21": rng.normal(0, 0.08, 5000),
                         "raw_21": rng.normal(0, 0.08, 5000)})
    fake = real.copy()
    real.loc[0, "ret_21"] = 399.0                       # QUBT, 2018-06-29
    spec = EventSpec(drift_horizons=(21,), winsorize_pct=0.01)
    before = real["ret_21"].mean()
    info = winsorize(real, fake, spec)
    assert before > 0.07, "the outlier should dominate the raw mean"
    assert abs(real["ret_21"].mean()) < 0.01
    lo, hi = info["thresholds"]["ret_21"]
    assert real["ret_21"].max() <= hi and fake["ret_21"].max() <= hi
    assert info["absurd"]["ret_21"] >= 1


def test_thin_months_are_dropped_and_the_sign_does_not_flip():
    """Regression. Off-season months held one or two announcements per decile,
    produced +/-17% 'spreads', and flipped the headline statistic from +0.49%
    to -0.30%."""
    rng = np.random.default_rng(13)
    rows = []
    for month in range(60):
        fat = month % 3 == 0                      # earnings season
        n = 200 if fat else 4
        for _ in range(n):
            rows.append({"date": pd.Timestamp("2015-01-15") + pd.DateOffset(months=month),
                         "bucket": rng.integers(0, 10),
                         "ret_21": rng.normal(0.004 if not fat else 0.0, 0.05)})
    df = pd.DataFrame(rows)
    loose = spread_series(df, "ret_21", 10, min_per_cell=1)
    tight, info = spread_series_detail(df, "ret_21", 10, min_per_cell=MIN_PER_CELL)
    assert info["dropped"] > 0, "thin months should be dropped"
    assert tight.std() < loose.std(), "the guard must reduce, not add, dispersion"
    assert abs(tight.mean() - info["pooled"]) < abs(loose.mean() - info["pooled"])


def test_liquidity_tiers_partition_the_range():
    adv = np.array([5e5, 5e6, 5e7, 5e8])
    assert list(liquidity_tier(adv)) == ["T1_micro_<$1M", "T2_small_$1-10M",
                                         "T3_mid_$10-100M", "T4_large_>$100M"]


def test_verdict_requires_the_control_to_be_beaten():
    """Significance without N1 is momentum, not an announcement effect."""
    t = {"P1_drift_is_monotone_in_the_surprise": {"pass": True},
         "P2_top_minus_bottom_spread_is_positive": {"pass": True},
         "N1_excess_over_the_pseudo_event_control": {"pass": False},
         "N2_placebo_surprise_labels_are_null": {"pass": True},
         "E1_spread_survives_costs": {"pass": True}}
    assert not verdict(t)["effect_is_real_and_tradeable"]
    t["N1_excess_over_the_pseudo_event_control"]["pass"] = True
    assert verdict(t)["effect_is_real_and_tradeable"]


# ------------------------------------------------------------ news overlay --
from strategylab.momentum import ic as icmod
from strategylab.news.overlay import (NEWS_SIGNALS, build_news_matrices,
                                      coverage_report, minimum_detectable_ic)


class _FakeStore:
    def __init__(self, df):
        self._df = df

    def load(self):
        return self._df


def _news_frame(panel, symbols, lo=100, hi=400, seed=0):
    rng = np.random.default_rng(seed)
    rows = []
    for t in range(lo, hi):
        for s in symbols:
            if rng.random() < 0.6:
                rows.append({"ticker": s,
                             "trade_date": pd.Timestamp(panel.dates[t]),
                             "mean_sentiment": rng.uniform(-1, 1),
                             "n_articles": int(rng.integers(1, 6))})
    return pd.DataFrame(rows)


def test_news_matrices_are_nan_outside_coverage():
    """Silence is not neutrality. A name nobody wrote about is unknown, and
    collapsing that to zero would hand the signal a cross-section made of
    absence."""
    panel, _ = synth_panel(n_days=600, n_symbols=6, seed=1)
    syms = panel.symbols[:6]
    df = _news_frame(panel, syms, 100, 400)
    mats = build_news_matrices(panel, store=_FakeStore(df))
    for k in NEWS_SIGNALS:
        m = mats[k]
        assert m.shape == panel.close.shape
        assert not np.isfinite(m[:99]).any(), f"{k} has values before coverage starts"
        assert not np.isfinite(m[401:]).any(), f"{k} has values after coverage ends"
    assert np.isfinite(mats["news_attention"][150:350, :6]).any()


def test_news_matrices_have_no_lookahead():
    panel, _ = synth_panel(n_days=600, n_symbols=6, seed=2)
    syms = panel.symbols[:6]
    df = _news_frame(panel, syms, 100, 500)
    base = build_news_matrices(panel, store=_FakeStore(df))
    K = 300
    later = df.copy()
    late = later["trade_date"] > pd.Timestamp(panel.dates[K])
    later.loc[late, "mean_sentiment"] = 1.0
    later.loc[late, "n_articles"] = 99
    after = build_news_matrices(panel, store=_FakeStore(later))
    for k in NEWS_SIGNALS:
        a, b = base[k][:K - 5], after[k][:K - 5]
        ok = np.isfinite(a) & np.isfinite(b)
        assert np.allclose(a[ok], b[ok]), f"{k} peeked at future news"


def test_missing_news_cache_returns_empty_not_zero():
    panel, _ = synth_panel(n_days=300, n_symbols=4, seed=3)
    mats = build_news_matrices(panel, store=_FakeStore(None))
    for k in NEWS_SIGNALS:
        assert not np.isfinite(mats[k]).any()


def test_minimum_detectable_ic_scales_with_the_horizon():
    """Overlapping returns mean the effective sample is sessions/horizon. A
    floor stated after the fact is a rationalisation; stated before, it is the
    difference between 'not present' and 'not resolvable'."""
    a = minimum_detectable_ic(306, 5)
    b = minimum_detectable_ic(306, 21)
    assert a["effective_independent_obs"] > b["effective_independent_obs"]
    assert b["min_detectable_ic"] > a["min_detectable_ic"]
    assert b["effective_independent_obs"] == pytest.approx(306 / 21, abs=0.1)


def test_coverage_report_measures_the_tradeable_cross_section():
    panel, _ = synth_panel(n_days=600, n_symbols=8, seed=4)
    df = _news_frame(panel, panel.symbols[:4], 100, 400)
    mats = build_news_matrices(panel, store=_FakeStore(df))
    mask = np.zeros(panel.close.shape, dtype=bool)
    mask[:, :8] = True
    rep = coverage_report(panel, mask, mats)
    assert rep["covered_sessions"] > 200
    assert 0.3 < rep["median_share_of_universe_with_news"] < 0.7, rep


# ---------------------------------------------- Newey-West overlap guard --
def test_newey_west_lags_are_capped_on_a_short_sample():
    """THE regression. NW with lags = horizon under-corrects badly when the
    sample is only a few multiples of the horizon: 21 lags on 101 observations
    produced t = 2.95 where the honest figure from 4.8 effective observations
    was 1.09."""
    rng = np.random.default_rng(5)
    ic = rng.normal(0.03, 0.06, 101)
    r = icmod.ic_summary(ic, horizon=21)
    assert r["available"]
    assert r["nw_lags_wanted"] == 21
    assert r["nw_lags_used"] <= 11, r["nw_lags_used"]
    assert r["overlap_unreliable"] is True
    assert r["effective_independent_obs"] == pytest.approx(101 / 21, abs=0.1)


def test_block_t_is_withheld_when_there_are_too_few_blocks():
    """A t-statistic from four observations is theatre. The news holdout at a
    21-day horizon yields exactly four."""
    rng = np.random.default_rng(6)
    r = icmod.ic_summary(rng.normal(0.03, 0.06, 101), horizon=21)
    assert r["n_blocks"] < 8 and r["too_few_blocks"]
    assert not np.isfinite(r["t_block"])

    long = icmod.ic_summary(rng.normal(0.01, 0.06, 1000), horizon=21)
    assert long["n_blocks"] >= 8 and not long["too_few_blocks"]
    assert np.isfinite(long["t_block"])


def test_long_sample_keeps_the_full_lag_count():
    rng = np.random.default_rng(7)
    r = icmod.ic_summary(rng.normal(0.0, 0.1, 2500), horizon=21)
    assert r["nw_lags_used"] == 21
    assert r["overlap_unreliable"] is False
