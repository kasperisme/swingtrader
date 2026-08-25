"""Flow-Discriminated Pairs.

The load-bearing tests here are the two that would have caught the mistakes
this study actually made:

  * `test_non_session_row_empties_formation_without_the_filter` pins the bug
    that cost a whole vault window — one vendor bar on a Saturday NaNs every
    other name and silently empties the candidate set.
  * `test_formation_is_blind_to_the_trading_window` scrambles the trading data
    and asserts the formed book is byte-identical, which is the only thing
    standing between this design and the circularity that killed Stage 1.
"""

import numpy as np
import pandas as pd
import pytest

from strategylab.data.prices import Panel
from strategylab.pairs.discriminate import RegimeSpec, announcement_grid, classify
from strategylab.pairs.events import EventSpec, collect_events, events_frame
from strategylab.pairs.formation import (FormationSpec, adf_t, drop_non_sessions,
                                         form_pairs, formation_windows, half_life,
                                         null_distribution, null_pvalue, ols_pair,
                                         trading_sessions)
from strategylab.pairs.study import PREREGISTERED_TESTS, cluster_diff, run_tests, verdict


# ----------------------------------------------------------------- helpers --
def make_panel(close: np.ndarray, symbols: list[str], start="2013-01-01") -> Panel:
    n = close.shape[0]
    dates = pd.bdate_range(start, periods=n).values.astype("datetime64[D]")
    vol = np.full_like(close, 5e6)
    return Panel(dates=dates, symbols=symbols, open=close.copy(), high=close * 1.01,
                 low=close * 0.99, close=close, volume=vol)


def cointegrated_pair(n=1400, beta=1.3, hl=12.0, seed=0, sigma_s=0.05):
    """log P_A = a + beta*log P_B + s, with s an OU of known half-life."""
    rng = np.random.default_rng(seed)
    xb = np.log(40.0) + np.cumsum(rng.normal(0, 0.015, n))
    kappa = np.log(2.0) / hl
    phi = np.exp(-kappa)
    s = np.zeros(n)
    eps = rng.normal(0, sigma_s * np.sqrt(1 - phi ** 2), n)
    for t in range(1, n):
        s[t] = phi * s[t - 1] + eps[t]
    xa = 0.7 + beta * xb + s
    return np.exp(xa), np.exp(xb), s


# --------------------------------------------------------------- estimator --
def test_adf_matches_statsmodels():
    """The vectorised ADF is the same number statsmodels reports."""
    sm = pytest.importorskip("statsmodels.tsa.stattools")
    rng = np.random.default_rng(3)
    series = [np.cumsum(rng.normal(0, 1, 400)),
              cointegrated_pair(400, seed=4)[2] * 20.0]
    for x in series:
        mine = float(adf_t(x[:, None], lags=1)[0])
        theirs = float(sm.adfuller(x, maxlag=1, autolag=None, regression="n")[0])
        assert abs(mine - theirs) < 1e-6, f"{mine} vs {theirs}"


def test_simulated_null_reproduces_the_published_critical_values():
    """The simulated Engle-Granger null must land on MacKinnon's numbers.

    This is what licenses using a simulated null at all: if the estimator were
    wrong, or the null misspecified, the quantiles would not agree with a
    published table nobody here can tune.
    """
    null = null_distribution(T=504, lags=1, replications=3000, seed=11)
    for q, published in ((0.01, -3.90), (0.05, -3.34), (0.10, -3.04)):
        got = float(np.quantile(null, q))
        assert abs(got - published) < 0.12, f"{q:.0%}: simulated {got:.3f} vs {published}"


def test_selection_rule_fires_at_the_nominal_rate_on_noise():
    """Independent random walks are rejected ~alpha of the time, not more."""
    null = null_distribution(T=300, lags=1, replications=2000, seed=11)
    rng = np.random.default_rng(99)
    stats = []
    for _ in range(400):
        w = rng.standard_normal((300, 2)).cumsum(axis=0)
        _, _, r = ols_pair(w[:, 0], w[:, 1:2])
        stats.append(adf_t(r, lags=1)[0])
    p = null_pvalue(np.array(stats), null)
    rate = float((p < 0.05).mean())
    assert 0.015 < rate < 0.10, f"rejection rate {rate:.3f} should sit near 0.05"


