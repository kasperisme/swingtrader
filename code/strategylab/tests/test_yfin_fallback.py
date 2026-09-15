"""yfinance standing in for FMP: the rows it produces and when it is reached.

Offline — a fake `yf.Ticker` is patched in. The properties that matter are the
ones a wrong mapping would break silently rather than loudly: one target per
firm (not one per rating action), the statement's FCF rather than Yahoo's
levered figure, and FMP's quota error tripping the breaker instead of burning
retries.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from strategylab.data import fmp, yfin


class FakeTicker:
    info = {"currentPrice": 505.41, "longName": "Microsoft Corporation",
            "industry": "Software - Infrastructure", "sector": "Technology",
            "longBusinessSummary": "Makes software.", "marketCap": 3.75e12,
            "enterpriseValue": 3.73e12, "totalDebt": 1.29e11, "totalCash": 7.7e10,
            "trailingPE": 36.0, "enterpriseToRevenue": 11.2,
            "enterpriseToEbitda": 22.0, "freeCashflow": 1.65e10}
    income_stmt = pd.DataFrame(
        {pd.Timestamp("2026-06-30"): [331.8e9, 228.0e9, 150.0e9, 190.0e9],
         pd.Timestamp("2025-06-30"): [281.7e9, 193.0e9, 128.0e9, 160.0e9]},
        index=["Total Revenue", "Gross Profit", "Operating Income", "EBITDA"])
    cashflow = pd.DataFrame({pd.Timestamp("2026-06-30"): [67.0e9]},
                            index=["Free Cash Flow"])
    upgrades_downgrades = pd.DataFrame(
        {"Firm": ["Stifel", "B of A Securities", "Stifel", "Mizuho", "Old Firm"],
         "currentPriceTarget": [530.0, 600.0, 450.0, 0.0, 300.0]},
        index=pd.DatetimeIndex(["2026-09-04", "2026-09-01", "2026-07-30",
                                "2026-07-15", "2026-01-02"], name="GradeDate"))

    def history(self, start=None, auto_adjust=False):
        idx = pd.DatetimeIndex(["2026-07-30", "2026-08-31", "2026-09-04"])
        return pd.DataFrame({"Close": [520.0, 498.0, 495.0]}, index=idx)


@pytest.fixture
def fake(monkeypatch):
    t = FakeTicker()
    monkeypatch.setattr(yfin, "_ticker", lambda s: t)
    monkeypatch.setattr(yfin, "_info", lambda s: dict(t.info))
    return t


def test_targets_keep_the_latest_per_firm_inside_the_window(fake):
    rows = yfin.price_targets("MSFT", as_of=date(2026, 9, 14), window_days=120)
    got = {r["analystCompany"]: r["priceTarget"] for r in rows}
    # Stifel's withdrawn $450 is gone, Mizuho's grade-only row has no target,
    # and January is outside the window.
    assert got == {"Stifel": 530.0, "B of A Securities": 600.0}


def test_targets_are_point_in_time(fake):
    rows = yfin.price_targets("MSFT", as_of=date(2026, 8, 1), window_days=120)
    assert [(r["analystCompany"], r["priceTarget"]) for r in rows] == [("Stifel", 450.0)]


def test_price_when_posted_is_the_close_on_or_before_publication(fake):
    rows = yfin.price_targets("MSFT", as_of=date(2026, 9, 14))
    by_firm = {r["analystCompany"]: r["priceWhenPosted"] for r in rows}
    assert by_firm == {"Stifel": 495.0, "B of A Securities": 498.0}


def test_fcf_comes_from_the_statement_not_levered_fcf(fake):
    assert yfin.cash_flow_statement("MSFT")[0]["freeCashFlow"] == 67.0e9
    km = yfin.key_metrics_ttm("MSFT")[0]
    assert km["freeCashFlowYieldTTM"] == pytest.approx(67.0e9 / 3.75e12)


def test_fetch_financials_falls_back_when_fmp_is_out(fake, monkeypatch):
    import importlib
    implied = importlib.import_module("strategylab.social.implied")

    def dead(*_a, **_k):
        raise fmp.FMPError("FMP bandwidth quota exhausted")
    monkeypatch.setattr(implied.fmp, "_get", dead)

    f = implied.fetch_financials("MSFT")
    assert f.price == 505.41
    assert f.revenue == 331.8e9
    assert f.revenue_yoy == pytest.approx(331.8 / 281.7 - 1)
    assert f.fcf_margin == pytest.approx(67.0 / 331.8)
    assert f.enterprise_value == 3.73e12
    assert f.source.startswith("yfinance")
    assert implied.implied("MSFT", fin=f).implied_revenue_cagr is not None


def test_business_profile_built_without_fmp_is_not_cached(fake, monkeypatch, tmp_path):
    import importlib
    business = importlib.import_module("strategylab.social.business")

    def dead(*_a, **_k):
        raise fmp.FMPError("FMP bandwidth quota exhausted")
    monkeypatch.setattr(business.fmp, "_get", dead)

    store = business.BusinessStore(cache_dir=tmp_path)
    bp = store.build("MSFT")
    assert bp.company == "Microsoft Corporation" and bp.revenue == 331.8e9
    assert not bp.product_segments
    assert store.load("MSFT") is None          # rebuilt with segments once FMP is back


def test_bandwidth_quota_trips_the_breaker_without_retrying(monkeypatch):
    calls = []

    class Resp:
        status_code = 429
        text = '{"Error Message": "Bandwidth Limit Reach . Please upgrade"}'

    monkeypatch.setattr(fmp, "_BANDWIDTH_EXHAUSTED", [])
    monkeypatch.setattr(fmp, "fmp_key", lambda: "k")
    monkeypatch.setattr(fmp, "_throttle", lambda: None)
    monkeypatch.setattr(fmp.requests, "get", lambda *a, **k: calls.append(1) or Resp())

    with pytest.raises(fmp.FMPError, match="bandwidth"):
        fmp._get("https://x/a")
    with pytest.raises(fmp.FMPError, match="bandwidth"):
        fmp._get("https://x/b")
    assert len(calls) == 1
