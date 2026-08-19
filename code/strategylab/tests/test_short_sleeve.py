"""Signed-position mechanics, verified against hand-computed arithmetic.

Sign errors in a backtester do not crash — they produce a plausible equity
curve that is wrong in a direction nobody notices. So these tests construct
scenarios whose answer is known exactly, and check the number.
"""

import numpy as np
import pandas as pd
import pytest

from strategylab.backtest import run_backtest
from strategylab.config import LabConfig
from strategylab.data.prices import Panel
from strategylab.features import FeatureBank
from strategylab.genome import default_genome
from strategylab.strategy import Signals, build_signals


def _flat_panel(prices: np.ndarray, dates=None) -> Panel:
    """One symbol, exact OHLC = the given closes (no intrabar range)."""
    prices = np.asarray(prices, dtype=float).reshape(-1, 1)
    n = len(prices)
    d = dates if dates is not None else \
        pd.bdate_range("2020-01-01", periods=n).values.astype("datetime64[D]")
    vol = np.full((n, 1), 1e9)
    return Panel(dates=d, symbols=["X"], open=prices.copy(), high=prices.copy(),
                 low=prices.copy(), close=prices.copy(), volume=vol)


def _signals(panel: Panel, long_at=None, short_at=None) -> Signals:
    n, m = panel.close.shape
    z = np.zeros((n, m), dtype=bool)
    lt, st = z.copy(), z.copy()
    if long_at is not None:
        lt[long_at, 0] = True
    if short_at is not None:
        st[short_at, 0] = True
    atr = np.full((n, m), 1.0)
    return Signals(eligible=np.ones((n, m), dtype=bool), trigger=lt,
                   score=np.ones((n, m), dtype=np.float32),
                   short_eligible=np.ones((n, m), dtype=bool), short_trigger=st,
                   short_score=np.ones((n, m), dtype=np.float32),
                   regime_ok=np.ones(n, dtype=bool), atr=atr,
                   stop_ma=np.full((n, m), np.nan), exit_ma=np.full((n, m), np.nan),
                   gap_pct=np.zeros((n, m)), gate_pass_counts={},
                   n_days=n, n_symbols=m)


def _cfg(frictionless=True) -> LabConfig:
    cfg = LabConfig()
    if frictionless:
        cfg.costs.commission_bps = 0.0
        cfg.costs.slippage_bps = 0.0
        cfg.costs.spread_bps = 0.0
        cfg.costs.impact_coef_bps = 0.0
    return cfg


def _genome(**kw):
    base = {"pf.sizing": "equal_weight", "pf.max_weight": 0.5,
            "pf.max_positions": 3, "pf.max_new_per_day": 3,
            "pf.max_gross_exposure": 1.0, "pf.max_sector_positions": 3,
            "entry.max_gap_pct": 20.0, "exit.target_r": 0.0,
            "exit.trail_enabled": False, "exit.breakeven_after_r": 0.0,
            "exit.max_hold_days": 160, "exit.stop_type": "atr",
            "exit.stop_atr_mult": 5.0, "exit.regime_exit": False,
            "exit.exit_on_sma_break": False,
            "short.enabled": True, "short.max_positions": 3,
            "short.max_gross": 0.6, "short.borrow_bps_annual": 25.0,
            "short.stop_atr_mult": 5.0, "short.target_r": 0.0,
            "short.trail_enabled": False, "short.max_hold_days": 120,
            "short.cover_on_regime": False}
    base.update(kw)
    return default_genome().patched(base)


def _run(panel, sig, g, cfg=None):
    return run_backtest(g, panel, sig, ["Tech"], cfg or _cfg(),
                        dollar_volume_20d=np.full(panel.close.shape, 1e12))


# ---------------------------------------------------------------- direction --
def test_short_profits_when_price_falls():
    px = np.concatenate([np.full(5, 100.0), np.linspace(100, 80, 20)])
    r = _run(_flat_panel(px), _signals(_flat_panel(px), short_at=3),
             _genome(**{"short.max_hold_days": 15}))
    assert r.trades, "short never opened"
    t = r.trades[0]
    assert t.side == -1
    assert t.pnl > 0, f"short lost money in a falling market: {t.pnl}"
    assert r.equity[-1] > r.equity[0]