def test_half_life_recovers_a_known_ou_speed():
    for target in (8.0, 20.0, 45.0):
        _, _, s = cointegrated_pair(n=4000, hl=target, seed=int(target))
        got = float(half_life(s[:, None])[0])
        assert abs(got - target) / target < 0.20, f"half-life {got:.1f} vs {target}"


def test_ols_recovers_the_hedge_ratio_on_average_but_not_in_one_sample():
    """The hedge ratio is consistent, and over a 504-day formation window it is
    also NOISY — which matters for the study, not just for this test.

    beta_hat = beta + cov(s, x_B)/var(x_B). The spread s and the regressor x_B
    are independent by construction, so the estimator is unbiased; but both are
    highly persistent, so a single short sample can miss by 10%+. A hedge ratio
    that is 10% wrong puts a deterministic drift into the traded spread that no
    amount of mean reversion removes, and it is one mechanism behind the
    out-of-sample level drift this study measures.
    """
    long_run = [float(ols_pair(np.log(ca), np.log(cb)[:, None])[1][0])
                for ca, cb, _ in (cointegrated_pair(n=6000, beta=1.75, seed=s)
                                  for s in range(12))]
    assert abs(np.mean(long_run) - 1.75) < 0.05, "consistent in the long run"

    short = [float(ols_pair(np.log(ca), np.log(cb)[:, None])[1][0])
             for ca, cb, _ in (cointegrated_pair(n=504, beta=1.75, seed=s)
                               for s in range(24))]
    assert abs(np.mean(short) - 1.75) < 0.15, "still centred at 504 observations"
    assert np.std(short) > 0.03, (
        "a 504-day hedge ratio should carry visible sampling error; if this "
        "ever tightens, the drift attribution in the findings needs revisiting")


# --------------------------------------------------------------- formation --
def _two_pair_panel(seed=0, n=1400):
    ca, cb, _ = cointegrated_pair(n=n, beta=1.3, hl=12.0, seed=seed)
    cc, cd, _ = cointegrated_pair(n=n, beta=0.8, hl=25.0, seed=seed + 100)
    close = np.column_stack([ca, cb, cc, cd])
    panel = make_panel(close, ["AA", "BB", "CC", "DD"])
    industries = {"AA": "Widgets", "BB": "Widgets", "CC": "Widgets", "DD": "Widgets"}
    return panel, industries


def _spec(**kw):
    d = dict(formation_days=504, trading_days=126, min_adv_usd=0.0, min_price=0.0,
             min_formation_bars=480, require_earnings_coverage=False,
             null_replications=1000, max_pairs_per_symbol=4)
    d.update(kw)
    return FormationSpec(**d)


def test_formation_finds_the_planted_pairs_and_their_parameters():
    """Both planted pairs are recovered with the parameters they were built with.

    Note what is NOT asserted: that the reverse-direction hedge ratio is 1/beta.
    It is not. Regressing B on A returns cov/var(A), which is the forward slope
    attenuated by R^2, so inverting it overstates beta whenever the spread
    carries real variance. That asymmetry is precisely why Engle-Granger is
    direction-dependent and why `form_pairs` fits both orientations and keeps
    the stronger one.
    """
    panel, industries = _two_pair_panel()
    spec = _spec()
    w = formation_windows(panel, str(panel.dates[600]), str(panel.dates[-1]), spec)[0]
    pairs, funnel = form_pairs(panel, w, industries, spec)
    found = {frozenset((p.a, p.b)): p for p in pairs}
    assert frozenset(("AA", "BB")) in found, funnel

    # Specificity: AA/BB and CC/DD are built from independent random walks, so
    # no cross pair may be selected. (CC/DD itself, with a 25-day half-life, is
    # NOT asserted to be found — an AR(1) that persistent is near the detection
    # limit over 504 observations, which is the same power problem the
    # `max_half_life` band exists to keep out of the book.)
    for cross in (("AA", "CC"), ("AA", "DD"), ("BB", "CC"), ("BB", "DD")):
        assert frozenset(cross) not in found, f"{cross} is a spurious pair"

    p = found[frozenset(("AA", "BB"))]
    assert 6.0 < p.half_life < 22.0, "planted half-life was 12 days"

    # Whatever orientation was selected, the stored parameters must equal a
    # direct OLS on the formation window alone.
    logp = np.log(panel.close[w["f0"]:w["f1"]])
    ja, jb = panel.symbols.index(p.a), panel.symbols.index(p.b)
    a_, b_, resid = ols_pair(logp[:, ja], logp[:, jb][:, None])
    assert abs(p.beta - float(b_[0])) < 1e-10
    assert abs(p.alpha - float(a_[0])) < 1e-10
    assert abs(p.sigma - float(resid[:, 0].std(ddof=1))) < 1e-10



