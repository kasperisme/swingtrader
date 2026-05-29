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
  "intro":   {"kicker", "title", "subtitle", "durationInSeconds"},
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


def composition_for(spec: dict[str, Any]) -> str:
    """Remotion composition id for a spec, by shape."""
    return "PriceNewsChart" if ("chart" in spec and "race" not in spec) else "BarChartRace"


def load(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text())


def save(spec: dict[str, Any], path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(spec, indent=2))
    return p
