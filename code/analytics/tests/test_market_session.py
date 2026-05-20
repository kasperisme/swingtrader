"""NYSE trading-session gate for scheduled screenings."""

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from services.agent.engine import _is_market_open


@patch("services.agent.engine.datetime")
def test_nyse_open_on_weekday(mock_datetime):
    mock_datetime.now.return_value = datetime(
        2026, 5, 19, 10, 30, tzinfo=ZoneInfo("America/New_York")
    )
    assert _is_market_open("nyse") is True


@patch("services.agent.engine.datetime")
def test_nyse_closed_on_weekend(mock_datetime):
    mock_datetime.now.return_value = datetime(
        2026, 5, 17, 10, 30, tzinfo=ZoneInfo("America/New_York")
    )
    assert _is_market_open("nyse") is False


@patch("services.agent.engine.datetime")
def test_nyse_closed_after_hours(mock_datetime):
    mock_datetime.now.return_value = datetime(
        2026, 5, 19, 18, 0, tzinfo=ZoneInfo("America/New_York")
    )
    assert _is_market_open("nyse") is False
