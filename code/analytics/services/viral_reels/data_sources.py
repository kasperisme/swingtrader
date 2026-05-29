"""
data_sources — build time-bucketed "race" keyframes from the News Impact
Screener data foundation, plus external overlays (FMP price/OHLC).

A *keyframe* is one moment in time in the race:

    {
      "t": "2026-05-15",            # ISO date (the canonical sort key)
      "label": "May 15",            # human label shown in the reel
      "entries": [                  # every tracked entity, every keyframe
        {"id": "SECTOR_ROTATION", "label": "Sector Rotation", "value": 128.0},
        ...
      ]
    }

The renderer interpolates value *and* rank between consecutive keyframes, so the
Python side just needs to emit one consistent entry per entity per keyframe
(values carried forward for cumulative modes). All series builders guarantee
that invariant.

Value modes
-----------
- ``cumulative_articles``  running sum of article volume (default; best race
                           aesthetics — monotonic growth with rank shuffles).
- ``cumulative_attention`` running sum of ``article_count * abs(weighted_avg)``
                           (attention magnitude — how much the news cared).
- ``level``                the raw daily weighted-average sentiment (can be
                           negative; oscillates rather than races).
"""

from __future__ import annotations

import logging
import os
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Iterable

import requests

from shared.db import get_supabase_client
from services.rag.taxonomy import CLUSTER_ID_TO_LABEL, DIM_KEY_TO_LABEL

log = logging.getLogger(__name__)

VALUE_MODES = ("cumulative_articles", "cumulative_attention", "level")


def _supabase():
    return get_supabase_client(), "swingtrader"


def _day_label(iso_day: str) -> str:
    """'2026-05-15' -> 'May 15'."""
    try:
        return datetime.strptime(iso_day[:10], "%Y-%m-%d").strftime("%b %-d")
    except ValueError:
        return iso_day


def _round(v: float) -> float:
    return round(float(v), 4)


def _age_since(iso: str | None) -> str:
    """Relative age baked at build time, mirroring the UI's formatAgeSince."""
    if not iso:
        return ""
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    diff = (datetime.now(timezone.utc) - dt).total_seconds()
    if diff < 0:
        return "just now"
    minute, hour, day, week = 60, 3600, 86400, 604800
    if diff < hour:
        return f"{max(1, int(diff // minute))}m ago"
    if diff < day:
        return f"{int(diff // hour)}h ago"
    if diff < week:
        return f"{int(diff // day)}d ago"
    return f"{int(diff // week)}w ago"


def _source_label(source: str | None, url: str | None) -> str:
    """Prefer the stored source; else derive a host from the url."""
    if source and source.strip():
        return source.strip()
    if url:
        host = url.split("//")[-1].split("/")[0]
        return host or url
    return ""


# ---------------------------------------------------------------------------
# Generic keyframe builder
# ---------------------------------------------------------------------------


def _build_keyframes(
    rows: list[dict[str, Any]],
    *,
    id_key: str,
    day_key: str,
    count_key: str,
    score_key: str,
    label_fn: Callable[[str], str],
    value_mode: str,
    top_k: int | None,
) -> list[dict[str, Any]]:
    """Pivot flat daily rows into per-day keyframes covering every entity.

    Each input row is one (entity, day) pair with an article count and a
    weighted-average score. The output carries every entity into every day so
    the renderer can interpolate without gaps.
    """
    if value_mode not in VALUE_MODES:
        raise ValueError(f"value_mode must be one of {VALUE_MODES}, got {value_mode!r}")

    # raw[day][entity] = (count, score)
    raw: dict[str, dict[str, tuple[float, float]]] = defaultdict(dict)
    entities: set[str] = set()
    for r in rows:
        ent = r.get(id_key)
        day = r.get(day_key)
        if not ent or not day:
            continue
        day = str(day)[:10]
        count = float(r.get(count_key) or 0)
        score = float(r.get(score_key) or 0)
        raw[day][ent] = (count, score)
        entities.add(ent)

    if not raw:
        return []

    days = sorted(raw.keys())

    # Running accumulators per entity for cumulative modes.
    running: dict[str, float] = {e: 0.0 for e in entities}
    keyframes: list[dict[str, Any]] = []
    for day in days:
        for ent in entities:
            count, score = raw[day].get(ent, (0.0, 0.0))
            if value_mode == "cumulative_articles":
                running[ent] += count
            elif value_mode == "cumulative_attention":
                running[ent] += count * abs(score)
            else:  # level
                # carry forward last level when a day has no data for the entity
                if ent in raw[day]:
                    running[ent] = score
        entries = [
            {"id": ent, "label": label_fn(ent), "value": _round(running[ent])}
            for ent in entities
        ]
        keyframes.append({"t": day, "label": _day_label(day), "entries": entries})

    if top_k is not None and top_k < len(entities):
        # Keep the entities with the largest final value; drop the rest entirely
        # (consistently across every keyframe so the entry set stays stable).
        final = {e["id"]: e["value"] for e in keyframes[-1]["entries"]}
        keep = {
            eid
            for eid, _ in sorted(final.items(), key=lambda kv: abs(kv[1]), reverse=True)[:top_k]
        }
        for kf in keyframes:
            kf["entries"] = [e for e in kf["entries"] if e["id"] in keep]

    return keyframes


