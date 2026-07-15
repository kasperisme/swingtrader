"""Registry mapping script_key → callable.

To add a new market screening:
  1. Write `scripts/<key>.py` exporting `def run(client, screening) -> ScreeningResult`
  2. Register it below.
  3. Insert a row in market_screenings with script_key = "<key>" via the admin UI.
"""

from __future__ import annotations

from typing import Callable

from .scripts import (
    ai_supercycle,
    hormuz_winners,
    insider_congress,
    ipo_screener,
    nis_fundamentals,
    nis_momentum,
    nis_short,
    stage_2,
    test_aapl,
)
from .types import ScreeningResult


ScriptFn = Callable[[object, dict], ScreeningResult]


SCRIPTS: dict[str, ScriptFn] = {
    "ai_supercycle":     ai_supercycle.run,
    "hormuz_winners":    hormuz_winners.run,
    "insider_congress":  insider_congress.run,
    "ipo_screener":      ipo_screener.run,
    "nis_fundamentals":  nis_fundamentals.run,
    "nis_momentum":      nis_momentum.run,
    "nis_short":         nis_short.run,
    "stage_2":           stage_2.run,
    "test_aapl":         test_aapl.run,
}


def get_script(script_key: str) -> ScriptFn | None:
    return SCRIPTS.get(script_key)


def list_script_keys() -> list[str]:
    return sorted(SCRIPTS.keys())
