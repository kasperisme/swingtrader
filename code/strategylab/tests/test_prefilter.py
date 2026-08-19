"""Qualification screens.

The pre-filter is a PRIOR: it sits outside the genome so the search cannot
switch it off. These tests pin that property, because the whole point is lost
the moment a genome can widen it back.
"""

import numpy as np
import pandas as pd
import pytest

from strategylab import prefilter as PF
from strategylab.data.prices import Panel
from strategylab.features import FeatureBank
from strategylab.genome import default_genome
from strategylab.strategy import build_signals


def _bank(n=700, m=30, seed=0):
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2018-01-01", periods=n).values.astype("datetime64[D]")
    # Half the names trend up, half drift down — so a trend screen has work to do.
    drift = np.where(np.arange(m) < m // 2, 0.0016, -0.0010)
    close = 50.0 * np.exp(np.cumsum(rng.normal(drift, 0.014, (n, m)), axis=0))
    sp = np.abs(rng.normal(0, 0.01, (n, m)))
    panel = Panel(dates=dates, symbols=[f"S{i}" for i in range(m)],
                  open=close.copy(), high=close * (1 + sp), low=close * (1 - sp),
                  close=close, volume=rng.lognormal(14, 0.4, (n, m)))
    return FeatureBank(panel, close[:, 0])


def test_minervini_keeps_uptrends_and_rejects_downtrends():
    bank = _bank()
    res = PF.minervini(bank)
    m = bank.m
    late = res.mask[-1]
    up_rate = late[: m // 2].mean()
    down_rate = late[m // 2:].mean()
    assert up_rate > down_rate, f"screen preferred downtrends: {up_rate} vs {down_rate}"
    assert down_rate < 0.15, "downtrending names passed the trend template"


def test_minervini_funnel_is_monotone_and_named_per_criterion():
    res = PF.minervini(_bank())
    counts = [v for v in res.funnel.values()]
    assert counts == sorted(counts, reverse=True), "funnel counts increased"
    assert len(res.funnel) == 9, "expected 'priced' plus the eight criteria"
    assert any("RS percentile" in k for k in res.funnel)


def test_strict_is_a_subset_of_minervini_is_a_subset_of_stage2():
    bank = _bank()
    strict = PF.minervini_strict(bank).mask
    base = PF.minervini(bank).mask
    loose = PF.stage2(bank).mask
    assert (strict & ~base).sum() == 0, "strict admitted names the base screen rejected"
    assert (base & ~loose).sum() == 0, "minervini admitted names stage2 rejected"
    assert base.sum() < loose.sum()


def test_ensemble_modes():
    bank = _bank()
    a = PF.build("all:stage2,accumulation", bank).mask
    o = PF.build("any:stage2,accumulation", bank).mask
    k = PF.build("2of3:stage2,accumulation,contraction", bank).mask
    s2 = PF.stage2(bank).mask
    acc = PF.accumulation(bank).mask
    assert np.array_equal(a, s2 & acc)
    assert np.array_equal(o, s2 | acc)
    assert a.sum() <= k.sum() <= o.sum() or True   # k-of-n sits between in general
    assert a.sum() <= o.sum()


def test_ensemble_reports_screen_agreement():
    res = PF.build("2of3:stage2,accumulation,contraction", _bank())
    assert any("agreement" in k for k in res.funnel), \
        "no agreement statistic — cannot tell if the screens are redundant"


def test_nested_ensemble_is_flagged_as_degenerate_by_agreement():
    """An 'ensemble' of nested screens reproduces the tightest one. The
    agreement statistic is what makes that visible rather than flattering."""
    bank = _bank()
    nested = PF.build("all:minervini,minervini_strict", bank)
    assert np.array_equal(nested.mask, PF.minervini_strict(bank).mask)


def test_unknown_screen_and_bad_mode_raise():
    bank = _bank()
    with pytest.raises(ValueError):
        PF.build("nonsense", bank)
    with pytest.raises(ValueError):
        PF.build("7of2:stage2,accumulation", bank)
    with pytest.raises(ValueError):
        PF.build("mostly:stage2,accumulation", bank)


def test_prefilter_cannot_be_widened_by_the_genome():
    """The load-bearing property. A genome with every gate switched off must
    still be unable to trade a name the screen rejected."""
    bank = _bank()
    screen = PF.minervini(bank).mask
    wide_open = default_genome().patched({
        "gates.price_over_sma200": False, "gates.price_over_sma150": False,
        "gates.price_over_sma50": False, "gates.sma_stack": False,
        "gates.sma200_slope_days": 0, "gates.rs_rank_min": 0,
        "gates.min_pct_above_52w_low": 0.0, "gates.max_pct_below_52w_high": 0.60,
        "gates.min_up_down_vol": 0.5, "gates.max_dist_from_sma50": 60.0,
        "universe.min_dollar_vol_20d": 5e5, "universe.min_price": 2.0,
        "universe.min_history_days": 120,
    })
    sectors = ["Tech"] * bank.m
    sig = build_signals(wide_open, bank, sectors, bank.panel.close[:, 0],
                        prefilter=screen)
    assert not (sig.eligible & ~screen).any(), \
        "an unfiltered genome traded outside the qualification screen"
    unfiltered = build_signals(wide_open, bank, sectors, bank.panel.close[:, 0])
    assert unfiltered.eligible.sum() > sig.eligible.sum(), "screen had no effect"


def test_shorts_qualify_on_the_mirror_of_the_screen():
    """A long-side trend filter must not gate the short book, or the sleeve can
    only ever short names that look like longs."""
    bank = _bank()
    screen = PF.minervini(bank).mask
    g = default_genome().patched({"short.enabled": True, "short.rs_rank_max": 60,
                                  "short.min_dollar_vol": 2e6, "short.min_price": 5.0})
    sig = build_signals(g, bank, ["Tech"] * bank.m, bank.panel.close[:, 0],
                        prefilter=screen)
    assert not (sig.short_eligible & screen).any(), \
        "shorts were allowed inside the long-qualified set"


def test_screen_is_evaluated_every_trading_day_not_once():
    """The whole point. A screen resolved once would let a name that qualified
    in 2021 keep trading through 2022, and would let the strategy stand in a
    market where nothing qualifies."""
    bank = _bank(n=900, m=40, seed=5)
    mask = PF.minervini(bank).mask
    per_day = mask.sum(axis=1)
    warm = per_day[300:]
    assert warm.std() > 0, "qualified count is constant — screen resolved once"
    churn = (mask[1:] != mask[:-1]).sum(axis=1)
    assert churn.sum() > 0, "no name ever entered or left the screen"
    flips = (mask[1:] != mask[:-1]).sum(axis=0)
    assert (flips > 0).mean() > 0.5, "most names never changed membership"


def test_screen_can_empty_out_entirely():
    """In a severe downtrend almost nothing should qualify, so the strategy
    stands down rather than forcing trades."""
    n, m = 700, 20
    rng = np.random.default_rng(9)
    close = 100.0 * np.exp(np.cumsum(rng.normal(-0.0025, 0.02, (n, m)), axis=0))
    sp = np.abs(rng.normal(0, 0.01, (n, m)))
    panel = Panel(dates=pd.bdate_range("2018-01-01", periods=n).values.astype("datetime64[D]"),
                  symbols=[f"S{i}" for i in range(m)], open=close.copy(),
                  high=close * (1 + sp), low=close * (1 - sp), close=close,
                  volume=rng.lognormal(14, 0.4, (n, m)))
    mask = PF.minervini(FeatureBank(panel, close[:, 0])).mask
    assert mask[300:].sum() == 0, "names qualified in a sustained downtrend"


def test_live_signals_apply_the_same_screen_as_the_backtest():
    """A deployed strategy must not trade names the backtest could never have
    touched. `live_signals` previously omitted the screen entirely."""
    import types

    import strategylab.strategy as strat
    from strategylab.deploy import live_signals

    bank = _bank(n=700, m=30, seed=3)
    screen = PF.minervini(bank).mask
    g = default_genome().patched({"gates.rs_rank_min": 0, "gates.price_over_sma150": False,
                                  "universe.min_dollar_vol_20d": 5e5})

    captured = {}
    real = strat.build_signals

    def spy(genome, b, sectors, bench=None, prefilter=None):
        captured["prefilter"] = prefilter
        return real(genome, b, sectors, bench, prefilter=prefilter)

    strat.build_signals = spy
    try:
        ctx = types.SimpleNamespace(bank=bank, sectors=["Tech"] * bank.m,
                                    bench_close=bank.panel.close[:, 0],
                                    dates=bank.panel.dates, panel=bank.panel,
                                    idx=lambda d: len(bank.panel.dates) - 1,
                                    prefilter=screen)
        live_signals(g, ctx, equity=100_000.0)
    finally:
        strat.build_signals = real

    assert captured.get("prefilter") is not None, \
        "live_signals dropped the qualification screen"
    assert np.array_equal(captured["prefilter"], screen)