def test_short_loses_when_price_rises():
    px = np.concatenate([np.full(5, 100.0), np.linspace(100, 130, 20)])
    r = _run(_flat_panel(px), _signals(_flat_panel(px), short_at=3),
             _genome(**{"short.max_hold_days": 15, "short.stop_atr_mult": 60.0}))
    assert r.trades
    t = r.trades[0]
    assert t.side == -1 and t.pnl < 0
    assert r.equity[-1] < r.equity[0]


def test_long_and_short_pnl_are_exact_mirrors():
    """Same price path, opposite sides, no frictions -> equal and opposite P&L."""
    px = np.concatenate([np.full(3, 100.0), np.full(20, 110.0)])
    panel = _flat_panel(px)
    g = _genome(**{"short.borrow_bps_annual": 25.0, "exit.max_hold_days": 10,
                   "short.max_hold_days": 10, "short.stop_atr_mult": 60.0})
    lo = _run(panel, _signals(panel, long_at=1), g)
    sh = _run(panel, _signals(panel, short_at=1), g)
    assert lo.trades and sh.trades
    lt, st = lo.trades[0], sh.trades[0]
    assert lt.side == 1 and st.side == -1
    assert abs(lt.entry_price - st.entry_price) < 1e-9
    assert abs(lt.exit_price - st.exit_price) < 1e-9
    # The short additionally pays borrow, so mirror the pre-borrow P&L.
    assert abs(lt.pnl + (st.pnl + st.borrow_cost)) < 1e-6, \
        f"long {lt.pnl:.4f} vs short {st.pnl:.4f} (+borrow {st.borrow_cost:.4f})"


def test_short_pnl_matches_hand_arithmetic():
    """100 -> 90 on a short: profit is exactly shares x 10, minus borrow."""
    px = np.concatenate([np.full(3, 100.0), np.full(12, 90.0)])
    panel = _flat_panel(px)
    # NB: borrow cannot be set to zero — the genome floors it at 25bps, because
    # a stock loan is never free and a search allowed to zero it would happily
    # "discover" costless shorting.
    g = _genome(**{"short.max_hold_days": 8, "pf.max_weight": 0.25})
    r = _run(panel, _signals(panel, short_at=1), g)
    t = r.trades[0]
    assert abs(t.entry_price - 100.0) < 1e-9
    assert abs(t.exit_price - 90.0) < 1e-9
    assert t.borrow_cost > 0
    assert abs(t.pnl - (t.shares * 10.0 - t.borrow_cost)) < 1e-6
    assert abs((r.equity[-1] - r.equity[0]) - t.pnl) < 1e-3


# ------------------------------------------------------------------- stops ---
def test_short_stop_sits_above_the_entry_and_triggers_on_a_rise():
    px = np.concatenate([np.full(3, 100.0), np.full(12, 120.0)])
    panel = _flat_panel(px)
    g = _genome(**{"short.stop_atr_mult": 3.0})   # ATR = 1 -> stop at 103
    r = _run(panel, _signals(panel, short_at=1), g)
    t = r.trades[0]
    assert t.initial_stop > t.entry_price, "short stop is below the entry"
    assert abs(t.initial_stop - 103.0) < 1e-6
    assert t.exit_reason in ("stop", "stop_gap")
    assert t.pnl < 0


def test_short_trailing_stop_ratchets_downward_only():
    px = np.concatenate([np.full(3, 100.0), np.linspace(100, 70, 25), np.full(5, 70.0)])
    panel = _flat_panel(px)
    g = _genome(**{"short.trail_enabled": True, "short.trail_atr_mult": 2.0,
                   "short.stop_atr_mult": 5.0, "short.max_hold_days": 100})
    r = _run(panel, _signals(panel, short_at=1), g)
    t = r.trades[0]
    assert t.final_stop < t.initial_stop, "short trail did not ratchet down"


