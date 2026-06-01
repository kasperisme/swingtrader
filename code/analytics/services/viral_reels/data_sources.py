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
    window_days: int = 30,
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
    window_days: int = 30,
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
    window_days: int = 30,
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


def _next_day_move_str(points: list[dict[str, Any]] | None, day: str) -> str | None:
    """Next-day close-to-close move for an event landing on/just-before ``day``."""
    close_by_day = {p["t"]: p["close"] for p in (points or [])}
    days = sorted(close_by_day)
    if not days:
        return None
    if day not in close_by_day:
        later = [d for d in days if d >= day]
        if not later:
            return None
        day = later[0]
    i = days.index(day)
    if i + 1 >= len(days):
        return None
    c0, c1 = close_by_day[days[i]], close_by_day[days[i + 1]]
    if not c0:
        return None
    return f"{(c1 - c0) / c0 * 100:+.1f}% next day"


def _fmp_sentiment_by_url(ticker: str, urls: list[str]) -> dict[str, float]:
    """Recover internal AI sentiment for FMP articles already scored in our DB.

    FMP news carries no sentiment; when the same article (by url) exists in
    ``ticker_sentiment_heads_v`` we reuse its per-ticker score so the pin keeps
    its sentiment colour. Best-effort — unmatched urls just stay neutral.
    """
    urls = [u for u in urls if u]
    if not urls:
        return {}
    try:
        client, schema = _supabase()
        rows = (
            client.schema(schema)
            .table("ticker_sentiment_heads_v")
            .select("article_url,sentiment_score")
            .eq("ticker", ticker.upper().strip())
            .in_("article_url", urls)
            .execute()
            .data
            or []
        )
    except Exception:  # noqa: BLE001 — enrichment is best-effort, never fatal
        return {}
    return {r["article_url"]: r.get("sentiment_score") for r in rows if r.get("article_url")}


def fmp_stock_news(
    ticker: str,
    window_days: int = 30,
    limit: int = 100,
    points: list[dict[str, Any]] | None = None,
    enrich_sentiment: bool = True,
) -> list[dict[str, Any]]:
    """Stock-news headlines for a ticker via FMP (stable ``news/stock``).

    Broader / fresher coverage than the internal feed — useful to fill gaps for
    thinly-covered tickers and to ground the reel in real article cards (FMP
    always supplies an image). FMP carries no sentiment; when ``enrich_sentiment``
    is set we recover the internal AI score by url match (otherwise the pin is
    neutral). Returns one event per article (oldest→newest), shaped like
    :func:`news_candidates` output so the director can fold them into a spec.
    """
    ticker = ticker.upper().strip()
    to = datetime.now(timezone.utc).date()
    frm = to - timedelta(days=window_days)
    resp = requests.get(
        "https://financialmodelingprep.com/stable/news/stock",
        params={
            "symbols": ticker,
            "from": frm.isoformat(),
            "to": to.isoformat(),
            "limit": limit,
            "apikey": _fmp_key(),
        },
        timeout=30,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"FMP news/stock returned {resp.status_code}: {resp.text[:200]}")
    rows = resp.json() or []

    senti = (
        _fmp_sentiment_by_url(ticker, [r.get("url") for r in rows]) if enrich_sentiment else {}
    )
    events: list[dict[str, Any]] = []
    for r in rows:
        pub = r.get("publishedDate")
        title = (r.get("title") or "").strip()
        if not pub or not title:
            continue
        day = str(pub)[:10]
        score = senti.get(r.get("url"))
        events.append(
            {
                "t": day,
                "articleId": None,
                "title": title,
                "source": _source_label(r.get("publisher") or r.get("site"), r.get("url")),
                "url": r.get("url"),
                "imageUrl": r.get("image"),
                "sentiment": None if score is None else _round(score),
                "age": _age_since(pub),
                "move": _next_day_move_str(points, day),
            }
        )
    events.sort(key=lambda e: e["t"])
    return events


