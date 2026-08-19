"""Charts must render without a display and without silently dropping panels."""

import numpy as np
import pandas as pd
import pytest

from strategylab.backtest import run_backtest
from strategylab.charts import contact_sheet, performance_charts, search_charts
from strategylab.config import LabConfig
from strategylab.features import FeatureBank
from strategylab.genome import default_genome
from strategylab.ledger import Ledger, Trial
from strategylab.strategy import build_signals
from tests.conftest import synthetic_panel


@pytest.fixture(scope="module")
def result():
    panel = synthetic_panel(n_days=900, n_symbols=40, seed=4)
    g = default_genome().patched({
        "universe.min_dollar_vol_20d": 1e5, "universe.min_price": 2.0,
        "regime.enabled": False, "gates.rs_rank_min": 30,
        "gates.min_up_down_vol": 0.5,
    })
    bank = FeatureBank(panel, panel.close[:, 0])
    sectors = ["Tech" if i % 2 else "Health" for i in range(len(panel.symbols))]
    sig = build_signals(g, bank, sectors, panel.close[:, 0])
    return run_backtest(g, panel, sig, sectors, LabConfig(),
                        rs_rank=bank.get("rs_rank"),
                        adr=bank.get("adr_pct", length=20),
                        dollar_volume_20d=bank.get("dollar_volume_20d")), panel


def test_performance_charts_render_all_panels(result, tmp_path):
    res, panel = result
    bench = np.zeros(len(res.equity))
    bench[1:] = panel.close[1:, 0] / panel.close[:-1, 0] - 1.0
    folds = [{"fold": f"fold{i}", "start": "2015-01-01", "end": "2016-01-01",
              "sharpe": s, "return": 0.1, "max_drawdown": 0.1, "n_trades": 30}
             for i, s in enumerate([0.8, -0.2, 1.1])]
    paths = performance_charts(res, {}, tmp_path, bench_returns=bench,
                               fold_metrics=folds, label="test")
    names = {p.name for p in paths}
    assert {"perf_equity.png", "perf_folds.png", "perf_trades.png",
            "perf_exposure.png"} <= names
    for p in paths:
        assert p.exists() and p.stat().st_size > 5_000, f"{p.name} looks empty"


def test_performance_charts_survive_a_strategy_with_no_trades(tmp_path):
    """A genome that never fires must not crash the reporting path."""
    from strategylab.backtest import BacktestResult
    n = 200
    res = BacktestResult(
        dates=pd.bdate_range("2020-01-01", periods=n).values.astype("datetime64[D]"),
        equity=np.full(n, 100_000.0), cash=np.full(n, 100_000.0),
        exposure=np.zeros(n), n_positions=np.zeros(n), returns=np.zeros(n),
        trades=[], initial_equity=100_000.0)
    paths = performance_charts(res, {}, tmp_path, label="empty")
    assert any(p.name == "perf_equity.png" for p in paths)


def test_search_charts_from_a_ledger(tmp_path):
    ledger = Ledger(tmp_path / "l.sqlite")
    g = default_genome()
    for i in range(6):
        ledger.record(Trial(genome=g.patched({"pf.max_positions": 5 + i}),
                            rung=1, valid=True, reward=0.1 * i, sharpe=0.2 * i,
                            metrics={"sharpe": 0.2 * i}, source="llm" if i % 2 else "mutate",
                            operator="tune_exits", iteration=i))
    paths = search_charts(tmp_path / "l.sqlite", tmp_path / "charts")
    assert any(p.name == "search_reward.png" for p in paths)
    for p in paths:
        assert p.stat().st_size > 5_000


def test_search_charts_on_an_empty_ledger(tmp_path):
    ledger = Ledger(tmp_path / "empty.sqlite")  # noqa: F841
    assert search_charts(tmp_path / "empty.sqlite", tmp_path / "c") == []


def test_contact_sheet_references_every_image(tmp_path):
    from pathlib import Path
    imgs = []
    for name in ("a.png", "b.png"):
        p = tmp_path / name
        p.write_bytes(b"x")
        imgs.append(p)
    out = contact_sheet(imgs, tmp_path / "r.html", "Title", "Sub")
    html = out.read_text()
    assert "Title" in html and "Sub" in html
    for p in imgs:
        assert p.name in html
    # Theme-aware and self-contained: no external asset hosts.
    assert "prefers-color-scheme" in html
    assert "http://" not in html and "https://" not in html


def test_side_attribution_chart_renders_when_shorts_are_present(tmp_path):
    """A short sleeve must be visible in the reporting, not averaged away."""
    from tests.test_short_sleeve import _flat_panel, _genome, _run, _signals

    px = np.concatenate([np.full(3, 100.0), np.full(25, 85.0)])
    panel = _flat_panel(px)
    res = _run(panel, _signals(panel, short_at=1),
               _genome(**{"short.max_hold_days": 10, "short.stop_atr_mult": 60.0}))
    paths = performance_charts(res, {}, tmp_path, label="mixed")
    assert any(p.name == "perf_sides.png" for p in paths), \
        "short trades present but no side-attribution chart"


def test_side_chart_is_skipped_for_a_long_only_book(result, tmp_path):
    res, _panel = result
    paths = performance_charts(res, {}, tmp_path, label="long only")
    assert not any(p.name == "perf_sides.png" for p in paths)
