"""Dummy screening for end-to-end testing.

Returns AAPL as a single passing ticker every run. No external calls, no
heavy compute — instant. Use this to validate the full flow:
  - public_screening_results row inserted
  - user_screening_results fan-out to subscribers
  - Telegram notification fired
"""

from __future__ import annotations

from ..types import ScreeningResult


def run(client, screening: dict) -> ScreeningResult:  # noqa: ARG001
    return ScreeningResult(
        triggered=True,
        summary="<b>Test screening (dummy)</b>\n\n• <b>AAPL</b> — Technology",
        ticker_count=1,
        data_used={
            "passed": 1,
            "symbols": [
                {"symbol": "AAPL", "sector": "Technology", "subSector": "Consumer Electronics"},
            ],
        },
    )
