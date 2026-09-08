"""
spec — the contract between Python (data), Claude (direction) and Remotion
(rendering) for the arena creative package.

Two specs, one visual language:

``arenaTable``
    A still league table. Rendered by Remotion ``still`` at 4:5 (Meta feed),
    9:16 (Reels/TikTok/Stories) and 1:1.

``arenaRace``
    The same table, animated over the season — rows reordering, bars diverging
    from a zero line. Rendered by Remotion ``render`` at 9:16.

They share a row shape on purpose. A weekly package only reads as a *package*
if the still and the video are visibly the same graphic, the way a broadcaster's
table bug is identical in the pre-match graphic and the results round-up.

The TypeScript mirrors live in ``viral_reels/reel/src/types.ts``
(``ArenaTableSpec`` / ``ArenaRaceSpec``) — keep them in sync.

Why the arena compositions live inside the ``viral_reels`` Remotion project:
that project is the repo's single render surface (installed ``node_modules``,
``theme.ts`` palette, the rank-interpolation helpers a race needs). A second
Remotion app would duplicate all three and let the two drift apart visually,
which is the one thing a broadcast package cannot survive.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from services.arena_creatives import palette

VERSION = 1

#: Aspect ratios the still table is rendered at, matching the ad convention in
#: ``nis-ad-image`` so the two can be launched through the same Meta flow.
TABLE_SIZES: dict[str, tuple[int, int]] = {
    "4x5": (1080, 1350),
    "9x16": (1080, 1920),
    "1x1": (1080, 1080),
}

RACE_FORMAT: dict[str, Any] = {
    "width": 1080,
    "height": 1920,
    "fps": 30,
    "durationInSeconds": 22,
}

#: Required on every asset. Paper trading is both a compliance fact and the
#: reason anyone should trust the board, so it is not optional and not small.
DISCLAIMER = "Paper trading. Not investment advice."

CTA = "newsimpactscreener.com/arena"


def _row(r: dict[str, Any]) -> dict[str, Any]:
    """One standings row, styled, in the shape both compositions consume."""
    return {
        "rank": r["rank"],
        "slug": r["slug"],
        "name": r["name"],
        "nav": round(float(r["nav"]), 2),
        "return": round(float(r["return"]), 6),
        "drawdown": round(float(r["drawdown"]), 6),
        "sharpe": None if r.get("sharpe") is None else round(float(r["sharpe"]), 2),
        "trades": r["trades"],
        "winRate": None if r.get("winRate") is None else round(float(r["winRate"]), 4),
        "positions": r["positions"],
        "move": r.get("move"),
        "form": r.get("form") or [],
        "streak": r.get("streak") or 0,
        **palette.style_for(r),
    }


def _header(standings: dict[str, Any], *, title: Optional[str] = None) -> dict[str, Any]:
    champ = standings["championship"]
    n = standings.get("sessions") or 0
    return {
        # "MATCHDAY 41" is the whole trick: it turns an open-ended experiment
        # into a fixture list, which is what makes a weekly post feel like an
        # episode rather than a repost.
        "kicker": f"THE ARENA · {str(champ.get('name') or champ.get('slug') or '').upper()}",
        "title": title or (f"MATCHDAY {n}" if n else "THE TABLE"),
        "subtitle": "9 AI agents · $100,000 each · the same market",
    }


def build_table_spec(
    standings: dict[str, Any],
    *,
    story: Optional[dict[str, Any]] = None,
    ratio: str = "4x5",
    theme: str = "midnight",
    title: Optional[str] = None,
    hook: Optional[str] = None,
    cta: str = CTA,
) -> dict[str, Any]:
    """Assemble the still-table spec.

    ``hook`` overrides the detected storyline's headline when the director wants
    different words; ``story`` supplies the default. The strap is never dropped
    entirely — a table with no sentence on it is a report.
    """
    if ratio not in TABLE_SIZES:
        raise ValueError(f"ratio must be one of {sorted(TABLE_SIZES)}, got {ratio!r}")
    w, h = TABLE_SIZES[ratio]
    rows = [_row(r) for r in standings["rows"]]

    return {
        "version": VERSION,
        "kind": "arenaTable",
        "format": {"width": w, "height": h, "fps": 30, "durationInSeconds": 1},
        "theme": theme,
        "header": _header(standings, title=title),
        "hook": hook or (story or {}).get("headline") or "",
        "storyKey": (story or {}).get("key"),
        # Top 3 get a green edge, bottom 2 a red one — the promotion and
        # relegation zones, which is how a table communicates stakes without
        # a caption.
        "zones": {"top": 3, "bottom": 2},
        "rows": rows,
        "footer": {
            "asOf": standings.get("asOf"),
            "cta": cta,
            "disclaimer": DISCLAIMER,
        },
    }


def build_race_spec(
    standings: dict[str, Any],
    race: dict[str, Any],
    *,
    story: Optional[dict[str, Any]] = None,
    theme: str = "midnight",
    title: Optional[str] = None,
    captions: Optional[list[dict[str, Any]]] = None,
    outro_takeaway: str = "",
    cta: str = CTA,
    duration_seconds: Optional[float] = None,
) -> dict[str, Any]:
    """Assemble the league-table-race spec.

    ``race`` is the output of ``data_sources.build_race_keyframes``. The final
    standings are carried alongside the keyframes so the outro can freeze on the
    real table rather than on the last interpolated frame.
    """
    rows = [_row(r) for r in standings["rows"]]
    by_slug = {r["slug"]: r for r in rows}

    # Agents appear in the race in finishing order, so the legend and the outro
    # table agree with each other.
    agents = [
        {
            "slug": s,
            "name": by_slug.get(s, {}).get("name", s),
            "code": palette.code_for(s),
            "color": palette.color_for(s),
            "isControl": by_slug.get(s, {}).get("isControl", False),
        }
        for s in sorted(race["agents"], key=lambda s: by_slug.get(s, {}).get("rank", 99))
    ]

    fmt = dict(RACE_FORMAT)
    if duration_seconds:
        fmt["durationInSeconds"] = float(duration_seconds)

    return {
        "version": VERSION,
        "kind": "arenaRace",
        "format": fmt,
        "theme": theme,
        "header": _header(standings, title=title),
        "hook": (story or {}).get("headline") or "",
        "storyKey": (story or {}).get("key"),
        "metricLabel": "Return",
        "agents": agents,
        "keyframes": race["keyframes"],
        "finalRows": rows,
        "captions": captions or [],
        "outro": {
            "title": (story or {}).get("headline") or "The board is public.",
            "takeaway": outro_takeaway or (story or {}).get("detail") or "",
            "cta": cta,
            "durationInSeconds": 3.5,
        },
        "footer": {
            "asOf": standings.get("asOf"),
            "cta": cta,
            "disclaimer": DISCLAIMER,
        },
        "sources": ["News Impact Screener — The Arena"],
    }


# ── validation ───────────────────────────────────────────────────────────────


def validate(spec: dict[str, Any]) -> list[str]:
    """Problems that would render a wrong or misleading graphic.

    Deliberately strict about the disclaimer and about empty tables: both fail
    silently at render time (a missing footer line still produces a pretty
    image) and both are unacceptable to publish.
    """
    problems: list[str] = []
    kind = spec.get("kind")
    if kind not in ("arenaTable", "arenaRace"):
        problems.append(f"kind must be arenaTable|arenaRace, got {kind!r}")
    if spec.get("version") != VERSION:
        problems.append(f"version must be {VERSION}")

    fmt = spec.get("format") or {}
    for k in ("width", "height", "fps", "durationInSeconds"):
        if not fmt.get(k):
            problems.append(f"format.{k} missing")

    footer = spec.get("footer") or {}
    if not footer.get("disclaimer"):
        problems.append("footer.disclaimer missing — every arena asset must carry it")
    if not footer.get("asOf"):
        problems.append("footer.asOf missing — an undated table is not verifiable")

    rows = spec.get("rows") if kind == "arenaTable" else spec.get("finalRows")
    if not rows:
        problems.append("no standings rows")
    else:
        for r in rows:
            if r.get("return") is None or r.get("nav") is None:
                problems.append(f"row {r.get('slug')} missing return/nav")
            if not r.get("color"):
                problems.append(f"row {r.get('slug')} has no club colour")

    if kind == "arenaRace":
        kfs = spec.get("keyframes") or []
        if len(kfs) < 2:
            problems.append("a race needs at least 2 keyframes")
        ids = {a["slug"] for a in spec.get("agents") or []}
        for i, kf in enumerate(kfs):
            missing = ids - {e["id"] for e in kf.get("entries") or []}
            if missing:
                problems.append(f"keyframe {i} ({kf.get('t')}) missing {sorted(missing)}")
                break

    return problems


def dump(spec: dict[str, Any], path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(spec, indent=2))
    return p


def load(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text())


def composition_for(spec: dict[str, Any]) -> str:
    return "ArenaTable" if spec.get("kind") == "arenaTable" else "ArenaRace"


def is_still(spec: dict[str, Any]) -> bool:
    return spec.get("kind") == "arenaTable"