def test_formation_is_blind_to_the_trading_window():
    """THE look-ahead test. Replace every price after the formation boundary
    with garbage; the formed book must be byte-identical."""
    panel, industries = _two_pair_panel()
    spec = _spec()
    w = formation_windows(panel, str(panel.dates[600]), str(panel.dates[-1]), spec)[0]
    base, _ = form_pairs(panel, w, industries, spec)

    rng = np.random.default_rng(1234)
    close = panel.close.copy()
    close[w["f1"]:] = np.exp(np.log(close[w["f1"]:]) + rng.normal(0, 0.5, close[w["f1"]:].shape))
    scrambled = make_panel(close, list(panel.symbols), start=str(panel.dates[0]))
    after, _ = form_pairs(scrambled, w, industries, spec)

    assert len(base) == len(after)
    for x, y in zip(base, after):
        assert (x.a, x.b) == (y.a, y.b)
        assert x.beta == y.beta and x.mu == y.mu and x.sigma == y.sigma
        assert x.adf_t == y.adf_t and x.half_life == y.half_life


def test_non_session_row_empties_formation_without_the_filter():
    """Regression: one bar on a non-trading day used to zero the candidate set.

    The panel index is the union of every symbol's dates, so a single spurious
    Saturday bar makes every other name NaN on that row, and joint completeness
    over the formation window then fails for all of them.
    """
    panel, industries = _two_pair_panel()
    n = panel.close.shape[0]
    # Splice in a Saturday on which only "AA" is priced.
    dates = list(panel.dates)
    bogus = np.datetime64("2014-11-08")          # a Saturday
    at = int(np.searchsorted(np.array(dates, dtype="datetime64[D]"), bogus))
    row = np.full((1, 4), np.nan)
    row[0, 0] = panel.close[at, 0]
    close = np.vstack([panel.close[:at], row, panel.close[at:]])
    new_dates = np.array(dates[:at] + [bogus] + dates[at:], dtype="datetime64[D]")
    dirty = Panel(dates=new_dates, symbols=list(panel.symbols), open=close.copy(),
                  high=close, low=close, close=close, volume=np.full_like(close, 5e6))

    spec = _spec()
    w = formation_windows(dirty, str(dirty.dates[600]), str(dirty.dates[-1]), spec)[0]
    assert w["f0"] < at < w["f1"], "the test needs the bogus row inside the formation window"

    broken, funnel = form_pairs(dirty, w, industries, spec)
    assert funnel["candidate pairs (within industry)"] == 0
    assert not broken

    clean, dropped = drop_non_sessions(dirty)
    assert "2014-11-08" in dropped
    w2 = formation_windows(clean, str(clean.dates[600]), str(clean.dates[-1]), spec)[0]
    fixed, funnel2 = form_pairs(clean, w2, industries, spec)
    assert funnel2["candidate pairs (within industry)"] > 0
    assert fixed, "the filter must restore the pair book"


def test_trading_sessions_keeps_weekdays():
    panel, _ = _two_pair_panel()
    keep = trading_sessions(panel)
    assert keep.all(), "a clean business-day panel must survive the filter intact"


# ------------------------------------------------------------------ events --
def _pair_for(panel, industries, spec=None):
    spec = spec or _spec()
    w = formation_windows(panel, str(panel.dates[600]), str(panel.dates[-1]), spec)[0]
    pairs, _ = form_pairs(panel, w, industries, spec)
    return [p for p in pairs if {p.a, p.b} == {"AA", "BB"}], w


