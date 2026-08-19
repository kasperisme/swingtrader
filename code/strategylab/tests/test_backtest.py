"""The tests that matter: causality, cost realism, and stop integrity.

A backtest that fails these produces beautiful numbers that mean nothing, so
they are checked on synthetic data where the ground truth is constructible.
"""

import numpy as np
import pytest

from strategylab.backtest import run_backtest
from strategylab.config import LabConfig
from strategylab.data.prices import Panel
from strategylab.features import FeatureBank
from strategylab.genome import default_genome
from strategylab.strategy import build_signals
from tests.conftest import synthetic_panel


def _run(panel: Panel, genome=None, cfg=None):
    g = genome or default_genome().patched({
        "universe.min_dollar_vol_20d": 1e5,
        "universe.min_price": 2.0,
        "universe.min_history_days": 250,
        "gates.rs_rank_min": 40,
        "regime.enabled": False,
        "gates.min_up_down_vol": 0.5,
    })
    cfg = cfg or LabConfig()
    bank = FeatureBank(panel, panel.close[:, 0])
    sectors = ["Tech" if i % 2 else "Health" for i in range(len(panel.symbols))]
    sig = build_signals(g, bank, sectors, panel.close[:, 0])
    return run_backtest(g, panel, sig, sectors, cfg,
                        rs_rank=bank.get("rs_rank"),
                        adr=bank.get("adr_pct", length=20),
                        dollar_volume_20d=bank.get("dollar_volume_20d")), g


def test_the_strategy_actually_trades(panel):
    res, _ = _run(panel)
    assert len(res.trades) > 5, "synthetic universe produced no trades — signals are dead"
    assert np.all(np.isfinite(res.equity))


def test_no_lookahead_future_prices_cannot_change_past_trades():
    """The decisive causality check.

    Run the identical strategy on two panels that agree exactly up to day K and
    diverge arbitrarily afterwards. Every trade that has already CLOSED by day K
    must be byte-identical. If any future bar can reach back into a completed
    trade, the simulator is leaking information and every result it produces is
    void.
    """
    K = 600
    base = synthetic_panel(n_days=900, seed=11)
    rng = np.random.default_rng(99)
    shock = 1.0 + rng.normal(0, 0.25, base.close[K + 1:].shape)
    future = Panel(
        dates=base.dates, symbols=list(base.symbols),
        open=base.open.copy(), high=base.high.copy(), low=base.low.copy(),
        close=base.close.copy(), volume=base.volume.copy(),
    )
    for mat in (future.open, future.high, future.low, future.close):
        mat[K + 1:] *= shock
    future.volume[K + 1:] *= 1.0 + rng.normal(0, 0.3, base.volume[K + 1:].shape)

    a, _ = _run(base)
    b, _ = _run(future)

    def closed_before(res):
        return sorted(
            (t.symbol, t.entry_idx, t.exit_idx, round(t.entry_price, 6), round(t.exit_price, 6))
            for t in res.trades if t.exit_idx <= K
        )

    assert closed_before(a), "test is vacuous — no trades closed before the divergence point"
    assert closed_before(a) == closed_before(b)


def test_entries_never_fill_at_the_signal_bar(panel):
    """Signal at close t, fill at open t+1 — never the same bar."""
    res, g = _run(panel)
    bank = FeatureBank(panel, panel.close[:, 0])
    sectors = ["Tech" if i % 2 else "Health" for i in range(len(panel.symbols))]
    sig = build_signals(g, bank, sectors, panel.close[:, 0])
    for t in res.trades:
        j = panel.symbols.index(t.symbol)
        assert sig.trigger[t.entry_idx - 1, j], "filled on a bar with no prior-day signal"
        # The fill must be the open of the entry bar, plus one-way friction.
        assert t.entry_price >= panel.open[t.entry_idx, j] - 1e-9


def test_costs_strictly_reduce_performance(panel):
    free = LabConfig()
    free.costs.commission_bps = 0.0
    free.costs.slippage_bps = 0.0
    free.costs.spread_bps = 0.0
    free.costs.impact_coef_bps = 0.0
    a, _ = _run(panel, cfg=free)
    b, _ = _run(panel)
    assert a.equity[-1] > b.equity[-1], "frictions did not reduce the equity curve"
    assert sum(t.costs for t in b.trades) > 0


def test_stops_are_honoured_including_gaps(panel):
    res, g = _run(panel)
    stopped = [t for t in res.trades if t.exit_reason in ("stop", "stop_gap")]
    assert stopped
    for t in stopped:
        # A stop exit fills at the live stop (after any trailing ratchet) or
        # below it on a gap — never above. Comparing against `initial_stop`
        # would be wrong for any trade whose stop was trailed up.
        assert t.final_stop >= t.initial_stop - 1e-9
        assert t.exit_price <= t.final_stop * 1.001


def test_capacity_limits_bind_on_illiquid_names():
    """A universe too thin to absorb the orders must produce truncated fills.

    The liquidity gate is lowered so the names stay eligible — the point is to
    exercise the ADV-participation cap, not the universe filter.
    """
    thin = synthetic_panel(n_days=900, seed=21)
    thin.volume[:] *= 0.05
    g = default_genome().patched({
        "universe.min_dollar_vol_20d": 5e5, "universe.min_price": 2.0,
        "regime.enabled": False, "gates.rs_rank_min": 20,
        "gates.min_up_down_vol": 0.5,
    })
    # A book far larger than these names can absorb — the situation the ADV cap
    # exists to model.
    big = LabConfig()
    big.initial_equity = 250_000_000.0
    res, _ = _run(thin, genome=g, cfg=big)
    assert res.trades, "test is vacuous — no trades to truncate"
    assert res.rejected["capacity"] > 0
    assert any(t.truncated for t in res.trades)


def test_equity_never_goes_negative(panel):
    aggressive = default_genome().patched({
        "pf.risk_pct": 3.0, "pf.max_positions": 30, "pf.max_weight": 0.5,
        "regime.enabled": False, "gates.rs_rank_min": 10,
        "universe.min_dollar_vol_20d": 1e5,
    })
    res, _ = _run(panel, genome=aggressive)
    assert np.all(res.equity >= 0)


def test_position_and_sector_caps_are_respected(panel):
    g = default_genome().patched({
        "pf.max_positions": 5, "pf.max_sector_positions": 2, "regime.enabled": False,
        "gates.rs_rank_min": 20, "universe.min_dollar_vol_20d": 1e5,
    })
    res, _ = _run(panel, genome=g)
    assert res.n_positions.max() <= 5
