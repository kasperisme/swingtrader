"""
spec — the ReelSpec contract shared between Python (data), Claude (direction)
and Remotion (rendering).

A ReelSpec is a plain JSON-serialisable dict. The renderer's TypeScript types
in ``reel/src/types.ts`` mirror this structure exactly — keep them in sync.

Shape
-----
{
  "version": 1,
  "format":  {"width": 1080, "height": 1920, "fps": 30, "durationInSeconds": 20},
  "theme":   "midnight",                 # key in reel/src/theme.ts
  "intro":   {...} / "outro": {...}   # NOT rendered — the reel carries no
             # burned-in hook/takeaway text (added later in Instagram/edits).
             # Kept as optional metadata only.
  "race": {
    "metricLabel": "Articles",
    "valueFormat": "count",              # count | score | percent | currency | signed
    "barsVisible": 6,
    "keyframes": [ {t, label, entries:[{id,label,value}]}, ... ]
  },
  "overlay": {"type":"priceSpark","ticker","label","points":[{t,close}]} | null,
  "captions": [ {"atSeconds": 3.0, "text": "..."} ],
  "headlines": [ {"title","source","url","publishedAt","age","imageUrl"} ],
  "outro":   {"title", "takeaway", "cta", "durationInSeconds"},
  "sources": ["News Impact Screener", "Financial Modeling Prep"]
}
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

VERSION = 1

DEFAULT_FORMAT: dict[str, Any] = {
    "width": 1080,
    "height": 1920,
    "fps": 30,
    "durationInSeconds": 20,
}

# The stock card is a still poster sized for the Instagram feed (4:5 portrait),
# not the 9:16 reel canvas.
CARD_DEFAULT_FORMAT: dict[str, Any] = {
    "width": 1080,
    "height": 1350,
    "fps": 30,
    "durationInSeconds": 6,
}

VALUE_FORMATS = ("count", "score", "percent", "currency", "signed")


def build_spec(
    *,
    keyframes: list[dict[str, Any]],
    metric_label: str,
    value_format: str = "count",
    theme: str = "midnight",
    title: str = "",
    kicker: str = "NEWS IMPACT SCREENER",
    subtitle: str = "",
    outro_title: str = "",
    outro_takeaway: str = "",
    cta: str = "newsimpactscreener.com",
    captions: list[dict[str, Any]] | None = None,
    headlines: list[dict[str, Any]] | None = None,
    overlay: dict[str, Any] | None = None,
    bars_visible: int = 6,
    sources: list[str] | None = None,
    format_overrides: dict[str, Any] | None = None,
    intro_seconds: float = 2.5,
    outro_seconds: float = 3.0,
) -> dict[str, Any]:
    """Assemble a ReelSpec dict. The director (Claude) supplies the copy;
    the data layer supplies ``keyframes`` and ``overlay``."""
    fmt = {**DEFAULT_FORMAT, **(format_overrides or {})}
    default_sources = ["News Impact Screener"]
    if overlay and overlay.get("type") == "priceSpark":
        default_sources.append("Financial Modeling Prep")
    return {
        "version": VERSION,
        "format": fmt,
        "theme": theme,
        "intro": {
            "kicker": kicker,
            "title": title,
            "subtitle": subtitle,
            "durationInSeconds": intro_seconds,
        },
        "race": {
            "metricLabel": metric_label,
            "valueFormat": value_format,
            "barsVisible": bars_visible,
            "keyframes": keyframes,
        },
        "overlay": overlay,
        "captions": captions or [],
        "headlines": headlines or [],
        "outro": {
            "title": outro_title,
            "takeaway": outro_takeaway,
            "cta": cta,
            "durationInSeconds": outro_seconds,
        },
        "sources": sources or default_sources,
    }


def build_price_news_spec(
    *,
    chart: dict[str, Any],
    theme: str = "midnight",
    title: str = "",
    kicker: str = "NEWS IMPACT SCREENER",
    subtitle: str = "",
    outro_title: str = "",
    outro_takeaway: str = "",
    cta: str = "newsimpactscreener.com",
    sources: list[str] | None = None,
    format_overrides: dict[str, Any] | None = None,
    intro_seconds: float = 2.5,
    outro_seconds: float = 3.0,
) -> dict[str, Any]:
    """Assemble a price+news ReelSpec. ``chart`` holds ticker/points/events
    from the data layer; the director supplies the copy."""
    fmt = {**DEFAULT_FORMAT, **(format_overrides or {})}
    return {
        "version": VERSION,
        "format": fmt,
        "theme": theme,
        "intro": {
            "kicker": kicker,
            "title": title,
            "subtitle": subtitle,
            "durationInSeconds": intro_seconds,
        },
        "chart": chart,
        "outro": {
            "title": outro_title,
            "takeaway": outro_takeaway,
            "cta": cta,
            "durationInSeconds": outro_seconds,
        },
        "sources": sources or ["News Impact Screener", "Financial Modeling Prep"],
    }


def build_card_spec(
    *,
    card: dict[str, Any],
    theme: str = "midnight",
    sources: list[str] | None = None,
    format_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble a stock-card spec (a still poster, not an animation).

    ``card`` holds the identity/stat/badge data from the data layer; the
    director supplies the headline, tag, hero portrait URL and any badge/stat
    overrides. Rendered as a single 1080×1350 (4:5) PNG via Remotion ``still``.
    """
    fmt = {**CARD_DEFAULT_FORMAT, **(format_overrides or {})}
    return {
        "version": VERSION,
        "format": fmt,
        "theme": theme,
        "card": card,
        "sources": sources or ["News Impact Screener", "Financial Modeling Prep"],
    }


