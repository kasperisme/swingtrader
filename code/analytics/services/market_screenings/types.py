"""Shared types for market screening scripts."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class ScreeningResult:
    """The return contract every market screening script must satisfy.

    Fields mirror the persisted columns on market_screening_results.
    `ticker_count` is used by the Telegram fan-out to render a tight
    "name + count" notification; set it to the number of tickers in the result
    (passing tickers, alerts, however the script wants to count).
    """

    triggered: bool
    summary: str | None = None
    data_used: dict[str, Any] = field(default_factory=dict)
    ticker_count: int | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