def test_r_multiple_sign_convention_matches_pnl_for_both_sides():
    for px, at, key in [
        (np.concatenate([np.full(3, 100.0), np.full(12, 120.0)]), 1, "long_at"),
        (np.concatenate([np.full(3, 100.0), np.full(12, 80.0)]), 1, "short_at"),
    ]:
        panel = _flat_panel(px)
        sig = _signals(panel, **{key: at})
        r = _run(panel, sig, _genome(**{"exit.max_hold_days": 8,
                                        "short.max_hold_days": 8,
                                        "short.stop_atr_mult": 60.0,
                                        "exit.stop_atr_mult": 60.0}))
        t = r.trades[0]
        assert np.sign(t.r_multiple) == np.sign(t.pnl), \
            f"R and P&L disagree in sign for side {t.side}"
        assert np.sign(t.return_pct) == np.sign(t.pnl)


def test_mae_and_mfe_are_direction_aware():
    # Short entered at 100; price dips to 80 (favourable) then back to 100.
    px = np.array([100.0, 100.0, 100.0, 90.0, 80.0, 100.0, 100.0, 100.0])
    panel = _flat_panel(px)
    g = _genome(**{"short.max_hold_days": 4, "short.stop_atr_mult": 60.0})
    r = _run(panel, _signals(panel, short_at=1), g)
    t = r.trades[0]
    assert t.mfe_r > 0, "favourable excursion recorded as adverse for a short"
    assert t.mae_r <= 0


# ------------------------------------------------------------- accounting ---
def test_short_entry_raises_cash_and_creates_a_liability():
    px = np.full(12, 100.0)
    panel = _flat_panel(px)
    r = _run(panel, _signals(panel, short_at=1),
             _genome(**{"short.max_hold_days": 100}))
    # Cash goes UP by the sale proceeds while the position is a liability, so
    # cash exceeds equity for the whole holding period.
    assert r.cash[5] > r.equity[5], "short proceeds were not credited to cash"
    # Flat price: the only thing moving equity is the daily borrow accrual, so
    # equity drifts down slowly rather than sitting still.
    assert r.equity[5] < r.equity[0]
    assert (r.equity[0] - r.equity[5]) / r.equity[0] < 1e-4, "borrow accrual is implausibly large"


def test_borrow_cost_accrues_and_reduces_short_pnl():
    px = np.concatenate([np.full(3, 100.0), np.full(40, 100.0)])
    panel = _flat_panel(px)
    free = _run(panel, _signals(panel, short_at=1),
                _genome(**{"short.borrow_bps_annual": 25.0, "short.max_hold_days": 30}))
    dear = _run(panel, _signals(panel, short_at=1),
                _genome(**{"short.borrow_bps_annual": 600.0, "short.max_hold_days": 30}))
    assert dear.trades[0].borrow_cost > free.trades[0].borrow_cost > 0
    assert dear.trades[0].pnl < free.trades[0].pnl
    assert dear.equity[-1] < free.equity[-1]


def test_short_gross_cap_is_respected():
    n = 60
    rng = np.random.default_rng(0)
    m = 8
    close = np.full((n, m), 100.0)
    panel = Panel(dates=pd.bdate_range("2020-01-01", periods=n).values.astype("datetime64[D]"),
                  symbols=[f"S{i}" for i in range(m)], open=close.copy(), high=close.copy(),
                  low=close.copy(), close=close.copy(), volume=np.full((n, m), 1e9))
    z = np.zeros((n, m), dtype=bool)
    st = z.copy()
    st[2, :] = True
    sig = Signals(eligible=np.ones((n, m), dtype=bool), trigger=z,
                  score=np.ones((n, m), dtype=np.float32),
                  short_eligible=np.ones((n, m), dtype=bool), short_trigger=st,
                  short_score=np.ones((n, m), dtype=np.float32),
                  regime_ok=np.ones(n, dtype=bool), atr=np.full((n, m), 1.0),
                  stop_ma=np.full((n, m), np.nan), exit_ma=np.full((n, m), np.nan),
                  gap_pct=np.zeros((n, m)), gate_pass_counts={}, n_days=n, n_symbols=m)
    g = _genome(**{"short.max_gross": 0.25, "pf.max_weight": 0.5,
                   "pf.max_positions": 8, "short.max_positions": 8,
                   "pf.max_new_per_day": 8, "pf.max_sector_positions": 8,
                   "short.max_hold_days": 100})
    r = run_backtest(g, panel, sig, ["Tech"] * m, _cfg(),
                     dollar_volume_20d=np.full((n, m), 1e12))
    # The cap binds at entry against equity at that moment; equity then drifts
    # down as borrow accrues, so the realised ratio creeps a little above it.
    assert r.exposure.max() <= 0.25 * 1.01, f"short gross cap breached: {r.exposure.max():.4f}"
    assert r.exposure.max() > 0.24, "cap was never approached — test is vacuous"