def _validate_format_and_timing(spec: dict[str, Any], errors: list[str]) -> None:
    fmt = spec.get("format") or {}
    for key in ("width", "height", "fps", "durationInSeconds"):
        if not isinstance(fmt.get(key), (int, float)) or fmt.get(key) <= 0:
            errors.append(f"format.{key} must be a positive number")
    intro_s = (spec.get("intro") or {}).get("durationInSeconds", 0) or 0
    outro_s = (spec.get("outro") or {}).get("durationInSeconds", 0) or 0
    total_s = fmt.get("durationInSeconds", 0) or 0
    if intro_s + outro_s >= total_s:
        errors.append(
            f"intro ({intro_s}s) + outro ({outro_s}s) must leave room for the main "
            f"section within the total {total_s}s"
        )


def validate(spec: dict[str, Any]) -> list[str]:
    """Validate either reel format. Empty list == valid.

    Dispatches on shape: a ``chart`` key means the price+news format, a ``race``
    key means the bar-chart-race format.
    """
    if "card" in spec and "race" not in spec and "chart" not in spec:
        return validate_card(spec)
    if "chart" in spec and "race" not in spec:
        return validate_price_news(spec)

    errors: list[str] = []

    fmt = spec.get("format") or {}
    for key in ("width", "height", "fps", "durationInSeconds"):
        if not isinstance(fmt.get(key), (int, float)) or fmt.get(key) <= 0:
            errors.append(f"format.{key} must be a positive number")

    race = spec.get("race") or {}
    if race.get("valueFormat") not in VALUE_FORMATS:
        errors.append(f"race.valueFormat must be one of {VALUE_FORMATS}")
    keyframes = race.get("keyframes") or []
    if len(keyframes) < 2:
        errors.append("race.keyframes needs at least 2 entries to animate")

    entity_sets = []
    for i, kf in enumerate(keyframes):
        entries = kf.get("entries") or []
        if not kf.get("t"):
            errors.append(f"race.keyframes[{i}] missing 't' (ISO date)")
        if not entries:
            errors.append(f"race.keyframes[{i}] has no entries")
        for j, e in enumerate(entries):
            if "id" not in e or "value" not in e:
                errors.append(f"race.keyframes[{i}].entries[{j}] needs 'id' and 'value'")
        entity_sets.append({e.get("id") for e in entries})

    # The renderer assumes a stable entity set across keyframes.
    if entity_sets and any(s != entity_sets[0] for s in entity_sets):
        errors.append(
            "every keyframe must list the same set of entity ids "
            "(carry values forward instead of dropping entities)"
        )

    overlay = spec.get("overlay")
    if overlay is not None:
        if overlay.get("type") != "priceSpark":
            errors.append("overlay.type must be 'priceSpark' (only type supported)")
        elif len(overlay.get("points") or []) < 2:
            errors.append("overlay.points needs at least 2 points")

    for i, h in enumerate(spec.get("headlines") or []):
        if not (h.get("title") or "").strip():
            errors.append(f"headlines[{i}] needs a non-empty 'title'")

    intro_s = (spec.get("intro") or {}).get("durationInSeconds", 0) or 0
    outro_s = (spec.get("outro") or {}).get("durationInSeconds", 0) or 0
    total_s = fmt.get("durationInSeconds", 0) or 0
    if intro_s + outro_s >= total_s:
        errors.append(
            f"intro ({intro_s}s) + outro ({outro_s}s) must leave room for the race "
            f"within the total {total_s}s"
        )

    return errors


def validate_price_news(spec: dict[str, Any]) -> list[str]:
    """Validate a price+news ReelSpec."""
    errors: list[str] = []
    _validate_format_and_timing(spec, errors)

    chart = spec.get("chart") or {}
    if not (chart.get("ticker") or "").strip():
        errors.append("chart.ticker is required")
    points = chart.get("points") or []
    if len(points) < 2:
        errors.append("chart.points needs at least 2 points to draw a line")
    for i, p in enumerate(points):
        if not p.get("t") or not isinstance(p.get("close"), (int, float)):
            errors.append(f"chart.points[{i}] needs 't' and numeric 'close'")
            break

    for i, e in enumerate(chart.get("events") or []):
        if not e.get("t"):
            errors.append(f"chart.events[{i}] needs 't' (ISO date)")
        if not (e.get("title") or "").strip():
            errors.append(f"chart.events[{i}] needs a non-empty 'title'")
        sent = e.get("sentiment")
        if sent is not None and not (-1.0 <= float(sent) <= 1.0):
            errors.append(f"chart.events[{i}].sentiment must be within [-1, 1]")

    return errors


