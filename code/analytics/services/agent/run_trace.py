"""
run_trace.py — ordered event log for a single screening run.

A ``RunTrace`` is a plain in-memory recorder threaded through the screening
engine and the multi-ticker pipeline. Each stage appends a compact event
(classify → plan → fetch → analytics → eval → conclude); the whole log is
written to ``user_screening_results.trace`` so a run can be reconstructed from
the database — including runs that errored or timed out.

Crucially the recorder is created in the *synchronous* engine frame and passed
into the async pipeline by reference. When a wall-clock timeout cancels the
pipeline coroutine, the events appended before cancellation remain in the
recorder, so the failed run still persists the sequence that led up to it.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any


class RunTrace:
    """Append-only, ordered list of run events with relative timestamps."""

    def __init__(self) -> None:
        self._t0 = time.monotonic()
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.events: list[dict[str, Any]] = []

    def event(self, stage: str, event: str, **detail: Any) -> None:
        """Record one event. ``detail`` must be JSON-serialisable (kept compact).

        asyncio is single-threaded, so concurrent batches appending here never
        race; ``seq`` stays monotonic in completion order.
        """
        self.events.append(
            {
                "seq": len(self.events),
                "dt": round(time.monotonic() - self._t0, 2),
                "stage": stage,
                "event": event,
                **detail,
            }
        )

    def elapsed(self) -> float:
        return round(time.monotonic() - self._t0, 2)

    def as_dict(self) -> dict[str, Any]:
        """Serialise for the ``trace`` JSONB column."""
        return {
            "started_at": self.started_at,
            "elapsed": self.elapsed(),
            "event_count": len(self.events),
            "events": self.events,
        }
