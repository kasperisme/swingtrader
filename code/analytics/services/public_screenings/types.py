"""Shared types for public screening scripts."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class ScreeningResult:
    """The return contract every public screening script must satisfy.

    Fields mirror the persisted columns on public_screening_results.
    """

    triggered: bool
    summary: str | None = None
    data_used: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
