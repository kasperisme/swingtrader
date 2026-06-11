"""Assemble a news briefing from already-scored data (no LLM).

The article set for each ticker / tag is fetched through the SAME search the
public /articles page uses — the ``search_news_by_tags`` RPC over the GIN
``search_tags`` index (tickers stored upper-case, theme tags lower-case in the
same array). So a briefing for $AAPL or #ai surfaces exactly the articles the
site's search would, over the briefing's 24h window.

That RPC returns headline metadata only; the briefing then enriches each article
with data the scoring pipeline already stored — per-ticker sentiment + reasoning
(``ticker_sentiment_heads_v``) and per-article impact (``news_impact_vectors``).
Everything here is deterministic: a few indexed reads, no model calls.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from shared.db import _as_json, get_supabase_client
from shared.email import app_url

log = logging.getLogger(__name__)

_SCHEMA = "swingtrader"


def internal_article_url(slug: str | None, article_id: Any) -> str:
    """Canonical newsimpactscreener.com article link (slug, else id)."""
    base = app_url()
    if slug:
        return f"{base}/articles/{slug}"
    if article_id is not None:
        return f"{base}/articles/{article_id}"
    return base


def _norm_tickers(tickers: list[str] | None) -> list[str]:
    return list(dict.fromkeys((t or "").upper().strip() for t in (tickers or []) if (t or "").strip()))


def _norm_tags(tags: list[str] | None) -> list[str]:
    return list(dict.fromkeys((t or "").lower().strip() for t in (tags or []) if (t or "").strip()))


def _search_by_tags(
    tag_filter: list[str],
    *,
    lookback_hours: int,
    match_count: int,
    stream: str | None = None,
) -> list[dict[str, Any]]:
    """Reuse the /articles tag search RPC. Returns the article metadata rows
    (article_id, title, url, source, slug, image_url, article_stream,
    published_at, snippet, similarity). Never raises — returns [] on error.
    """
    if not tag_filter:
        return []
    client = get_supabase_client()
    try:
        res = client.schema(_SCHEMA).rpc(
            "search_news_by_tags",
            {
                "tag_filter": tag_filter,
                "match_count": match_count,
                "lookback_hours": lookback_hours,
                "stream_filter": stream,
            },
        ).execute()
        return res.data or []
    except Exception as exc:  # noqa: BLE001 — one bad tag must not sink the briefing
        log.warning("[briefing] search_news_by_tags(%s) failed: %s", tag_filter, exc)
        return []


def _ticker_sections(tickers: list[str], hours: int, per_ticker_limit: int = 6) -> list[dict[str, Any]]:
    """One section per ticker: the /articles search for that ticker, enriched
    with the stored per-ticker sentiment score + reasoning."""
    if not tickers:
        return []
    client = get_supabase_client()

    rows_by_ticker: dict[str, list[dict]] = {}
    article_ids: set[int] = set()
    for ticker in tickers:
        rows = _search_by_tags([ticker], lookback_hours=hours, match_count=per_ticker_limit * 3)
        rows_by_ticker[ticker] = rows
        article_ids.update(int(r["article_id"]) for r in rows if r.get("article_id") is not None)

    # One lookup for the per-(ticker, article) sentiment of every article above.
    sentiment: dict[tuple[str, int], dict] = {}
    if article_ids:
        sres = (
            client.schema(_SCHEMA)
            .table("ticker_sentiment_heads_v")
            .select("article_id, ticker, sentiment_score, reasoning_text")
            .in_("article_id", list(article_ids))
            .in_("ticker", tickers)
            .execute()
        ).data or []
        for r in sres:
            sentiment[(str(r["ticker"]).upper(), int(r["article_id"]))] = r

    sections: list[dict[str, Any]] = []
    for ticker in tickers:
        items: list[dict[str, Any]] = []
        scores: list[float] = []
        for r in rows_by_ticker.get(ticker, [])[:per_ticker_limit]:
            aid = int(r["article_id"]) if r.get("article_id") is not None else None
            sent = sentiment.get((ticker, aid)) if aid is not None else None
            score = float(sent["sentiment_score"]) if sent and sent.get("sentiment_score") is not None else None
            if score is not None:
                scores.append(score)
            reason = (sent.get("reasoning_text") if sent else None) or (r.get("snippet") or "")
            items.append({
                "article_id": aid,
                "slug": r.get("slug"),
                "title": r.get("title") or "(untitled)",
                "url": r.get("url") or "",
                "source": r.get("source") or "",
                "published_at": r.get("published_at"),
                "sentiment_score": round(score, 3) if score is not None else None,
                "sentiment_reason": reason.strip(),
            })
        avg = sum(scores) / len(scores) if scores else 0.0
        sections.append({
            "ticker": ticker,
            "article_count": len(items),
            "avg_sentiment": round(avg, 3),
            "items": items,
        })
    return sections


def _tag_sections(tags: list[str], hours: int, per_tag_limit: int = 8) -> list[dict[str, Any]]:
    """One section per tag: the /articles search for that tag, ranked by stored
    impact magnitude (with top impact dimensions)."""
    if not tags:
        return []
    client = get_supabase_client()

    sections: list[dict[str, Any]] = []
    for tag in tags:
        rows = _search_by_tags([tag], lookback_hours=hours, match_count=per_tag_limit * 3)
        if not rows:
            sections.append({"tag": tag, "article_count": 0, "items": []})
            continue

        ids = [int(r["article_id"]) for r in rows if r.get("article_id") is not None]
        vecs: dict[int, dict] = {}
        if ids:
            vres = (
                client.schema(_SCHEMA)
                .table("news_impact_vectors")
                .select("article_id, impact_json, top_dimensions")
                .in_("article_id", ids)
                .execute()
            ).data or []
            vecs = {int(v["article_id"]): v for v in vres}

        items: list[dict[str, Any]] = []
        for r in rows:
            aid = int(r["article_id"]) if r.get("article_id") is not None else None
            v = vecs.get(aid) if aid is not None else None
            impact = _as_json(v["impact_json"], default={}) if v else {}
            magnitude = sum(abs(val) for val in impact.values() if isinstance(val, (int, float)))
            items.append({
                "article_id": aid,
                "slug": r.get("slug"),
                "title": r.get("title") or "(untitled)",
                "url": r.get("url") or "",
                "source": r.get("source") or "",
                "published_at": r.get("published_at"),
                "magnitude": round(magnitude, 3),
                "top_dimensions": _as_json(v["top_dimensions"], default=[]) if v else [],
            })

        # Strongest impact first; the RPC already returned newest-first so ties
        # keep recency.
        items.sort(key=lambda x: x["magnitude"], reverse=True)
        sections.append({"tag": tag, "article_count": len(items[:per_tag_limit]), "items": items[:per_tag_limit]})
    return sections


def gather_briefing(
    tickers: list[str] | None,
    tags: list[str] | None,
    hours: int = 24,
) -> dict[str, Any]:
    """Build the full briefing payload for a subscription's watchlist.

    Returns a dict consumed by render.py. Always well-formed even when nothing
    matched in the window (``total_articles == 0``) so the caller can still send
    a "quiet day" briefing.
    """
    tickers = _norm_tickers(tickers)
    tags = _norm_tags(tags)

    ticker_sections = _ticker_sections(tickers, hours)
    tag_sections = _tag_sections(tags, hours)

    total = sum(s["article_count"] for s in ticker_sections) + sum(
        s["article_count"] for s in tag_sections
    )
    briefing = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window_hours": hours,
        "tickers": ticker_sections,
        "tags": tag_sections,
        "total_articles": total,
        "references": [],
    }
    assign_references(briefing)
    return briefing


def assign_references(briefing: dict[str, Any]) -> list[dict[str, Any]]:
    """Number every distinct article once across the whole briefing and stamp
    each item with its reference number (``item['ref']``).

    Articles shared between sections (e.g. a story tagged with two tickers) get a
    single shared number. Links point at the canonical newsimpactscreener.com
    article page. Returns the ordered reference list and stores it on
    ``briefing['references']`` for the narrative + the end-of-PDF sources list.
    """
    refs: list[dict[str, Any]] = []
    by_article: dict[Any, int] = {}

    def _register(item: dict[str, Any]) -> None:
        aid = item.get("article_id")
        key = aid if aid is not None else f"u:{item.get('url') or item.get('title')}"
        if key not in by_article:
            n = len(refs) + 1
            by_article[key] = n
            refs.append({
                "n": n,
                "title": item.get("title") or "(untitled)",
                "source": item.get("source") or "",
                "url": internal_article_url(item.get("slug"), aid),
                "published_at": item.get("published_at"),
            })
        item["ref"] = by_article[key]

    for section in briefing.get("tickers", []):
        for item in section.get("items", []):
            _register(item)
    for section in briefing.get("tags", []):
        for item in section.get("items", []):
            _register(item)

    briefing["references"] = refs
    return refs