# Max trading-day gap the price-news chart should ever go without an event —
# the chart draws at a steady pace, so a larger gap leaves a stretch of empty
# line on screen. The director should land an event every ≤4 chart ticks.
MAX_EVENT_GAP_POINTS = 4


def event_spacing_warnings(
    spec: dict[str, Any], max_gap: int = MAX_EVENT_GAP_POINTS
) -> list[str]:
    """Non-fatal coverage check for a price-news spec: flag stretches of the
    chart with no plotted event.

    Gaps are measured in **chart ticks** (price points = trading days), not
    calendar days, since the line is drawn point-by-point at a steady pace. We
    warn when the run from the chart's start to the first event, between any two
    consecutive events, or from the last event to the chart's end exceeds
    ``max_gap`` points — i.e. the reel would show a span with no headline. Empty
    list == well covered. Not an error: the renderer still works.
    """
    if "chart" not in spec or "race" in spec:
        return []
    chart = spec.get("chart") or {}
    points = chart.get("points") or []
    events = chart.get("events") or []
    if len(points) < 2 or not events:
        return []

    day_index = {p["t"]: i for i, p in enumerate(points)}

    def _idx(t: str) -> int:
        # snap an event to the nearest chart tick (matches the renderer)
        if t in day_index:
            return day_index[t]
        from datetime import date

        def _d(s: str):
            return date.fromisoformat(str(s)[:10])

        target = _d(t)
        return min(range(len(points)), key=lambda i: abs((_d(points[i]["t"]) - target).days))

    idxs = sorted({_idx(str(e["t"])) for e in events if e.get("t")})
    last = len(points) - 1
    warnings: list[str] = []

    if idxs[0] > max_gap:
        warnings.append(
            f"first event is {idxs[0]} chart ticks in — the reel opens with an "
            f"empty {idxs[0]}-day run (want an event within {max_gap})"
        )
    for a, b in zip(idxs, idxs[1:]):
        if b - a > max_gap:
            warnings.append(
                f"{b - a}-tick gap between events at points {a} and {b} "
                f"(want one every ≤{max_gap})"
            )
    if last - idxs[-1] > max_gap:
        warnings.append(
            f"last event is {last - idxs[-1]} chart ticks before the end — the "
            f"reel ends on an empty run (want an event within {max_gap})"
        )
    return warnings


def validate_card(spec: dict[str, Any]) -> list[str]:
    """Validate a stock-card spec. Empty list == valid."""
    errors: list[str] = []
    fmt = spec.get("format") or {}
    for key in ("width", "height", "fps", "durationInSeconds"):
        if not isinstance(fmt.get(key), (int, float)) or fmt.get(key) <= 0:
            errors.append(f"format.{key} must be a positive number")

    card = spec.get("card") or {}
    if not (card.get("ticker") or "").strip():
        errors.append("card.ticker is required")
    if not (card.get("company") or "").strip():
        errors.append("card.company is required")
    if not (card.get("headline") or "").strip():
        errors.append("card.headline is required")
    if not (card.get("heroImageUrl") or card.get("logoUrl")):
        errors.append("card needs a heroImageUrl (CEO photo) or a logoUrl to render a hero")

    stats = card.get("stats") or []
    if not (1 <= len(stats) <= 4):
        errors.append("card.stats must have 1–4 entries")
    for i, s in enumerate(stats):
        if not (s.get("label") or "").strip() or not str(s.get("value") or "").strip():
            errors.append(f"card.stats[{i}] needs a 'label' and 'value'")

    badge = card.get("badge")
    if badge is not None:
        if not str(badge.get("value") or "").strip():
            errors.append("card.badge.value must be non-empty when a badge is present")
        tone = badge.get("tone")
        if tone is not None and tone not in ("positive", "negative", "neutral"):
            errors.append("card.badge.tone must be positive | negative | neutral")
    return errors


def is_still(spec: dict[str, Any]) -> bool:
    """True for specs rendered as a single PNG (the stock card)."""
    return "card" in spec and "race" not in spec and "chart" not in spec


def composition_for(spec: dict[str, Any]) -> str:
    """Remotion composition id for a spec, by shape."""
    if is_still(spec):
        return "StockCard"
    return "PriceNewsChart" if ("chart" in spec and "race" not in spec) else "BarChartRace"


def load(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text())


def save(spec: dict[str, Any], path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(spec, indent=2))
    return p