def test_disabled_short_sleeve_produces_no_short_trades():
    px = np.concatenate([np.full(3, 100.0), np.linspace(100, 70, 25)])
    panel = _flat_panel(px)
    r = _run(panel, _signals(panel, short_at=1), _genome(**{"short.enabled": False}))
    assert all(t.side == 1 for t in r.trades)


def test_equity_never_negative_with_shorts_in_a_squeeze():
    """A short into a violent rally must not drive equity below zero."""
    px = np.concatenate([np.full(3, 100.0), np.full(40, 400.0)])
    panel = _flat_panel(px)
    g = _genome(**{"short.stop_atr_mult": 60.0, "short.max_hold_days": 100,
                   "pf.max_weight": 0.5, "short.max_gross": 0.6})
    r = _run(panel, _signals(panel, short_at=1), g)
    assert np.all(r.equity >= 0)


def test_net_exposure_is_reported_and_signs_correctly():
    px = np.full(20, 100.0)
    panel = _flat_panel(px)
    r = _run(panel, _signals(panel, short_at=1),
             _genome(**{"short.max_hold_days": 100}))
    assert r.net_exposure is not None
    assert r.net_exposure[6] < 0, "a short-only book should show negative net exposure"
    assert r.exposure[6] > 0, "gross exposure should be positive"


def test_live_signals_emit_both_sides_when_the_sleeve_is_on(monkeypatch):
    """A deployed short-enabled genome must not silently emit long-only orders.

    This is the live/backtest divergence class: the rules that ship would not be
    the rules that were validated, and nothing would raise.
    """
    import types

    import strategylab.strategy as strat
    from strategylab.deploy import live_signals

    px = np.full(30, 100.0)
    panel = _flat_panel(px)
    last = len(panel.dates) - 1
    sig = _signals(panel, long_at=last, short_at=last)
    monkeypatch.setattr(strat, "build_signals", lambda *a, **k: sig)

    ctx = types.SimpleNamespace(bank=None, sectors=["Tech"], bench_close=None,
                                dates=panel.dates, panel=panel, idx=lambda d: last)
    df = live_signals(_genome(**{"short.enabled": True}), ctx, equity=100_000.0)

    assert "side" in df.columns, f"got {list(df.columns)}"
    assert set(df["side"]) == {"LONG", "SHORT"}, f"only one side emitted: {set(df['side'])}"
    short_row = df[df["side"] == "SHORT"].iloc[0]
    long_row = df[df["side"] == "LONG"].iloc[0]
    assert short_row["stop"] > short_row["ref_close"], "short stop is not above the entry"
    assert long_row["stop"] < long_row["ref_close"], "long stop is not below the entry"
    assert (df["shares"] > 0).all()


def test_live_signals_stay_long_only_when_the_sleeve_is_off(monkeypatch):
    import types

    import strategylab.strategy as strat
    from strategylab.deploy import live_signals

    px = np.full(30, 100.0)
    panel = _flat_panel(px)
    last = len(panel.dates) - 1
    sig = _signals(panel, long_at=last, short_at=last)
    monkeypatch.setattr(strat, "build_signals", lambda *a, **k: sig)
    ctx = types.SimpleNamespace(bank=None, sectors=["Tech"], bench_close=None,
                                dates=panel.dates, panel=panel, idx=lambda d: last)
    df = live_signals(_genome(**{"short.enabled": False}), ctx, equity=100_000.0)
    assert set(df["side"]) == {"LONG"}


def test_metrics_attribute_pnl_by_side():
    from strategylab.metrics import summarize
    px = np.concatenate([np.full(3, 100.0), np.full(20, 85.0)])
    panel = _flat_panel(px)
    r = _run(panel, _signals(panel, short_at=1),
             _genome(**{"short.max_hold_days": 10, "short.stop_atr_mult": 60.0}))
    m = summarize(r)
    assert m["n_short"] == 1 and m["n_long"] == 0
    assert m["short_pnl"] > 0
    assert m["total_borrow_cost"] > 0
    assert abs(m["short_pnl_share"] - 1.0) < 1e-9


