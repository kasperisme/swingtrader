"""
story_finder — heuristic surfacing of "viral areas" worth a reel.

This is *inspiration*, not the final call. It ranks candidate stories from the
news-impact data so the director (Claude) can pick a subject and frame it, then
fill in copy and pick the metric. Each candidate carries the suggested series
parameters needed to build the reel.
"""

from __future__ import annotations

import logging
from typing import Any

from . import data_sources as ds

log = logging.getLogger(__name__)


def _cumulative_leaders(keyframes: list[dict], n: int = 5) -> list[dict]:
    if not keyframes:
        return []
    last = sorted(keyframes[-1]["entries"], key=lambda e: e["value"], reverse=True)
    return last[:n]


def find_stories(window_days: int = 14, max_stories: int = 6) -> list[dict[str, Any]]:
    """Return ranked candidate stories. Resilient: skips any source that errors."""
    stories: list[dict[str, Any]] = []

    # 1) Cluster momentum — which macro theme swung hardest this window.
    try:
        snap = ds.trend_snapshot(window_days=window_days)
        for mover in snap["cluster_movers"][:3]:
            direction = "heating up" if mover["change"] >= 0 else "cooling off"
            stories.append(
                {
                    "kind": "cluster",
                    "subject": mover["label"],
                    "headline": f"{mover['label']} is {direction}",
                    "why": (
                        f"Cluster sentiment moved {mover['change']:+.2f} over "
                        f"{window_days}d ({mover['start']:+.2f} → {mover['end']:+.2f})."
                    ),
                    "rank_score": abs(mover["change"]),
                    "suggested": {
                        "kind": "cluster",
                        "window_days": window_days,
                        "value_mode": "cumulative_articles",
                        "metric_label": "Articles",
                        "value_format": "count",
                    },
                }
            )
        for mover in snap["dimension_movers"][:3]:
            direction = "rising" if mover["change"] >= 0 else "falling"
            stories.append(
                {
                    "kind": "dimension",
                    "subject": mover["label"],
                    "headline": f"{mover['label']} sentiment is {direction}",
                    "why": (
                        f"Dimension sentiment moved {mover['change']:+.2f} over "
                        f"{window_days}d."
                    ),
                    "rank_score": abs(mover["change"]) * 0.9,
                    "suggested": {
                        "kind": "dimension",
                        "window_days": window_days,
                        "top_k": 8,
                        "value_mode": "cumulative_articles",
                        "metric_label": "Articles",
                        "value_format": "count",
                    },
                }
            )
    except Exception as exc:  # pragma: no cover - depends on live DB
        log.warning("cluster/dimension story scan failed: %s", exc)

    # 2) Hot tickers — who the news is piling onto.
    try:
        tk = ds.ticker_series(window_days=window_days, top_k=8, value_mode="cumulative_articles")
        leaders = _cumulative_leaders(tk, n=5)
        if leaders:
            top = leaders[0]
            names = ", ".join(e["label"] for e in leaders)
            stories.append(
                {
                    "kind": "ticker",
                    "subject": top["label"],
                    "headline": f"{top['label']} is dominating the news flow",
                    "why": f"Most-mentioned tickers ({window_days}d): {names}.",
                    "rank_score": float(top["value"]),
                    "suggested": {
                        "kind": "ticker",
                        "window_days": window_days,
                        "top_k": 8,
                        "value_mode": "cumulative_articles",
                        "metric_label": "Mentions",
                        "value_format": "count",
                        "overlay_ticker": top["label"],
                    },
                }
            )
    except Exception as exc:  # pragma: no cover - depends on live DB
        log.warning("ticker story scan failed: %s", exc)

    stories.sort(key=lambda s: s["rank_score"], reverse=True)
    return stories[:max_stories]
