"""The FIM screener universe and the Tier-2 flow ingest.

The ETF-ownership floor is the filter most likely to be quietly dropped, and
dropping it is what makes a Tier-2 test come back null for the wrong reason:
a stock with no mechanical holders has no arbitrage-induced trading to measure,
so including it dilutes the estimate toward zero by construction.
"""

import json

import numpy as np
import pandas as pd
import pytest

from strategylab.data.prices import Panel
from strategylab.flow.etf_flow import ETFFlowStore, MIN_SO_CHANGE
from strategylab.flow.universe import (UniverseSpec, build_universe, etf_ownership,
                                       _company_key)


def _panel(n=800, m=6, seed=0):
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2021-01-01", periods=n).values.astype("datetime64[D]")
    close = 50.0 * np.exp(np.cumsum(rng.normal(0.0003, 0.015, (n, m)), axis=0))
    sp = np.abs(rng.normal(0, 0.01, (n, m)))
    return Panel(dates=dates, symbols=[f"S{i}" for i in range(m)],
                 open=close, high=close * (1 + sp), low=close * (1 - sp),
                 close=close, volume=rng.lognormal(14, 0.4, (n, m)))


def _inputs(panel, cap=10e9, adv=50e6, shares=1e8):
    n, m = panel.close.shape
    return (np.full((n, m), shares), np.full((n, m), adv), np.full((n, m), cap))


def test_market_cap_band_is_enforced_per_bar():
    p = _panel()
    shares, adv, cap = _inputs(p)
    cap[:, 0] = 1e9        # below the floor
    cap[:, 1] = 80e9       # above the ceiling
    res = build_universe(p, shares, adv, cap, UniverseSpec(min_etf_ownership=0.0))
    assert not res.mask[:, 0].any(), "sub-$2B name admitted"
    assert not res.mask[:, 1].any(), "mega-cap admitted"
    assert res.mask[:, 2].any()


def test_liquidity_and_price_floors_bind():
    p = _panel()
    shares, adv, cap = _inputs(p)
    adv[:, 0] = 1e6                     # below the $10M ADV floor
    res = build_universe(p, shares, adv, cap, UniverseSpec(min_etf_ownership=0.0))
    assert not res.mask[:, 0].any()

    cheap = _panel(seed=2)
    cheap.close[:] = 2.0                # below the $5 floor
    s2, a2, c2 = _inputs(cheap)
    res2 = build_universe(cheap, s2, a2, c2, UniverseSpec(min_etf_ownership=0.0))
    assert not res2.mask.any()


def test_etf_ownership_floor_is_applied_and_is_the_ait_precondition():
    p = _panel()
    shares, adv, cap = _inputs(p, shares=1e8)

    def loader(sym):
        # S0 is heavily indexed; S1 barely; the rest moderately.
        held = {"S0": 2e7, "S1": 1e5}.get(sym, 6e6)
        return [{"etf": "IJH", "weight": 0.01, "shares": held, "market_value": 1e9}]

    res = build_universe(p, shares, adv, cap,
                         UniverseSpec(min_etf_ownership=0.03), weights_loader=loader)
    assert res.mask[:, 0].any(), "20% ETF-held name should qualify"
    assert not res.mask[:, 1].any(), "0.1% ETF-held name has no measurable AIT"
    assert any("ETF ownership" in k for k in res.funnel)


def test_etf_ownership_uses_the_latest_share_count():
    p = _panel(m=2)
    shares = np.full(p.close.shape, np.nan)
    shares[-1, :] = 1e8
    own = etf_ownership(list(p.symbols), shares,
                        lambda s: [{"etf": "X", "weight": 0.01, "shares": 5e6}])
    assert np.allclose(own, 0.05)


def test_earnings_blackout_removes_a_window_around_the_announcement():
    p = _panel()
    shares, adv, cap = _inputs(p)
    grid = pd.DatetimeIndex(p.dates)
    ann = grid[400]
    res = build_universe(p, shares, adv, cap,
                         UniverseSpec(min_etf_ownership=0.0, earnings_exclusion_days=10,
                                      min_history_days=100),
                         earnings_dates={s: [ann] for s in p.symbols})
    assert not res.mask[395:405, 0].any(), "blackout not applied around the announcement"
    assert res.mask[350, 0], "blackout leaked outside its window"
    # S1's own announcement is elsewhere, so its window round S0's date is open.
    res2 = build_universe(p, shares, adv, cap,
                          UniverseSpec(min_etf_ownership=0.0, earnings_exclusion_days=10,
                                       min_history_days=100),
                          earnings_dates={s: ([ann] if s == "S0" else [grid[100]])
                                          for s in p.symbols})
    assert res2.mask[395:405, 1].any(), "blackout hit the wrong symbol"