def fmp_press_releases(
    ticker: str,
    window_days: int = 30,
    limit: int = 100,
    points: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Official company press releases via FMP (v3 ``press-releases/{ticker}``).

    The company's own catalysts (earnings, guidance, product) at their exact
    timestamp — the cleanest way to anchor a price move to its true cause when
    the third-party write-up lands a day late. No image/url/sentiment, so cards
    use the fallback thumbnail and a neutral pin. Filtered to the window and
    shaped like :func:`news_candidates` output. (FMP's *stable* press-release
    search is plan-restricted, so this uses the v3 path, which works on the
    standard plan.)
    """
    ticker = ticker.upper().strip()
    resp = requests.get(
        f"https://financialmodelingprep.com/api/v3/press-releases/{ticker}",
        params={"page": 0, "apikey": _fmp_key()},
        timeout=30,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"FMP press-releases returned {resp.status_code}: {resp.text[:200]}")
    rows = resp.json() or []
    cutoff = (datetime.now(timezone.utc).date() - timedelta(days=window_days)).isoformat()

    events: list[dict[str, Any]] = []
    for r in rows:
        date = r.get("date")
        title = (r.get("title") or "").strip()
        if not date or not title:
            continue
        day = str(date)[:10]
        if day < cutoff:
            continue
        events.append(
            {
                "t": day,
                "articleId": None,
                "title": title,
                "source": f"{ticker} press release",
                "url": None,
                "imageUrl": None,
                "sentiment": None,
                "age": _age_since(date),
                "move": _next_day_move_str(points, day),
            }
        )
        if len(events) >= limit:
            break
    events.sort(key=lambda e: e["t"])
    return events


def _distribute_events_over_time(
    candidates: list[dict[str, Any]], k: int
) -> list[dict[str, Any]]:
    """Pick ``k`` candidates spread across their date span.

    Splits the ``[earliest, latest]`` day range into ``k`` equal-time buckets
    and takes the highest-``_impact`` candidate from each. Empty buckets are
    backfilled with the strongest still-unused candidates, so the result has
    up to ``k`` events that cover the whole window instead of clustering where
    articles happen to be densest. Each candidate must carry ``_day`` (ISO
    ``YYYY-MM-DD``) and ``_impact`` (float).
    """
    if k <= 0 or not candidates:
        return []
    if len(candidates) <= k:
        return list(candidates)

    days = sorted(c["_day"] for c in candidates)
    start = date.fromisoformat(days[0]).toordinal()
    span = max(date.fromisoformat(days[-1]).toordinal() - start, 1)

    buckets: list[list[dict[str, Any]]] = [[] for _ in range(k)]
    for c in candidates:
        o = date.fromisoformat(c["_day"]).toordinal()
        idx = min(int((o - start) / span * k), k - 1)
        buckets[idx].append(c)

    chosen: list[dict[str, Any]] = []
    used: set[str] = set()
    for b in buckets:
        if b:
            best = max(b, key=lambda c: c["_impact"])
            chosen.append(best)
            used.add(best["_day"])

    if len(chosen) < k:
        rest = sorted(
            (c for c in candidates if c["_day"] not in used),
            key=lambda c: c["_impact"],
            reverse=True,
        )
        chosen.extend(rest[: k - len(chosen)])
    return chosen


def news_candidates(
    ticker: str,
    window_days: int = 30,
    points: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """The full pool of plottable news events for a ticker — one per day.

    Returns every day's strongest article as a ready-to-plot event dict (same
    shape the spec expects), annotated with its next-day price ``move`` and a
    heuristic ``impact`` score (``|next-day move| × |sentiment|``, or
    ``|sentiment|`` when the move can't be computed). This is the **director's
    pool**: Claude Code reviews it and picks which events tell the clearest
    story across the window, rather than relying on a fixed heuristic. Events
    are sorted oldest→newest. ``impact`` is advisory ranking, not a filter.
    """
    client, schema = _supabase()
    since = datetime.now(timezone.utc) - timedelta(days=window_days)
    rows = (
        client.schema(schema)
        .table("ticker_sentiment_heads_v")
        .select("article_id,ticker,sentiment_score,article_title,article_url,article_source,published_at")
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
        if not pub or not (r.get("article_title") or "").strip():
            continue
        day = str(pub)[:10]
        score = abs(float(r.get("sentiment_score") or 0))
        if day not in best_by_day or score > best_by_day[day]["_mag"]:
            best_by_day[day] = {**r, "_mag": score}

    close_by_day = {p["t"]: p["close"] for p in (points or [])}
    days_sorted = sorted(close_by_day.keys())

    def _next_day_move_pct(day: str) -> float | None:
        if day not in close_by_day or not days_sorted:
            # snap to nearest known trading day on/after the article
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
        return (c1 - c0) / c0 * 100

    # Pull image_url + source for every candidate (the sentiment view has
    # neither). One batched lookup against news_articles.
    article_ids = [r.get("article_id") for r in best_by_day.values() if r.get("article_id") is not None]
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
    for day, r in best_by_day.items():
        mv = _next_day_move_pct(day)
        # Impact weights a real price move by how strongly the headline scored,
        # so a strongly-scored headline that coincided with a move outranks a
        # near-neutral one that merely landed on a big day.
        impact = abs(mv) * r["_mag"] if mv is not None else r["_mag"]
        meta = meta_by_id.get(r.get("article_id"), {})
        events.append(
            {
                "t": day,
                "articleId": r.get("article_id"),
                "title": (r.get("article_title") or "").strip(),
                "source": _source_label(meta.get("source") or r.get("article_source"), r.get("article_url")),
                "url": r.get("article_url"),
                "imageUrl": meta.get("image_url"),
                "sentiment": _round(r.get("sentiment_score") or 0),
                "age": _age_since(r.get("published_at")),
                "move": None if mv is None else f"{mv:+.1f}% next day",
                "impact": round(impact, 2),
            }
        )
    events.sort(key=lambda e: e["t"])
    return events


def news_events(
    ticker: str,
    window_days: int = 30,
    max_events: int = 5,
    points: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Auto-selected events: a sensible default when no director curates them.

    Pulls the full :func:`news_candidates` pool, then picks ``max_events`` that
    are **distributed across the window** (time-bucketed) and, within each
    bucket, ranked by ``impact``. This keeps the standalone scaffold usable, but
    the director (Claude Code) is expected to override ``chart.events`` from the
    full pool — ranking by a fixed heuristic alone tends to miss the story.
    """
    pool = news_candidates(ticker, window_days=window_days, points=points)
    for e in pool:
        e["_day"] = e["t"]
        e["_impact"] = e["impact"]
    chosen = _distribute_events_over_time(pool, max_events)
    chosen.sort(key=lambda e: e["_day"])
    return [{k: v for k, v in e.items() if not k.startswith("_") and k != "impact"} for e in chosen]


def price_daily_moves(points: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Close-to-close % move for each consecutive pair of price points.

    Returns ``{"from", "to", "pct"}`` per trading-day transition, oldest first.
    """
    pts = sorted((p for p in (points or []) if p.get("close") is not None), key=lambda p: p["t"])
    moves: list[dict[str, Any]] = []
    for a, b in zip(pts, pts[1:]):
        c0, c1 = a.get("close"), b.get("close")
        if not c0:
            continue
        moves.append({"from": a["t"], "to": b["t"], "pct": (c1 - c0) / c0 * 100})
    return moves


def move_catalysts(
    ticker: str,
    window_days: int = 30,
    points: list[dict[str, Any]] | None = None,
    top_moves: int = 8,
    per_move: int = 4,
) -> list[dict[str, Any]]:
    """Biggest price moves, each paired with the headlines that could explain it.

    Price-aware view for the director: ranks the largest close-to-close moves
    in the window, then for each attaches the articles published on the
    **session that produced the move** (close[from] → close[to]) — i.e. the
    news *just before* the move — so the director can pick the catalyst that
    explains each drop or gain. Articles per move are ranked by |sentiment| and
    capped at ``per_move``. Returned oldest→newest with the strongest move
    marked, so it reads as a timeline.
    """
    client, schema = _supabase()
    since = datetime.now(timezone.utc) - timedelta(days=window_days)
    rows = (
        client.schema(schema)
        .table("ticker_sentiment_heads_v")
        .select("article_id,sentiment_score,article_title,article_url,article_source,published_at")
        .eq("ticker", ticker.upper().strip())
        .gte("published_at", since.isoformat())
        .order("published_at", desc=False)
        .limit(2000)
        .execute()
        .data
        or []
    )
    by_day: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        pub = r.get("published_at")
        if not pub or not (r.get("article_title") or "").strip():
            continue
        by_day[str(pub)[:10]].append(r)

    moves = price_daily_moves(points)
    ranked = sorted(moves, key=lambda m: abs(m["pct"]), reverse=True)[: max(top_moves, 0)]
    rank_by_key = {(m["from"], m["to"]): i for i, m in enumerate(ranked)}

    # Batch-fetch image_url + source for every article we'll surface.
    picked_ids: list[Any] = []
    arts_by_move: dict[tuple, list[dict]] = {}
    for m in ranked:
        arts = sorted(
            by_day.get(m["from"], []),
            key=lambda r: abs(float(r.get("sentiment_score") or 0)),
            reverse=True,
        )[: max(per_move, 0)]
        arts_by_move[(m["from"], m["to"])] = arts
        picked_ids += [a.get("article_id") for a in arts if a.get("article_id") is not None]

    meta_by_id: dict[Any, dict] = {}
    if picked_ids:
        meta_rows = (
            client.schema(schema)
            .table("news_articles")
            .select("id,image_url,source")
            .in_("id", picked_ids)
            .execute()
            .data
            or []
        )
        meta_by_id = {m["id"]: m for m in meta_rows}

    out: list[dict[str, Any]] = []
    for m in sorted(ranked, key=lambda m: m["from"]):
        pct = m["pct"]
        candidates = []
        for a in arts_by_move[(m["from"], m["to"])]:
            meta = meta_by_id.get(a.get("article_id"), {})
            candidates.append(
                {
                    "t": str(a.get("published_at"))[:10],
                    "articleId": a.get("article_id"),
                    "title": (a.get("article_title") or "").strip(),
                    "source": _source_label(meta.get("source") or a.get("article_source"), a.get("article_url")),
                    "url": a.get("article_url"),
                    "imageUrl": meta.get("image_url"),
                    "sentiment": _round(a.get("sentiment_score") or 0),
                    "age": _age_since(a.get("published_at")),
                }
            )
        out.append(
            {
                "from": m["from"],
                "to": m["to"],
                "move": f"{pct:+.1f}%",
                "pct": round(pct, 2),
                "direction": "gain" if pct >= 0 else "drop",
                "rank": rank_by_key[(m["from"], m["to"])] + 1,
                "candidates": candidates,
            }
        )
    return out


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
    window_days: int = 30,
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
# Stock card (poster) — CEO/hero portrait + logo + headline + stat cards
# ---------------------------------------------------------------------------


def _fmt_money(n: Any) -> str | None:
    """Compact currency, e.g. 1.23e12 -> '$1.2T', 950_000 -> '$950.0K'."""
    if n is None:
        return None
    try:
        v = float(n)
    except (TypeError, ValueError):
        return None
    for unit, div in (("T", 1e12), ("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if abs(v) >= div:
            return f"${v / div:.1f}{unit}"
    return f"${v:,.0f}"


def _fmt_pct(n: Any) -> str | None:
    if n is None:
        return None
    try:
        return f"{float(n):+.2f}%"
    except (TypeError, ValueError):
        return None


def _fmt_price(n: Any) -> str | None:
    if n is None:
        return None
    try:
        v = float(n)
    except (TypeError, ValueError):
        return None
    return f"${v:,.0f}" if abs(v) >= 1000 else f"${v:.2f}"


def company_profile(ticker: str) -> dict[str, Any]:
    """FMP company profile: name, logo image, CEO, sector, exchange, …

    Best-effort: returns ``{}`` on any failure so the card still builds from
    director-supplied copy. Uses the v3 ``profile/{ticker}`` endpoint.
    """
    ticker = ticker.upper().strip()
    try:
        resp = requests.get(
            f"https://financialmodelingprep.com/api/v3/profile/{ticker}",
            params={"apikey": _fmp_key()},
            timeout=30,
        )
        if resp.status_code != 200:
            log.warning("FMP profile %s returned %s", ticker, resp.status_code)
            return {}
        rows = resp.json() or []
        return rows[0] if rows else {}
    except Exception as exc:  # noqa: BLE001 — enrichment is best-effort
        log.warning("FMP profile %s failed: %s", ticker, exc)
        return {}


def fmp_quote(ticker: str) -> dict[str, Any]:
    """FMP full quote: price, changesPercentage, marketCap, pe, eps, volume, …

    Best-effort: returns ``{}`` on failure. Uses the v3 ``quote/{ticker}`` path.
    """
    ticker = ticker.upper().strip()
    try:
        resp = requests.get(
            f"https://financialmodelingprep.com/api/v3/quote/{ticker}",
            params={"apikey": _fmp_key()},
            timeout=30,
        )
        if resp.status_code != 200:
            log.warning("FMP quote %s returned %s", ticker, resp.status_code)
            return {}
        rows = resp.json() or []
        return rows[0] if rows else {}
    except Exception as exc:  # noqa: BLE001
        log.warning("FMP quote %s failed: %s", ticker, exc)
        return {}


def news_pulse(ticker: str, window_days: int = 14) -> dict[str, Any]:
    """Internal news-impact pulse for a ticker over the window.

    Aggregates ``ticker_sentiment_heads_v`` into article volume + mean
    sentiment and derives an advisory 0–10 ``impactScore`` (the on-brand analog
    to eyeball.football's rating). The score is directional: neutral ≈ 5, strong
    bullish coverage ≈ 10, strong bearish ≈ 0. Heuristic — the director can
    override the badge per card.
    """
    client, schema = _supabase()
    since = datetime.now(timezone.utc) - timedelta(days=window_days)
    rows = (
        client.schema(schema)
        .table("ticker_sentiment_heads_v")
        .select("sentiment_score,published_at")
        .eq("ticker", ticker.upper().strip())
        .gte("published_at", since.isoformat())
        .limit(5000)
        .execute()
        .data
        or []
    )
    scores = [float(r.get("sentiment_score") or 0) for r in rows if r.get("sentiment_score") is not None]
    count = len(scores)
    avg = sum(scores) / count if count else 0.0
    pos = sum(1 for s in scores if s > 0.05)
    vol_factor = min(count / 30.0, 1.0)
    raw = 5.0 + avg * 4.0 + vol_factor
    score = round(max(0.0, min(10.0, raw)), 1)
    return {
        "ticker": ticker.upper().strip(),
        "windowDays": window_days,
        "newsCount": count,
        "avgSentiment": _round(avg),
        "posShare": _round(pos / count) if count else 0.0,
        "impactScore": score,
    }


def screening_memberships(ticker: str) -> list[dict[str, str]]:
    """Latest market screenings that currently feature ``ticker``.

    For every active ``market_screenings`` row we look at its most recent
    completed result and check whether the ticker is one of that run's result
    rows. Returns ``[{"name", "slug"}, …]`` in screening-name order. Test
    screenings (name/slug contains "test") are skipped so promo cards only ever
    carry real, public screenings. Best-effort: any DB error yields ``[]`` so a
    card can still render offline.
    """
    tk = (ticker or "").upper().strip()
    if not tk:
        return []
    try:
        client, schema = _supabase()
        screenings = (
            client.schema(schema)
            .table("market_screenings")
            .select("id, name, slug, is_active")
            .eq("is_active", True)
            .execute()
            .data
            or []
        )
    except Exception as exc:  # network / auth / schema — never fatal for a card
        log.warning("screening_memberships: could not list screenings: %s", exc)
        return []

    out: list[dict[str, str]] = []
    for s in screenings:
        name = (s.get("name") or "").strip()
        slug = (s.get("slug") or "").strip()
        if "test" in name.lower() or "test" in slug.lower():
            continue
        try:
            latest = (
                client.schema(schema)
                .table("market_screening_results")
                .select("id")
                .eq("market_screening_id", s["id"])
                .eq("status", "done")
                .order("run_at", desc=True)
                .limit(1)
                .execute()
                .data
                or []
            )
            if not latest:
                continue
            hit = (
                client.schema(schema)
                .table("market_screening_result_rows")
                .select("symbol")
                .eq("result_id", latest[0]["id"])
                .eq("symbol", tk)
                .limit(1)
                .execute()
                .data
                or []
            )
            if hit:
                out.append({"name": name or slug or tk, "slug": slug})
        except Exception as exc:
            log.warning(
                "screening_memberships: membership check failed for %s: %s",
                slug or name,
                exc,
            )
            continue

    out.sort(key=lambda m: m["name"].lower())
    return out


def build_card(
    ticker: str,
    window_days: int = 14,
    *,
    headline: str | None = None,
    tag: str | None = None,
    hero_image_url: str | None = None,
    badge: dict[str, Any] | None = None,
    stats: list[dict[str, Any]] | None = None,
    nis_screenings: list[str] | None = None,
) -> dict[str, Any]:
    """Assemble the data half of a stock-card spec for a ticker.

    Pulls the FMP company profile (name/logo/CEO/sector) + quote (price stats)
    and the internal :func:`news_pulse`, then fills sensible defaults the
    director edits: a 4-up stat grid, an Impact badge, and identity fields.

    The **hero portrait** is left to the director: pass ``hero_image_url`` with a
    fetched CEO photo (the eyeball.football look). When absent the renderer falls
    back to the company logo on a branded gradient.
    """
    ticker = ticker.upper().strip()
    profile = company_profile(ticker)
    quote = fmp_quote(ticker)
    pulse = news_pulse(ticker, window_days=window_days)

    if stats is None:
        stats = []
        price = _fmt_price(quote.get("price"))
        if price:
            stats.append({"label": "Price", "value": price})
        chg = _fmt_pct(quote.get("changesPercentage"))
        if chg:
            stats.append({"label": "Change", "value": chg})
        mc = _fmt_money(quote.get("marketCap") or profile.get("mktCap"))
        if mc:
            stats.append({"label": "Market Cap", "value": mc})
        pe = quote.get("pe")
        if pe is not None:
            try:
                stats.append({"label": "P/E", "value": f"{float(pe):.1f}"})
            except (TypeError, ValueError):
                pass
        stats.append({"label": "News (14d)", "value": str(pulse["newsCount"])})
        stats = stats[:4]

    if badge is None:
        avg = pulse["avgSentiment"]
        tone = "positive" if avg > 0.05 else "negative" if avg < -0.05 else "neutral"
        badge = {"label": "Impact", "value": f'{pulse["impactScore"]:.1f}', "tone": tone}

    # NIS credibility badge: the latest screenings this ticker is featured in
    # (e.g. "NIS Momentum", "NIS Fundamentals"). Auto-detected from the DB unless
    # the caller passes an explicit list.
    if nis_screenings is None:
        nis_screenings = [m["name"] for m in screening_memberships(ticker)]

    return {
        "ticker": ticker,
        "company": (profile.get("companyName") or ticker).strip(),
        "ceo": (profile.get("ceo") or "").strip() or None,
        "sector": (profile.get("sector") or "").strip() or None,
        "exchange": (profile.get("exchangeShortName") or "").strip() or None,
        "logoUrl": profile.get("image"),
        # Director fetches a CEO photo and passes it; else the renderer uses the
        # logo as the centrepiece on a branded gradient.
        "heroImageUrl": hero_image_url,
        "headline": (headline or "<EDIT: the hook headline>").strip(),
        "tag": (tag or "").strip() or None,
        "badge": badge,
        "stats": stats,
        "nisScreenings": nis_screenings,
        "cta": "Swipe to Watch",
        "footer": "newsimpactscreener.com",
        "pulse": pulse,
    }


# ---------------------------------------------------------------------------
# Inspection helpers (for the director to eyeball what's moving)
# ---------------------------------------------------------------------------


def trend_snapshot(window_days: int = 30) -> dict[str, Any]:
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
