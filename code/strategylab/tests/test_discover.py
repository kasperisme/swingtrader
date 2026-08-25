"""The discovery loop.

Two tests carry the whole thing:

  * `test_loop_finds_a_planted_signal` — a search that cannot detect a real
    effect is worthless, however disciplined.
  * `test_loop_confirms_nothing_on_pure_noise` — a search that reports findings
    on noise is worse than worthless. This is the failure mode a loop told to
    run "until it finds alpha" has by construction, and the rising bar is what
    prevents it.
"""

import numpy as np
import pandas as pd
import pytest

from strategylab.data.prices import Panel
from strategylab.features import FeatureBank
from strategylab.discover.execute import Context, build_signal, evaluate
from strategylab.discover.hypothesis import (SIGNAL_PRIMITIVES, Hypothesis,
                                             HypothesisSpace, apply_transform)
from strategylab.discover.loop import DiscoveryLoop, LoopConfig, significance_bar
from strategylab.discover.registry import Registry, ScoredHypothesis


# ------------------------------------------------------------------ bar --
def test_bar_rises_with_the_trial_count():
    a, b, c = significance_bar(1), significance_bar(100), significance_bar(1000)
    assert a < b < c
    assert a == pytest.approx(2.0, abs=1e-9), "the floor is 2.0"
    assert b == pytest.approx(np.sqrt(2 * np.log(100)) + 0.5, abs=1e-9)
    assert c > 4.0, "a thousand hypotheses must demand a visibly higher bar"


def test_bar_would_be_breached_by_noise_at_a_fixed_threshold():
    """Why the bar has to move: the max of N null draws grows like sqrt(2 ln N),
    so a fixed 2.0 is certain to be cleared once a search gets wide enough."""
    rng = np.random.default_rng(0)
    draws = rng.standard_normal((200, 500))
    max_abs = np.abs(draws).max(axis=1)
    assert (max_abs > 2.0).mean() > 0.99, "a fixed 2.0 is breached essentially always"
    assert (max_abs > significance_bar(500)).mean() < 0.35, (
        "the rising bar must survive most noise searches of this width")


# ------------------------------------------------------------- registry --
def test_registry_counts_failures_toward_the_bar(tmp_path):
    """THE point of the registry. A bar computed only from the hypotheses that
    looked interesting is the selection effect wearing a lab coat."""
    reg = Registry(tmp_path / "r.sqlite")
    space = HypothesisSpace()
    for h in space.all()[:25]:
        reg.register(h)
        reg.record(ScoredHypothesis(key=h.key, name=h.name, t_stat=0.1, rung=0))
    assert reg.n_tested() == 25
    assert significance_bar(reg.n_tested()) > significance_bar(1)
    assert reg.summary()["cleared"] == 0


def test_registry_survives_a_restart(tmp_path):
    p = tmp_path / "r.sqlite"
    reg = Registry(p)
    h = HypothesisSpace().all()[0]
    reg.register(h)
    reg.record(ScoredHypothesis(key=h.key, name=h.name, t_stat=1.0))
    reg.close()
    again = Registry(p)
    assert again.n_tested() == 1
    assert h.key in again.tested_keys()


def test_registered_but_untested_does_not_count():
    """Registration is the pre-commitment; only execution raises the bar."""
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        reg = Registry(pd.io.common.os.path.join(d, "r.sqlite"))
        for h in HypothesisSpace().all()[:10]:
            reg.register(h)
        assert reg.summary()["registered"] == 10
        assert reg.n_tested() == 0


# ------------------------------------------------------------ hypotheses --
def test_space_is_finite_deduplicated_and_ordered():
    sp = HypothesisSpace()
    all_h = sp.all()
    assert len(all_h) == sp.size() > 100
    assert len({h.key for h in all_h}) == len(all_h), "keys must be unique"
    # The interpretable forms come first so an interrupted run covers them.
    assert all_h[0].transform == "raw"


def test_next_untested_skips_what_is_done():
    sp = HypothesisSpace()
    done = {h.key for h in sp.all()[:5]}
    nxt = sp.next_untested(done, 3)
    assert len(nxt) == 3
    assert not ({h.key for h in nxt} & done)


@pytest.mark.parametrize("transform", ["raw", "negate", "delta_21", "vs_own_mean_63"])
def test_transforms_never_look_forward(transform):
    """Every transform must be backward-looking; scrambling the tail cannot
    change the head."""
    rng = np.random.default_rng(1)
    mat = np.cumsum(rng.standard_normal((400, 6)), axis=0) + 50.0
    K = 250
    later = mat.copy()
    later[K + 1:] += rng.standard_normal(later[K + 1:].shape) * 20
    a = apply_transform(mat, transform)[:K]
    b = apply_transform(later, transform)[:K]
    ok = np.isfinite(a) & np.isfinite(b)
    assert ok.sum() > 100
    assert np.allclose(a[ok], b[ok]), f"{transform} peeked at the future"


def test_unknown_transform_is_rejected():
    with pytest.raises(ValueError):
        apply_transform(np.zeros((10, 2)), "nonsense")