def test_partial_earnings_coverage_skips_the_blackout_rather_than_biasing():
    """Applying a blackout to only the names that happen to have data penalises
    exactly those names — a selection effect dressed as a filter."""
    p = _panel(m=4)
    shares, adv, cap = _inputs(p)
    grid = pd.DatetimeIndex(p.dates)
    res = build_universe(p, shares, adv, cap,
                         UniverseSpec(min_etf_ownership=0.0, earnings_exclusion_days=10,
                                      min_history_days=100),
                         earnings_dates={"S0": [grid[400]]})     # 1 of 4 = 25%
    assert res.mask[395:405, 0].any(), "blackout applied under partial coverage"
    assert "SKIPPED" in str(res.funnel.get("earnings blackout applied", ""))


def test_full_earnings_coverage_does_apply_the_blackout():
    p = _panel(m=2)
    shares, adv, cap = _inputs(p)
    grid = pd.DatetimeIndex(p.dates)
    res = build_universe(p, shares, adv, cap,
                         UniverseSpec(min_etf_ownership=0.0, earnings_exclusion_days=10,
                                      min_history_days=100),
                         earnings_dates={"S0": [grid[400]], "S1": [grid[500]]})
    assert not res.mask[395:405, 0].any()
    assert not res.mask[495:505, 1].any()


def test_dual_class_dedupe_keeps_the_more_liquid_line():
    p = _panel(m=2)
    shares, adv, cap = _inputs(p)
    adv[:, 0] = 20e6
    adv[:, 1] = 90e6                        # the liquid line
    meta = {"S0": {"companyName": "Acme Corp Class A"},
            "S1": {"companyName": "Acme Corp Class B"}}
    res = build_universe(p, shares, adv, cap,
                         UniverseSpec(min_etf_ownership=0.0), listing_meta=meta)
    assert res.mask[:, 1].any() and not res.mask[:, 0].any()


def test_company_key_collapses_share_classes():
    assert _company_key({"companyName": "Acme Corp Class A"}) == \
           _company_key({"companyName": "Acme Corp Class B"})


def test_adr_reit_spac_exclusions():
    p = _panel(m=4)
    shares, adv, cap = _inputs(p)
    meta = {"S0": {"companyName": "Foo ADR"},
            "S1": {"companyName": "Bar Real Estate Investment Trust"},
            "S2": {"companyName": "Baz Acquisition Corp"},
            "S3": {"companyName": "Ordinary Industries Inc"}}
    res = build_universe(p, shares, adv, cap,
                         UniverseSpec(min_etf_ownership=0.0), listing_meta=meta)
    for j in (0, 1, 2):
        assert not res.mask[:, j].any(), f"S{j} should have been excluded"
    assert res.mask[:, 3].any()


def test_history_requirement():
    p = _panel(n=300)
    shares, adv, cap = _inputs(p)
    res = build_universe(p, shares, adv, cap,
                         UniverseSpec(min_etf_ownership=0.0, min_history_days=504))
    assert not res.mask.any(), "names with under 2 years of history were admitted"


# ---------------------------------------------------------------- Tier 2 ---
def test_etf_flow_ignores_sub_threshold_share_count_noise(tmp_path, monkeypatch):
    store = ETFFlowStore()
    monkeypatch.setattr(store, "flow_dir", tmp_path)

    dates = pd.bdate_range("2024-01-01", periods=10)
    # Share count drifts by rounding noise, then steps up on a real creation
    # and STAYS there — a creation is a level change, not a one-day blip.
    so = np.full(10, 1e8)
    so[5] = 1e8 * (1 + MIN_SO_CHANGE / 10)      # rounding noise
    so[7:] = 1e8 * 1.05                         # a genuine creation
    mc = [{"date": d.strftime("%Y-%m-%d"), "marketCap": s * 100.0}
          for d, s in zip(dates, so)]
    px = [{"date": d.strftime("%Y-%m-%d"), "close": 100.0} for d in dates]
    monkeypatch.setattr("strategylab.flow.etf_flow.fmp._get", lambda *a, **k: mc)
    monkeypatch.setattr("strategylab.flow.etf_flow.fmp.eod_raw", lambda *a, **k: px)

    df = store.fetch_flow("TEST", "2024-01-01", "2024-01-15")
    nonzero = df[df["flow_usd"].abs() > 0]
    assert len(nonzero) == 1, f"rounding noise was treated as flow: {nonzero}"
    assert nonzero["flow_usd"].iloc[0] > 0
    assert abs(nonzero["flow_usd"].iloc[0] - 5e8) < 1e6


def test_etf_ranking_uses_dollars_not_weight_percentage(tmp_path, monkeypatch):
    """A $30m thematic fund holding 8% of one name must not outrank a broad
    index fund that actually moves the stock."""
    store = ETFFlowStore()
    monkeypatch.setattr(store, "weight_dir", tmp_path)
    (tmp_path / "AAA.json").write_text(json.dumps([
        {"etf": "TINY", "weight": 0.08, "market_value": 3e7},
        {"etf": "BROAD", "weight": 0.002, "market_value": 5e9},
    ]))
    ranked = store.etfs_referenced(["AAA"])
    assert ranked[0] == "BROAD", f"ranked by weight, not dollars: {ranked}"
