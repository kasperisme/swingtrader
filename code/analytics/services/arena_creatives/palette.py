"""
palette — the arena's "club colours".

A league table only reads at thumbnail size if a given competitor is the SAME
colour in every asset, every week. So the mapping lives here as data rather
than being derived from a rotating categorical palette (the way
``viral_reels/theme.ts`` cycles ``VIVID`` by entity index) — that rotation is
right for anonymous clusters and wrong for a fixed roster of nine, where the
whole point is that the audience learns who the amber one is.

Two deliberate choices:

* **The controls are colourless.** ``jack-boggle`` (buy SPY, hold) and
  ``burton-malarkey`` (seeded random) get steel and slate; every LLM strategy
  gets a saturated hue. The single most important fact about the board — that a
  non-intelligent baseline is beating thinking agents — then survives being
  seen for 400ms with the sound off, before a word of caption is read.
* **Three-letter codes.** Football-table grammar. They fit the 9:16 crop, the
  form pills and a future score bug, where a full name does not.

An unknown slug degrades to a neutral rather than raising: a roster addition
should not be able to break a render pipeline the day it lands.
"""

from __future__ import annotations

from typing import Any

#: slug -> (three-letter code, hex colour)
#:
#: Hues are drawn from the reel palette in ``viral_reels/reel/src/theme.ts`` so
#: an arena asset sits next to a data-reel without a clash — with one hard
#: constraint on top: **no club colour may be the theme's gain-green or
#: loss-red**. In the race the bar IS the club colour and its direction carries
#: the sign, so an agent wearing green while losing money reads as a rendering
#: bug. That rules out the obvious green and red, which is why the loud agent is
#: orange rather than the red its persona would suggest.
AGENT_STYLE: dict[str, tuple[str, str]] = {
    # ── the strategies ───────────────────────────────────────────────────────
    "jim-clamor":      ("CLA", "#FF7A18"),  # orange — loud, without being loss-red
    "michael-beary":   ("BEA", "#9D7BFF"),
    "mark-minervine":  ("MIN", "#C2E05B"),
    "barren-wuffett":  ("WUF", "#FFD166"),
    "philip-fissure":  ("FIS", "#2BC4D9"),
    "jim-sigmons":     ("SIG", "#7A8CFF"),
    "chris-cameo":     ("CAM", "#E0709B"),
    # ── the controls: deliberately unbranded ────────────────────────────────
    "jack-boggle":     ("BOG", "#C7D0E0"),  # steel
    "burton-malarkey": ("MAL", "#8A93A4"),  # slate
}

_FALLBACK = ("???", "#6B7791")


def code_for(slug: str) -> str:
    """Three-letter table code, e.g. ``jack-boggle`` -> ``BOG``."""
    return AGENT_STYLE.get(slug, _FALLBACK)[0]


def color_for(slug: str) -> str:
    """Club colour as a hex string."""
    return AGENT_STYLE.get(slug, _FALLBACK)[1]


def is_control(row: dict[str, Any]) -> bool:
    """True for the two non-LLM baselines.

    Read off ``engine`` rather than a slug list so a third control added to
    ``roster.py`` is styled correctly without touching this file.
    """
    return str(row.get("engine") or "").lower() == "deterministic"


def style_for(row: dict[str, Any]) -> dict[str, Any]:
    """The render-facing style block for one leaderboard row."""
    slug = str(row.get("slug") or "")
    return {
        "code": code_for(slug),
        "color": color_for(slug),
        "isControl": is_control(row),
    }