def test_costs_strictly_reduce_every_event_return():
    panel, industries = _two_pair_panel()
    pairs, _ = _pair_for(panel, industries)
    ev = collect_events(panel, pairs, EventSpec())
    assert ev, "the planted OU pair should diverge at least once"
    for e in ev:
        assert e.net_return < e.gross_return


def test_fills_use_the_next_open_not_the_signal_close():
    """A signal on the close of t must be filled at the open of t+1."""
    panel, industries = _two_pair_panel()
    pairs, _ = _pair_for(panel, industries)
    ev = collect_events(panel, pairs, EventSpec())
    assert ev
    e = ev[0]
    assert e.entry_day == e.day + 1

    # Move the entry-day opens far away from the closes; returns must change.
    base = e.gross_return
    open_ = panel.open.copy()
    open_[e.entry_day, :] *= 1.25
    moved = Panel(dates=panel.dates, symbols=list(panel.symbols), open=open_,
                  high=panel.high, low=panel.low, close=panel.close, volume=panel.volume)
    ev2 = collect_events(moved, pairs, EventSpec())
    assert ev2 and ev2[0].gross_return != base


def test_rmst_keeps_censored_events_at_the_horizon():
    """The H1c fix: an unconverged event contributes the full horizon rather
    than dropping out of the average."""
    panel, industries = _two_pair_panel()
    pairs, _ = _pair_for(panel, industries)
    spec = EventSpec()
    ev = collect_events(panel, pairs, spec)
    censored = [e for e in ev if not e.converged]
    for e in censored:
        assert np.isnan(e.days_to_converge)
        assert e.rmst_days > 0
    for e in ev:
        if e.converged:
            assert e.rmst_days == e.days_to_converge


def test_events_re_arm_only_after_the_spread_comes_back():
    panel, industries = _two_pair_panel()
    pairs, _ = _pair_for(panel, industries)
    ev = collect_events(panel, pairs, EventSpec())
    days = sorted(e.day for e in ev)
    assert len(set(days)) == len(days), "no two events may fire on the same session"


# ----------------------------------------------------------- discriminator --
def test_announcement_grid_flags_only_the_window():
    panel, _ = _two_pair_panel()
    d = str(panel.dates[700])
    grid = announcement_grid(panel, {"AA": [d]}, window=2)
    flagged = np.flatnonzero(grid[:, 0])
    assert list(flagged) == [698, 699, 700, 701, 702]
    assert not grid[:, 1].any(), "a name with no announcements is never flagged"


def test_classification_and_placebo_share_a_marginal_rate():
    panel, industries = _two_pair_panel()
    pairs, _ = _pair_for(panel, industries)
    ev = events_frame(collect_events(panel, pairs, EventSpec()))
    rng = np.random.default_rng(2)
    dates = [str(panel.dates[i]) for i in rng.choice(len(panel.dates), 60, replace=False)]
    df = classify(ev, panel, {"AA": dates, "BB": dates}, RegimeSpec())
    assert set(df["regime"]) <= {"L", "N"}
    assert (df["n_legs_flagged"] > 0).equals(df["regime"] == "N")
    real = float((df["regime"] == "N").mean())
    fake = float(df["placebo_flag"].mean())
    assert abs(real - fake) < 0.25, "the placebo must carry a comparable marginal rate"


# ------------------------------------------------------------------- study --
def _synthetic_events(n=3000, effect=0.0, seed=0):
    """Events with a KNOWN L-minus-N convergence gap of `effect`."""
    rng = np.random.default_rng(seed)
    regime = np.where(rng.random(n) < 0.28, "N", "L")
    base = 0.30
    p = np.where(regime == "L", base + effect / 2, base - effect / 2)
    conv = (rng.random(n) < p).astype(float)
    return pd.DataFrame({
        "window": rng.integers(0, 20, n), "regime": regime,
        "regime_detail": np.where(regime == "L", "L_no_news", "N_one_leg"),
        "converged": conv, "converged_soft": conv,
        "net_return": rng.normal(0, 0.05, n), "gross_return": rng.normal(0, 0.05, n),
        "days_to_converge": np.where(conv > 0, rng.integers(1, 60, n), np.nan),
        "rmst_days": np.where(conv > 0, rng.integers(1, 60, n), 60.0),
        "half_life": rng.uniform(5, 60, n), "z_entry": rng.uniform(2, 4, n),
        "etf_overlap": rng.random(n),
        "stale_flag": rng.random(n) < 0.4, "placebo_flag": rng.random(n) < 0.28,
    })


