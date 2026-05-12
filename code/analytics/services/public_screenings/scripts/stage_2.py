"""Stage 2 screener — placeholder hardcoded logic.

Replace the body of `run()` with real Mark-Minervini-style stage-2 logic
(price > MA50 > MA150 > MA200, MA200 rising 1+ month, 52-week high proximity,
relative strength, etc.). For now this returns a fixed result so we can
validate the plumbing end-to-end.
"""

from __future__ import annotations

from ..types import ScreeningResult


def run(client, screening: dict) -> ScreeningResult:
    return ScreeningResult(
        triggered=True,
        summary=(
            "<b>Stage 2 candidates (placeholder)</b>\n\n"
            "Real logic not yet wired. Replace scripts/stage_2.py to query "
            "price + moving averages and emit a stock list here."
        ),
        data_used={"placeholder": True},
    )