def test_investigation_flags_a_losing_short_sleeve():
    from strategylab.investigate import investigate
    from strategylab.validation import Evaluation

    px = np.concatenate([np.full(3, 100.0), np.linspace(100, 200, 40)])
    panel = _flat_panel(px)
    g = _genome(**{"short.stop_atr_mult": 60.0, "short.max_hold_days": 30})
    r = _run(panel, _signals(panel, short_at=1), g)
    ev = Evaluation("h", 1, True)
    ev.result = r
    from strategylab.metrics import summarize
    ev.metrics = summarize(r)
    d = investigate(ev, g)
    assert "short_sleeve" in d.tables
    assert any("short sleeve LOSES" in f.finding for f in d.findings), \
        "a money-losing short book was not flagged"


# ------------------------------------------------ literature enhancements ---
def test_vol_scaling_shrinks_positions_when_the_strategy_gets_volatile():
    """Barroso & Santa-Clara: scale the book by target / realised strategy vol.

    Built as an overlay on position size, so the check is that a volatile
    history produces smaller positions than a calm one on the same signal.
    """
    rng = np.random.default_rng(0)
    n = 500
    calm = 100.0 * np.exp(np.cumsum(rng.normal(0.0004, 0.004, n)))
    wild = 100.0 * np.exp(np.cumsum(rng.normal(0.0004, 0.040, n)))
    out = {}
    for label, path in (("calm", calm), ("wild", wild)):
        panel = _flat_panel(path)
        at = list(range(3, n - 40, 25))
        sig = _signals(panel, long_at=at)
        g = _genome(**{"short.enabled": False, "pf.vol_scaling": True,
                       "pf.vol_target_portfolio": 0.10, "pf.vol_lookback": 120,
                       "pf.vol_scale_cap": 3.0, "exit.max_hold_days": 10,
                       "pf.sizing": "equal_weight"})
        r = _run(panel, sig, g)
        out[label] = float(np.nanmean(r.vol_scale[200:]))
    assert out["wild"] < out["calm"], \
        f"vol scaling did not shrink the book in the volatile regime: {out}"
    assert out["calm"] > out["wild"] * 1.5


def test_vol_scaling_is_inert_when_disabled():
    px = 100.0 * np.exp(np.cumsum(np.random.default_rng(1).normal(0.0004, 0.02, 300)))
    panel = _flat_panel(px)
    r = _run(panel, _signals(panel, long_at=[3, 50, 100]),
             _genome(**{"short.enabled": False, "pf.vol_scaling": False}))
    assert np.allclose(r.vol_scale, 1.0)


def test_information_discreteness_prefers_continuous_paths():
    """Same cumulative return, delivered continuously vs in one jump.

    Low ID means continuous. The jumpy path must score HIGHER (more discrete).
    """
    from strategylab.features import FeatureBank

    n = 400
    smooth = np.full(n, 0.0015)                 # a small gain every single day
    jumpy = np.zeros(n)
    jumpy[::20] = 0.0015 * 20                   # the same total, in rare jumps
    paths = []
    for r in (smooth, jumpy):
        paths.append(100.0 * np.exp(np.cumsum(r)))
    close = np.column_stack(paths)
    panel = Panel(dates=pd.bdate_range("2020-01-01", periods=n).values.astype("datetime64[D]"),
                  symbols=["SMOOTH", "JUMPY"], open=close.copy(), high=close.copy(),
                  low=close.copy(), close=close.copy(), volume=np.full((n, 2), 1e9))
    bank = FeatureBank(panel, close[:, 0])
    idisc = bank.get("info_discreteness")[-1]
    assert np.isfinite(idisc).all()
    assert idisc[0] < idisc[1], \
        f"continuous path did not score as more continuous: {idisc}"