def test_h1_does_not_fire_when_there_is_no_effect():
    """The false-positive check. With regimes assigned at random the key test
    must not pass — otherwise every result this battery produces is worthless."""
    fired = 0
    for seed in range(12):
        t = run_tests(_synthetic_events(effect=0.0, seed=seed))
        fired += bool(t["H1a_convergence_rate_L_gt_N"]["pass"])
    assert fired <= 1, f"key test fired on {fired}/12 pure-noise panels"


def test_h1_fires_when_the_effect_is_planted():
    """The power check — the mirror of the above."""
    fired = 0
    for seed in range(8):
        t = run_tests(_synthetic_events(n=5000, effect=0.10, seed=seed))
        fired += bool(t["H1a_convergence_rate_L_gt_N"]["pass"])
    assert fired >= 6, f"key test only fired on {fired}/8 panels with a real 10pp effect"


def test_verdict_requires_the_falsifications_to_pass():
    """A design where the placebo also separates must not be declared a
    replication, however strong the real split looks."""
    tests = {
        "P0_baseline_pairs_converge": {"pass": True},
        "H1a_convergence_rate_L_gt_N": {"pass": True},
        "F1_placebo_labels_null": {"pass": False},
        "F2_stale_announcements_null": {"pass": True},
    }
    assert not verdict(tests)["h1_replicated"]
    tests["F1_placebo_labels_null"]["pass"] = True
    assert verdict(tests)["h1_replicated"]


def test_cluster_inference_drops_rather_than_imputes_thin_cells():
    df = _synthetic_events(n=400, seed=1)
    df.loc[df["window"] == 0, "regime"] = "L"          # window 0 has no N events
    r = cluster_diff(df, "converged", "regime", "L", "N")
    assert r["clusters_dropped"] >= 1
    assert r["clusters"] < df["window"].nunique()


def test_every_registered_test_is_actually_run():
    """A name on the pre-registration that never executes is a silent variant."""
    t = run_tests(_synthetic_events(n=4000, effect=0.05, seed=3))
    for name in PREREGISTERED_TESTS:
        assert name in t, f"{name} is registered but was never computed"


# ------------------------------------------------------------------ anchor --
from strategylab.pairs.anchor import (AnchorSpec, anchored_z, synthetic_null,
                                      z_from_series)
from strategylab.pairs.anchor_study import ANCHORS, PRIMARY, excess_over_null
from strategylab.pairs.anchor_study import verdict as anchor_verdict
from strategylab.pairs.events import scan_convergence


def _rw_spreads(n=400, T=700, seed=0):
    rng = np.random.default_rng(seed)
    return rng.standard_normal((T, n)).cumsum(axis=0)


def test_rolling_anchor_manufactures_convergence_on_random_walks():
    """THE finding of Step 1, pinned.

    Subtracting a trailing mean makes a random walk oscillate around zero, so a
    rolling-anchored z "converges" constantly with no mean reversion present at
    all. This is the same class of artefact as the EMA that manufactured flow
    persistence in Stage 1, and it is why every anchor is scored against its own
    simulated null rather than against 50% or against intuition.
    """
    s = _rw_spreads(n=300, T=700, seed=1)
    spec = EventSpec()
    rates = {}
    for label, anchor in (("frozen", AnchorSpec(mode="formation")),
                          ("rolling", AnchorSpec(mode="rolling", window=60))):
        z = z_from_series(s, anchor, 0, 504)
        conv, n_ev = 0, 0
        for j in range(s.shape[1]):
            for e in scan_convergence(z[:, j], 504, 630, spec, n=700):
                n_ev += 1
                conv += int(e["converged"])
        rates[label] = conv / max(1, n_ev)

    assert rates["frozen"] < 0.50, (
        f"a frozen anchor on random walks should sit near the first-passage rate, "
        f"got {rates['frozen']:.1%}")
    assert rates["rolling"] > 0.65, (
        f"a rolling anchor should MANUFACTURE convergence on random walks; "
        f"got only {rates['rolling']:.1%} — if this ever drops, the null in "
        f"anchor_study is no longer doing any work")
    assert rates["rolling"] - rates["frozen"] > 0.25