def _window_floor(window_days: int) -> str:
    since = datetime.now(timezone.utc) - timedelta(days=window_days)
    return since.strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# News-impact series (the unique data foundation)
# ---------------------------------------------------------------------------


def cluster_series(
    window_days: int = 14,
    value_mode: str = "cumulative_articles",
) -> list[dict[str, Any]]:
    """Bar-chart-race keyframes for the 9 impact clusters."""
    client, schema = _supabase()
    res = (
        client.schema(schema)
        .table("news_trends_cluster_daily_v")
        .select("*")
        .gte("bucket_day", _window_floor(window_days))
        .order("bucket_day", desc=False)
        .limit(5000)
        .execute()
    )
    return _build_keyframes(
        res.data or [],
        id_key="cluster_id",
        day_key="bucket_day",
        count_key="bucket_article_count",
        score_key="cluster_weighted_avg",
        label_fn=lambda cid: CLUSTER_ID_TO_LABEL.get(cid, cid),
        value_mode=value_mode,
        top_k=None,
    )


def dimension_series(
    window_days: int = 14,
    top_k: int = 8,
    value_mode: str = "cumulative_articles",
) -> list[dict[str, Any]]:
    """Bar-chart-race keyframes for the top-K impact dimensions."""
    client, schema = _supabase()
    res = (
        client.schema(schema)
        .table("news_trends_dimension_daily_v")
        .select("*")
        .gte("bucket_day", _window_floor(window_days))
        .order("bucket_day", desc=False)
        .limit(8000)
        .execute()
    )
    return _build_keyframes(
        res.data or [],
        id_key="dimension_key",
        day_key="bucket_day",
        count_key="bucket_article_count",
        score_key="dimension_weighted_avg",
        label_fn=lambda k: DIM_KEY_TO_LABEL.get(k, k.replace("_", " ").title()),
        value_mode=value_mode,
        top_k=top_k,
    )


