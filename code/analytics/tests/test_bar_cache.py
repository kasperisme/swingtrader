"""The FMP daily-bar store: what it fetches, what it serves from disk, and when
it refuses to trust itself (provisional bars, re-based history, FMP failures)."""

from datetime import date, datetime, timedelta, timezone

import pandas as pd
import pytest

from services.screener import bar_cache
from services.screener.bar_cache import BarCache


class FakeFMP:
    """Business-day bars with close = day number; ``split`` divides history like
    FMP's back-adjustment after a 2:1 split."""

    def __init__(self, listed: date = date(2020, 1, 1)):
        self.calls: list[tuple[str, str]] = []
        self.listed = listed
        self.split = 1.0
        self.today_close = None     # override the last bar's close (intraday)
        self.fail = False
        self.empty = False

    def __call__(self, ticker, start, end):
        self.calls.append((start, end))
        if self.fail:
            raise Exception("API response on chart: 429")
        if self.empty:
            return pd.DataFrame()
        days = pd.bdate_range(max(pd.Timestamp(start), pd.Timestamp(self.listed)), end)
        rows = [{"date": d.strftime("%Y-%m-%d"), "open": 1.0, "high": 1.0, "low": 1.0,
                 "close": (d.toordinal() % 1000 + 100) / self.split, "volume": 1000}
                for d in days]
        if rows and self.today_close is not None:
            rows[-1]["close"] = self.today_close
        return pd.DataFrame(rows[::-1])  # FMP answers newest first


def et(y, m, d, hour):
    """A wall-clock moment in New York, as UTC."""
    return datetime(y, m, d, hour, tzinfo=bar_cache._ET).astimezone(timezone.utc)


@pytest.fixture
def clock():
    class Clock:
        now = et(2026, 9, 14, 21)  # Monday evening, the day's bar is settled
    return Clock


@pytest.fixture
def setup(tmp_path, clock, monkeypatch):
    monkeypatch.delenv("FMP_BAR_CACHE", raising=False)
    fmp = FakeFMP()
    cache = BarCache(fmp, tmp_path, now=lambda: clock.now)
    return fmp, cache


def test_first_call_fetches_the_window_then_serves_from_disk(setup):
    fmp, cache = setup
    a = cache.get("AAPL", "2025-09-14", "2026-09-14")
    b = cache.get("AAPL", "2025-09-14", "2026-09-14")
    c = cache.get("AAPL", "2026-01-01", "2026-06-30")  # inside coverage
    assert fmp.calls == [("2025-09-14", "2026-09-14")]
    pd.testing.assert_frame_equal(a, b)
    assert a["date"].is_monotonic_increasing and a["date"].iloc[-1] == pd.Timestamp("2026-09-14")
    assert c["date"].min() >= pd.Timestamp("2026-01-01") and c["date"].max() <= pd.Timestamp("2026-06-30")


def test_next_day_fetches_only_an_overlapping_tail(setup, clock):
    fmp, cache = setup
    cache.get("AAPL", "2025-09-14", "2026-09-14")
    clock.now = et(2026, 9, 15, 21)
    out = cache.get("AAPL", "2025-09-15", "2026-09-15")
    assert fmp.calls[-1] == ((date(2026, 9, 14) - timedelta(days=bar_cache.OVERLAP_DAYS)).isoformat(), "2026-09-15")
    assert out["date"].iloc[-1] == pd.Timestamp("2026-09-15")
    assert out["date"].is_unique


def test_earlier_start_fetches_only_the_head(setup):
    fmp, cache = setup
    cache.get("AAPL", "2026-01-01", "2026-09-14")
    out = cache.get("AAPL", "2023-09-14", "2026-09-14")  # nis_short's 3-year window
    assert fmp.calls[-1] == ("2023-09-14", (date(2026, 1, 1) + timedelta(days=bar_cache.OVERLAP_DAYS)).isoformat())
    assert out["date"].iloc[0] == pd.Timestamp("2023-09-14") and out["date"].is_unique
    cache.get("AAPL", "2024-01-01", "2026-09-14")
    assert len(fmp.calls) == 2