def test_frozen_null_agrees_with_the_analytic_first_passage_rate():
    """The simulation is validated against a formula, not against itself."""
    from scipy import stats as _st
    spec = EventSpec()
    s = _rw_spreads(n=600, T=700, seed=2)
    z = z_from_series(s, AnchorSpec(mode="formation"), 0, 504)
    conv, analytic, n_ev = 0, [], 0
    for j in range(s.shape[1]):
        for e in scan_convergence(z[:, j], 504, 630, spec, n=700):
            n_ev += 1
            conv += int(e["converged"])
            seg = z[e["day"]:e["stop"] + 1, j]
            dz = float(np.diff(seg).std(ddof=1))
            steps = len(seg) - 1
            if dz > 0 and steps > 0:
                analytic.append(min(1.0, 2 * _st.norm.cdf(
                    -abs(e["z_entry"]) / (dz * np.sqrt(steps)))))
    assert n_ev > 200
    got, want = conv / n_ev, float(np.mean(analytic))
    assert abs(got - want) < 0.06, f"simulated {got:.3f} vs analytic {want:.3f}"


def test_rolling_anchor_has_no_lookahead():
    """The shift(1) is the whole no-look-ahead argument — pin it.

    Scrambling every price after day K must leave every z up to and including
    day K byte-identical.
    """
    panel, industries = _two_pair_panel()
    pairs, _ = _pair_for(panel, industries)
    p = pairs[0]
    anchor = AnchorSpec(mode="rolling", window=60)
    base = anchored_z(p, panel.close, anchor)

    K = 800
    rng = np.random.default_rng(7)
    close = panel.close.copy()
    close[K + 1:] = np.exp(np.log(close[K + 1:]) + rng.normal(0, 0.4, close[K + 1:].shape))
    after = anchored_z(p, close, anchor)

    a, b = base[:K + 1], after[:K + 1]
    both = np.isfinite(a) & np.isfinite(b)
    assert both.sum() > 300
    assert np.array_equal(a[both], b[both]), "the rolling anchor peeked at the future"
    assert np.array_equal(np.isfinite(a), np.isfinite(b))


def test_rolling_beta_null_is_matched_to_the_rolling_beta_anchor():
    """Regression: A2's null must re-estimate beta the way A2 does.

    Scoring the rolling-beta anchor against the fixed-beta null understated it
    by ~35 percentage points, which read as a catastrophic result rather than a
    mismatched control.
    """
    fspec = _spec(formation_days=250, null_replications=400)
    espec = EventSpec(horizon=40)
    fixed = synthetic_null(ANCHORS["A1_rolling_60"], espec, fspec, crit=-3.0,
                           n_keep=120, seed=3, block=800, max_blocks=12)
    rolled = synthetic_null(ANCHORS["A2_rolling_60_rolling_beta"], espec, fspec,
                            crit=-3.0, n_keep=120, seed=3, block=800, max_blocks=12)
    assert fixed["available"] and rolled["available"]
    assert abs(fixed["convergence"] - rolled["convergence"]) > 0.02, (
        "the two nulls came out identical — the rolling-beta spread is probably "
        "not being rebuilt in synthetic_null")


def test_excess_over_null_is_zero_when_realised_equals_the_null():
    df = _synthetic_events(n=4000, effect=0.0, seed=11)
    rate = float(df["converged"].mean())
    r = excess_over_null(df, rate)
    assert abs(r["excess"]) < 0.01
    assert abs(r["t"]) < 2.0


def test_anchor_verdict_needs_both_gates():
    good = {"G1_excess_convergence_over_matched_null": {"pass": True},
            "G2_excess_is_positive_in_a_majority_of_windows": {"pass": True}}
    assert anchor_verdict({PRIMARY: good})["anchor_repair_succeeds"]
    bad = dict(good, G1_excess_convergence_over_matched_null={"pass": False})
    assert not anchor_verdict({PRIMARY: bad})["anchor_repair_succeeds"]
    # A secondary anchor passing cannot rescue the primary.
    others = {PRIMARY: bad, "A3_rolling_120": good}
    assert not anchor_verdict(others)["anchor_repair_succeeds"]