def ticker_series(
    window_days: int = 14,
    top_k: int = 8,
    value_mode: str = "cumulative_articles",
    tickers: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Bar-chart-race keyframes for the most-mentioned tickers.

    Built from ``ticker_sentiment_heads_v`` (one row per article per ticker).
    Articles are bucketed by published day; the per-day count is the number of
    article mentions and the score is the mean sentiment that day.
    """
    client, schema = _supabase()
    since = datetime.now(timezone.utc) - timedelta(days=window_days)
    q = (
        client.schema(schema)
        .table("ticker_sentiment_heads_v")
        .select("ticker,sentiment_score,published_at")
        .gte("published_at", since.isoformat())
    )
    if tickers:
        q = q.in_("ticker", [t.upper() for t in tickers])
    raw_rows = q.order("published_at", desc=False).limit(20000).execute().data or []

    # Aggregate to (ticker, day) -> count + mean sentiment, matching the daily
    # view shape the generic builder expects.
    agg: dict[tuple[str, str], dict[str, float]] = defaultdict(
        lambda: {"count": 0.0, "score_sum": 0.0}
    )
    for r in raw_rows:
        tkr = r.get("ticker")
        pub = r.get("published_at")
        if not tkr or not pub:
            continue
        day = str(pub)[:10]
        cell = agg[(tkr.upper(), day)]
        cell["count"] += 1
        cell["score_sum"] += float(r.get("sentiment_score") or 0)

    daily_rows = [
        {
            "ticker": tkr,
            "bucket_day": day,
            "bucket_article_count": cell["count"],
            "weighted_avg": (cell["score_sum"] / cell["count"]) if cell["count"] else 0.0,
        }
        for (tkr, day), cell in agg.items()
    ]
    return _build_keyframes(
        daily_rows,
        id_key="ticker",
        day_key="bucket_day",
        count_key="bucket_article_count",
        score_key="weighted_avg",
        label_fn=lambda t: t,
        value_mode=value_mode,
        top_k=top_k,
    )


SERIES_BUILDERS: dict[str, Callable[..., list[dict[str, Any]]]] = {
    "cluster": cluster_series,
    "dimension": dimension_series,
    "ticker": ticker_series,
}


# ---------------------------------------------------------------------------
# External source: FMP price / OHLC overlay
# ---------------------------------------------------------------------------


def _fmp_key() -> str:
    key = os.environ.get("FMP_API_KEY") or os.environ.get("APIKEY")
    if not key:
        raise RuntimeError(
            "Set FMP_API_KEY (or APIKEY) in code/analytics/.env to fetch price overlays"
        )
    return key


def price_overlay(ticker: str, window_days: int = 30) -> dict[str, Any]:
    """Daily close-price overlay for a ticker via FMP historical-price REST.

    Returns a ``priceSpark`` overlay the reel draws as a synced sparkline.
    """
    ticker = ticker.upper().strip()
    to = datetime.now(timezone.utc).date()
    frm = to - timedelta(days=window_days)
    url = f"https://financialmodelingprep.com/api/v3/historical-price-full/{ticker}"
    resp = requests.get(
        url,
        params={"from": frm.isoformat(), "to": to.isoformat(), "apikey": _fmp_key()},
        timeout=30,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"FMP historical-price returned {resp.status_code}: {resp.text[:200]}")
    historical = (resp.json() or {}).get("historical", []) or []
    points = sorted(
        (
            {"t": str(row.get("date"))[:10], "close": _round(row.get("close") or 0)}
            for row in historical
            if row.get("date") is not None and row.get("close") is not None
        ),
        key=lambda p: p["t"],
    )
    return {
        "type": "priceSpark",
        "ticker": ticker,
        "label": f"{ticker} close",
        "points": points,
    }


# ---------------------------------------------------------------------------
# Price + News format — price history (OHLC) and the news events to plot on it
# ---------------------------------------------------------------------------


def price_history(ticker: str, window_days: int = 30) -> dict[str, Any]:
    """Daily OHLC history for a ticker via FMP, shaped for the price-news chart."""
    ticker = ticker.upper().strip()
    to = datetime.now(timezone.utc).date()
    frm = to - timedelta(days=window_days)
    url = f"https://financialmodelingprep.com/api/v3/historical-price-full/{ticker}"
    resp = requests.get(
        url,
        params={"from": frm.isoformat(), "to": to.isoformat(), "apikey": _fmp_key()},
        timeout=30,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"FMP historical-price returned {resp.status_code}: {resp.text[:200]}")
    historical = (resp.json() or {}).get("historical", []) or []
    points = sorted(
        (
            {
                "t": str(r.get("date"))[:10],
                "close": _round(r.get("close") or 0),
                "open": _round(r.get("open") or 0),
                "high": _round(r.get("high") or 0),
                "low": _round(r.get("low") or 0),
            }
            for r in historical
            if r.get("date") is not None and r.get("close") is not None
        ),
        key=lambda p: p["t"],
    )
    return {"ticker": ticker, "label": ticker, "valuePrefix": "$", "points": points}


def news_events(
    ticker: str,
    window_days: int = 30,
    max_events: int = 5,
    points: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Strongest per-day news events for a ticker, to plot on the price line.

    Sourced from ``ticker_sentiment_heads_v``. Keeps the highest-magnitude
    article per day, takes the top ``max_events`` by |sentiment|, and (if
    ``points`` are given) annotates each with the next-day price move.
    """
    client, schema = _supabase()
    since = datetime.now(timezone.utc) - timedelta(days=window_days)
    rows = (
        client.schema(schema)
        .table("ticker_sentiment_heads_v")
        .select("article_id,ticker,sentiment_score,title,url,published_at")
        .eq("ticker", ticker.upper().strip())
        .gte("published_at", since.isoformat())
        .order("published_at", desc=False)
        .limit(2000)
        .execute()
        .data
        or []
    )

    # Keep the strongest article per day.
    best_by_day: dict[str, dict] = {}
    for r in rows:
        pub = r.get("published_at")
        if not pub or not (r.get("title") or "").strip():
            continue
        day = str(pub)[:10]
        score = abs(float(r.get("sentiment_score") or 0))
        if day not in best_by_day or score > best_by_day[day]["_mag"]:
            best_by_day[day] = {**r, "_mag": score}

    ranked = sorted(best_by_day.values(), key=lambda r: r["_mag"], reverse=True)[:max_events]
    ranked.sort(key=lambda r: str(r.get("published_at")))

    close_by_day = {p["t"]: p["close"] for p in (points or [])}
    days_sorted = sorted(close_by_day.keys())

    def _next_day_move(day: str) -> str | None:
        if day not in close_by_day or not days_sorted:
            # snap to nearest known trading day
            later = [d for d in days_sorted if d >= day]
            if not later:
                return None
            day = later[0]
        i = days_sorted.index(day)
        if i + 1 >= len(days_sorted):
            return None
        c0, c1 = close_by_day[days_sorted[i]], close_by_day[days_sorted[i + 1]]
        if not c0:
            return None
        pct = (c1 - c0) / c0 * 100
        return f"{pct:+.1f}% next day"

    # Pull image_url + source for the chosen articles (the sentiment view has
    # neither). One batched lookup against news_articles.
    article_ids = [r.get("article_id") for r in ranked if r.get("article_id") is not None]
    meta_by_id: dict[Any, dict] = {}
    if article_ids:
        meta_rows = (
            client.schema(schema)
            .table("news_articles")
            .select("id,image_url,source")
            .in_("id", article_ids)
            .execute()
            .data
            or []
        )
        meta_by_id = {m["id"]: m for m in meta_rows}

    events: list[dict[str, Any]] = []
    for r in ranked:
        day = str(r.get("published_at"))[:10]
        meta = meta_by_id.get(r.get("article_id"), {})
        events.append(
            {
                "t": day,
                "articleId": r.get("article_id"),
                "title": (r.get("title") or "").strip(),
                "source": _source_label(meta.get("source"), r.get("url")),
                "url": r.get("url"),
                "imageUrl": meta.get("image_url"),
                "sentiment": _round(r.get("sentiment_score") or 0),
                "age": _age_since(r.get("published_at")),
                "move": _next_day_move(day),
            }
        )
    return events


def align_first_event_to_second_point(chart: dict[str, Any], lead: int = 1) -> dict[str, Any]:
    """Trim leading price points so the earliest event lands on the ``lead``-th
    rendered date (default: the 2nd point).

    Drops only the empty pre-news run-up, keeping ``lead`` context point(s)
    before the first article so it appears early in the reel without any pacing
    tricks. No-op when there are no events or no room to trim.
    """
    points = chart.get("points") or []
    events = chart.get("events") or []
    if len(points) < 2 or not events:
        return chart

    def _d(s: str) -> date:
        return date.fromisoformat(str(s)[:10])

    target = _d(min(str(e["t"]) for e in events if e.get("t")))
    nearest = min(range(len(points)), key=lambda i: abs((_d(points[i]["t"]) - target).days))
    start = max(0, nearest - lead)
    if start > 0:
        chart = {**chart, "points": points[start:]}
    return chart


# ---------------------------------------------------------------------------
# Headlines — the real articles behind a viral area (UI-styled cards in the reel)
# ---------------------------------------------------------------------------


def headlines(
    window_days: int = 14,
    limit: int = 5,
    dimension_key: str | None = None,
    tickers: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Top article headlines driving the window, as reel-ready cards.

    Pulled from ``news_trends_article_base_v`` (title/source/url/image +
    per-article impact vector). When ``dimension_key`` is given, articles are
    ranked by how strongly they load on that dimension; otherwise by overall
    scoring confidence. Each card carries a pre-baked relative ``age``.
    """
    client, schema = _supabase()
    since = datetime.now(timezone.utc) - timedelta(days=window_days)
    rows = (
        client.schema(schema)
        .table("news_trends_article_base_v")
        .select("article_id,title,url,source,image_url,published_at,impact_jsonb,confidence_mean")
        .gte("published_at", since.isoformat())
        .order("published_at", desc=True)
        .limit(400)
        .execute()
        .data
        or []
    )

    def _impact(row: dict) -> dict:
        v = row.get("impact_jsonb")
        if isinstance(v, dict):
            return v
        try:
            import json

            return json.loads(v) if v else {}
        except (TypeError, ValueError):
            return {}

    if dimension_key:
        scored = [
            (abs(float(_impact(r).get(dimension_key, 0) or 0)), r)
            for r in rows
            if dimension_key in _impact(r)
        ]
        scored.sort(key=lambda x: x[0], reverse=True)
        picked = [r for _, r in scored]
    else:
        picked = sorted(rows, key=lambda r: float(r.get("confidence_mean") or 0), reverse=True)

    out: list[dict[str, Any]] = []
    for r in picked[:limit]:
        title = (r.get("title") or "").strip()
        if not title:
            continue
        out.append(
            {
                "articleId": r.get("article_id"),
                "title": title,
                "source": _source_label(r.get("source"), r.get("url")),
                "url": r.get("url"),
                "publishedAt": r.get("published_at"),
                "age": _age_since(r.get("published_at")),
                "imageUrl": r.get("image_url"),
            }
        )
    return out


def article_images(ids: list[int]) -> list[dict[str, Any]]:
    """Look up id/title/source/image_url for specific news_articles ids.

    Diagnostic: confirm whether the articles a reel would use actually carry an
    image_url in the DB.
    """
    if not ids:
        return []
    client, schema = _supabase()
    rows = (
        client.schema(schema)
        .table("news_articles")
        .select("id,title,source,image_url")
        .in_("id", ids)
        .execute()
        .data
        or []
    )
    return [
        {
            "id": r.get("id"),
            "title": r.get("title"),
            "source": r.get("source"),
            "image_url": r.get("image_url"),
            "has_image": bool((r.get("image_url") or "").strip()),
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Inspection helpers (for the director to eyeball what's moving)
# ---------------------------------------------------------------------------


def trend_snapshot(window_days: int = 14) -> dict[str, Any]:
    """Compact cluster + dimension snapshot for picking a story.

    Returns the latest level and the change-over-window for each cluster and
    the top-moving dimensions — enough signal for the director to choose a
    subject without dumping raw rows.
    """
    clusters = cluster_series(window_days=window_days, value_mode="level")
    dims = dimension_series(window_days=window_days, top_k=20, value_mode="level")

    def _movers(keyframes: list[dict]) -> list[dict]:
        if len(keyframes) < 2:
            return []
        first = {e["id"]: e for e in keyframes[0]["entries"]}
        last = {e["id"]: e for e in keyframes[-1]["entries"]}
        out = []
        for eid, le in last.items():
            fe = first.get(eid)
            start = fe["value"] if fe else 0.0
            out.append(
                {
                    "id": eid,
                    "label": le["label"],
                    "start": start,
                    "end": le["value"],
                    "change": _round(le["value"] - start),
                }
            )
        return sorted(out, key=lambda d: abs(d["change"]), reverse=True)

    return {
        "window_days": window_days,
        "cluster_movers": _movers(clusters),
        "dimension_movers": _movers(dims)[:10],
    }