def test_residual_momentum_strips_the_market_component():
    """A stock that is purely the market re-levered should have residual
    momentum near zero, while one with genuine idiosyncratic drift should not."""
    from strategylab.features import FeatureBank

    n, rng = 600, np.random.default_rng(3)
    mkt = rng.normal(0.0006, 0.01, n)
    pure_beta = 1.5 * mkt                        # nothing of its own
    idio = 0.2 * mkt + rng.normal(0.0012, 0.008, n)   # own drift
    close = np.column_stack([100 * np.exp(np.cumsum(pure_beta)),
                             100 * np.exp(np.cumsum(idio))])
    bench = 100 * np.exp(np.cumsum(mkt))
    panel = Panel(dates=pd.bdate_range("2020-01-01", periods=n).values.astype("datetime64[D]"),
                  symbols=["BETA", "IDIO"], open=close.copy(), high=close.copy(),
                  low=close.copy(), close=close.copy(), volume=np.full((n, 2), 1e9))
    bank = FeatureBank(panel, bench)
    rm = bank.get("residual_momentum")[-1]
    assert np.isfinite(rm).all()
    assert abs(rm[0]) < abs(rm[1]), \
        f"market-only stock did not have the smaller residual momentum: {rm}"


def test_vol_scaling_sheds_risk_not_just_entry_size():
    """The paper rescales the whole position; an entry-and-hold engine cannot
    resize, so it must at least SHED. Without this, vol scaling only throttles
    new entries and the legacy book rides the volatility untouched.

    Needs a multi-symbol book: with one position the gross can never exceed the
    scaled cap, and the test would pass vacuously.
    """
    n, m = 420, 12
    rng = np.random.default_rng(7)
    calm = rng.normal(0.0006, 0.004, (260, m))
    storm = rng.normal(-0.002, 0.055, (n - 260, m))   # regime break, correlated
    storm += rng.normal(0, 0.01, (n - 260, 1))        # a common shock
    close = 100.0 * np.exp(np.cumsum(np.vstack([calm, storm]), axis=0))
    panel = Panel(dates=pd.bdate_range("2020-01-01", periods=n).values.astype("datetime64[D]"),
                  symbols=[f"S{i}" for i in range(m)], open=close.copy(), high=close.copy(),
                  low=close.copy(), close=close.copy(), volume=np.full((n, m), 1e9))
    z = np.zeros((n, m), dtype=bool)
    lt = z.copy()
    lt[3:250:10, :] = True
    sig = Signals(eligible=np.ones((n, m), dtype=bool), trigger=lt,
                  score=np.ones((n, m), dtype=np.float32),
                  short_eligible=z.copy(), short_trigger=z.copy(),
                  short_score=np.zeros((n, m), dtype=np.float32),
                  regime_ok=np.ones(n, dtype=bool), atr=np.full((n, m), 1.0),
                  stop_ma=np.full((n, m), np.nan), exit_ma=np.full((n, m), np.nan),
                  gap_pct=np.zeros((n, m)), gate_pass_counts={}, n_days=n, n_symbols=m)
    g = _genome(**{"short.enabled": False, "pf.vol_scaling": True,
                   "pf.vol_target_portfolio": 0.08, "pf.vol_lookback": 100,
                   "pf.vol_scale_cap": 1.2, "exit.max_hold_days": 160,
                   "exit.stop_atr_mult": 200.0, "pf.sizing": "equal_weight",
                   "pf.max_positions": 12, "pf.max_new_per_day": 12,
                   "pf.max_sector_positions": 12, "pf.max_weight": 0.12,
                   "pf.max_gross_exposure": 1.0})
    r = run_backtest(g, panel, sig, ["Tech"] * m, _cfg(),
                     dollar_volume_20d=np.full((n, m), 1e12))
    reasons = {t.exit_reason for t in r.trades}
    assert "vol_trim" in reasons, \
        f"the book was never rescaled through a volatility regime break: {reasons}"
    assert float(np.nanmin(r.vol_scale)) < 0.9, "scaling never tightened"
    # Trimming must REDUCE a position, not end it: the trimmed name should also
    # appear with a later, non-trim exit.
    trims = [t for t in r.trades if t.exit_reason == "vol_trim"]
    later = [t for t in r.trades if t.exit_reason != "vol_trim"
             and t.symbol in {x.symbol for x in trims}]
    assert later, "every trimmed position was closed outright rather than reduced"