# ------------------------------------------------------------ integration --
def _panel(n=1600, m=45, seed=0, plant=0.0):
    """Trending names. With `plant`, the 5-day return predicts the NEXT 5 days
    positively — a real, detectable effect placed in the data on purpose."""
    rng = np.random.default_rng(seed)
    r = rng.normal(0.0006, 0.017, (n, m))
    if plant:
        for t in range(10, n - 6):
            r[t + 1:t + 6] += plant * np.sign(r[t - 5:t].sum(axis=0)) * 0.01
    close = 40.0 * np.exp(np.cumsum(r, axis=0))
    intra = np.abs(rng.normal(0, 0.011, close.shape))
    high, low = close * (1 + intra), close * (1 - intra)
    open_ = np.clip(close * (1 + rng.normal(0, 0.004, close.shape)), low, high)
    vol = rng.lognormal(14.5, 0.4, close.shape)
    dates = pd.bdate_range("2010-01-04", periods=n).values.astype("datetime64[D]")
    bench = 100.0 * np.exp(np.cumsum(rng.normal(0.0004, 0.009, n)))
    p = Panel(dates=dates, symbols=[f"D{i:03d}" for i in range(m)], open=open_,
              high=high, low=low, close=close, volume=vol)
    return p, FeatureBank(p, benchmark_close=bench)


def _ctx(panel, bank):
    mask = np.zeros(panel.close.shape, dtype=bool)
    mask[300:] = True
    n = panel.close.shape[0]
    return Context(panel, bank, mask, (300, int(n * 0.8)), (int(n * 0.8), n - 70))


def test_build_signal_covers_every_primitive():
    """A primitive that raises is invisible in the report and reads as tested."""
    panel, bank = _panel()
    ctx = _ctx(panel, bank)
    for name in SIGNAL_PRIMITIVES:
        h = Hypothesis(name, "raw", "ic", 21)
        sig = build_signal(ctx, h)
        assert sig is not None, f"{name} failed to build"
        assert sig.shape == panel.close.shape


def test_loop_finds_a_planted_signal(tmp_path):
    panel, bank = _panel(seed=3, plant=1.0)
    ctx = _ctx(panel, bank)
    reg = Registry(tmp_path / "r.sqlite")
    space = HypothesisSpace(primitives=("ret_5", "atr_pct", "volume_ratio"),
                            transforms=("raw",), outcomes=("ic",), horizons=(5,))
    loop = DiscoveryLoop(ctx, reg, space,
                         LoopConfig(max_iterations=3, rung0_batch=3, promote_top=3))
    loop.run()
    rows = {r["name"]: r for r in reg.best(10)}
    planted = rows.get("ret_5|raw|ic|H5")
    assert planted is not None
    assert abs(planted["t_stat"]) > 3.0, (
        f"the planted effect should be obvious, got t={planted['t_stat']:.2f}")


def test_loop_confirms_nothing_on_pure_noise(tmp_path):
    """THE test. Told to search, the loop must come back empty on noise."""
    panel, bank = _panel(seed=7, plant=0.0)
    ctx = _ctx(panel, bank)
    reg = Registry(tmp_path / "r.sqlite")
    loop = DiscoveryLoop(ctx, reg, HypothesisSpace(transforms=("raw", "negate"),
                                                   outcomes=("ic",), horizons=(21,)),
                         LoopConfig(max_iterations=6, rung0_batch=10, promote_top=2))
    state = loop.run()
    assert reg.n_tested() > 30, "the search must actually have looked"
    assert not state.confirmed, f"confirmed a finding on noise: {state.confirmed}"
    assert reg.summary()["confirmed"] == 0


def test_loop_rejects_a_hypothesis_whose_placebo_also_fires(tmp_path):
    panel, bank = _panel(seed=5)
    reg = Registry(tmp_path / "r.sqlite")
    loop = DiscoveryLoop(_ctx(panel, bank), reg, HypothesisSpace(), LoopConfig())
    s = ScoredHypothesis(key="k", name="x|raw|ic|H21", t_stat=9.0, placebo_t=4.0)
    assert not loop._judge(s, bar=3.0), "a firing placebo is a broken control"
    s.placebo_t = 0.2
    assert loop._judge(s, bar=3.0)


def test_loop_records_screened_out_hypotheses(tmp_path):
    """Rung-0 rejects still happened, so they still count toward the bar."""
    panel, bank = _panel(seed=9)
    reg = Registry(tmp_path / "r.sqlite")
    loop = DiscoveryLoop(_ctx(panel, bank), reg,
                         HypothesisSpace(transforms=("raw",), outcomes=("ic",),
                                         horizons=(21,)),
                         LoopConfig(max_iterations=1, rung0_batch=10, promote_top=1))
    out = loop.step()
    assert out["promoted"] <= 1
    assert reg.n_tested() == 10, "every hypothesis in the batch must be recorded"


def test_loop_stops_when_the_space_is_exhausted(tmp_path):
    panel, bank = _panel(seed=11)
    reg = Registry(tmp_path / "r.sqlite")
    space = HypothesisSpace(primitives=("ret_5", "atr_pct"), transforms=("raw",),
                            outcomes=("ic",), horizons=(21,))
    loop = DiscoveryLoop(_ctx(panel, bank), reg, space,
                         LoopConfig(max_iterations=20, rung0_batch=2, promote_top=1))
    state = loop.run()
    assert state.stopped_because == "space exhausted"
    assert reg.n_tested() == space.size()