def test_intraday_bar_is_provisional(setup, clock):
    fmp, cache = setup
    clock.now = et(2026, 9, 14, 11)  # market open: today's candle still moving
    fmp.today_close = 1.23
    assert cache.get("AAPL", "2026-01-01", "2026-09-14")["close"].iloc[-1] == 1.23

    clock.now = et(2026, 9, 14, 11) + timedelta(minutes=5)  # a board starting alongside
    cache.get("AAPL", "2026-01-01", "2026-09-14")
    assert len(fmp.calls) == 1, "provisional bar shared inside the TTL"

    clock.now = et(2026, 9, 14, 17)  # after the close
    fmp.today_close = None
    out = cache.get("AAPL", "2026-01-01", "2026-09-14")
    assert len(fmp.calls) == 2, "provisional bar refetched once stale"
    assert out["close"].iloc[-1] != 1.23


def test_past_windows_never_refetch(setup, clock):
    fmp, cache = setup
    cache.get("AAPL", "2026-07-01", "2026-09-05")  # a point-in-time replay
    clock.now = et(2026, 9, 20, 9)
    cache.get("AAPL", "2026-07-01", "2026-09-05")
    assert len(fmp.calls) == 1


def test_split_rebases_history_and_triggers_a_whole_refetch(setup, clock):
    fmp, cache = setup
    cache.get("AAPL", "2025-09-14", "2026-09-14")
    fmp.split = 2.0
    clock.now = et(2026, 9, 15, 21)
    out = cache.get("AAPL", "2025-09-15", "2026-09-15")
    assert fmp.calls[-1] == ("2025-09-15", "2026-09-15"), "tail disagreed, so the window was refetched whole"
    first = pd.Timestamp("2025-09-15")
    assert out.loc[out["date"] == first, "close"].iloc[0] == (first.toordinal() % 1000 + 100) / 2.0


def test_fmp_error_raises_and_writes_nothing(setup, clock, tmp_path):
    fmp, cache = setup
    fmp.fail = True
    with pytest.raises(Exception, match="429"):
        cache.get("AAPL", "2026-01-01", "2026-09-14")
    assert not list(tmp_path.iterdir())


def test_empty_answer_over_stored_bars_is_a_failure_not_a_delisting(setup, clock):
    fmp, cache = setup
    cache.get("AAPL", "2026-01-01", "2026-09-14")
    fmp.empty = True
    clock.now = et(2026, 9, 15, 21)
    with pytest.raises(RuntimeError, match="no bars"):
        cache.get("AAPL", "2026-01-01", "2026-09-15")


def test_ticker_listed_after_the_start_is_not_refetched_for_its_missing_head(tmp_path, clock):
    fmp = FakeFMP(listed=date(2026, 6, 1))
    cache = BarCache(fmp, tmp_path, now=lambda: clock.now)
    out = cache.get("NEWCO", "2025-09-14", "2026-09-14")
    cache.get("NEWCO", "2025-09-14", "2026-09-14")
    assert len(fmp.calls) == 1
    assert out["date"].iloc[0] >= pd.Timestamp("2026-06-01")


def test_future_end_is_capped_at_today(setup):
    fmp, cache = setup
    cache.get("AAPL", "2026-09-01", "2026-12-31")
    assert fmp.calls == [("2026-09-01", "2026-09-14")]


def test_disabled_fetches_every_time(tmp_path, clock, monkeypatch):
    monkeypatch.setenv("FMP_BAR_CACHE", "0")
    fmp = FakeFMP()
    cache = BarCache(fmp, tmp_path, now=lambda: clock.now)
    cache.get("AAPL", "2026-01-01", "2026-09-14")
    cache.get("AAPL", "2026-01-01", "2026-09-14")
    assert len(fmp.calls) == 2 and not list(tmp_path.iterdir())


def test_callers_get_a_copy_they_can_mutate(setup):
    _, cache = setup
    a = cache.get("AAPL", "2026-01-01", "2026-09-14")
    a["SMA200"] = 0.0  # what technical.get_daily_chart does to it
    assert "SMA200" not in cache.get("AAPL", "2026-01-01", "2026-09-14").columns


def test_screener_client_uses_the_store(tmp_path, monkeypatch, clock):
    from services.screener import fmp as fmp_mod

    monkeypatch.setenv("APIKEY", "x")
    fake = FakeFMP()
    client = fmp_mod.fmp()
    client._bars = BarCache(fake, tmp_path, now=lambda: clock.now)
    df = client.daily_chart("AAPL", "2026-01-01", "2026-09-14")
    client.daily_chart("AAPL", "2026-01-01", "2026-09-14")
    assert len(fake.calls) == 1 and not df.empty
    fake.listed = date(2027, 1, 1)
    with pytest.raises(fmp_mod.RequestError, match="no daily bars"):
        client.daily_chart("ZZZZ", "2026-01-01", "2026-09-14")