def test_vol_derisk_never_fires_when_scaling_is_off():
    n, m = 300, 8
    rng = np.random.default_rng(11)
    close = 100.0 * np.exp(np.cumsum(rng.normal(0.0002, 0.03, (n, m)), axis=0))
    panel = Panel(dates=pd.bdate_range("2020-01-01", periods=n).values.astype("datetime64[D]"),
                  symbols=[f"S{i}" for i in range(m)], open=close.copy(), high=close.copy(),
                  low=close.copy(), close=close.copy(), volume=np.full((n, m), 1e9))
    z = np.zeros((n, m), dtype=bool)
    lt = z.copy()
    lt[3:200:10, :] = True
    sig = Signals(eligible=np.ones((n, m), dtype=bool), trigger=lt,
                  score=np.ones((n, m), dtype=np.float32),
                  short_eligible=z.copy(), short_trigger=z.copy(),
                  short_score=np.zeros((n, m), dtype=np.float32),
                  regime_ok=np.ones(n, dtype=bool), atr=np.full((n, m), 1.0),
                  stop_ma=np.full((n, m), np.nan), exit_ma=np.full((n, m), np.nan),
                  gap_pct=np.zeros((n, m)), gate_pass_counts={}, n_days=n, n_symbols=m)
    g = _genome(**{"short.enabled": False, "pf.vol_scaling": False,
                   "pf.max_positions": 8, "pf.max_new_per_day": 8,
                   "pf.max_sector_positions": 8, "exit.stop_atr_mult": 200.0})
    r = run_backtest(g, panel, sig, ["Tech"] * m, _cfg(),
                     dollar_volume_20d=np.full((n, m), 1e12))
    assert not {"vol_derisk", "vol_trim"} & {t.exit_reason for t in r.trades}


def test_vol_trims_do_not_inflate_the_trade_count():
    """A trim is a transaction, not a new position. Counting it as a trade
    would make a risk overlay look like a change in trading frequency."""
    from strategylab.metrics import summarize

    n, m = 420, 12
    rng = np.random.default_rng(7)
    calm = rng.normal(0.0006, 0.004, (260, m))
    storm = rng.normal(-0.002, 0.055, (n - 260, m)) + rng.normal(0, 0.01, (n - 260, 1))
    close = 100.0 * np.exp(np.cumsum(np.vstack([calm, storm]), axis=0))
    panel = Panel(dates=pd.bdate_range("2020-01-01", periods=n).values.astype("datetime64[D]"),
                  symbols=[f"S{i}" for i in range(m)], open=close.copy(), high=close.copy(),
                  low=close.copy(), close=close.copy(), volume=np.full((n, m), 1e9))
    z = np.zeros((n, m), dtype=bool)
    lt = z.copy(); lt[3:250:10, :] = True
    sig = Signals(eligible=np.ones((n, m), dtype=bool), trigger=lt,
                  score=np.ones((n, m), dtype=np.float32),
                  short_eligible=z.copy(), short_trigger=z.copy(),
                  short_score=np.zeros((n, m), dtype=np.float32),
                  regime_ok=np.ones(n, dtype=bool), atr=np.full((n, m), 1.0),
                  stop_ma=np.full((n, m), np.nan), exit_ma=np.full((n, m), np.nan),
                  gap_pct=np.zeros((n, m)), gate_pass_counts={}, n_days=n, n_symbols=m)
    g = _genome(**{"short.enabled": False, "pf.vol_scaling": True,
                   "pf.vol_target_portfolio": 0.08, "pf.vol_lookback": 100,
                   "pf.vol_scale_cap": 1.2, "exit.max_hold_days": 160,
                   "exit.stop_atr_mult": 200.0, "pf.sizing": "equal_weight",
                   "pf.max_positions": 12, "pf.max_new_per_day": 12,
                   "pf.max_sector_positions": 12, "pf.max_weight": 0.12})
    r = run_backtest(g, panel, sig, ["Tech"] * m, _cfg(),
                     dollar_volume_20d=np.full((n, m), 1e12))
    m_ = summarize(r)
    assert m_["n_vol_trims"] > 0, "test is vacuous — no trims occurred"
    assert m_["n_trades"] < m_["n_transactions"]
    assert m_["n_trades"] == m_["n_transactions"] - m_["n_vol_trims"]
    # Costs must still count every transaction, trims included.
    assert m_["total_costs"] >= sum(t.costs for t in r.trades
                                    if t.exit_reason != "vol_trim")
