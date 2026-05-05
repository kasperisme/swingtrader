"""
News article retrieval — top articles, ticker news, ticker-article mapping.

Consolidates:
  - services/agent/data_queries.get_top_articles
  - services/agent/data_queries.get_ticker_news
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from shared.db import get_supabase_client, _as_json

log = logging.getLogger(__name__)


def _client():
    return get_supabase_client(), "swingtrader"


def get_top_articles(
    tickers: list[str] | None = None,
    hours: int = 14,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Top-scored articles sorted by impact magnitude.

    Returns: title, url, source, published_at, impact_json, top_dimensions, magnitude.
    """
    client, schema = _client()
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    since_iso = since.isoformat()

    q = (
        client.schema(schema)
        .table("news_articles")
        .select("id, title, url, source, created_at, published_at")
        .gte("created_at", since_iso)
        .order("created_at", desc=True)
        .limit(limit * 3)
    )

    if tickers:
        tick_res = (
            client.schema(schema)
            .table("news_article_tickers")
            .select("article_id")
            .in_("ticker", [t.upper() for t in tickers])
            .execute()
        )
        article_ids = list({r["article_id"] for r in (tick_res.data or [])})
        if not article_ids:
            return []
        q = q.in_("id", article_ids)

    articles = q.execute().data or []
    if not articles:
        return []

    ids = [a["id"] for a in articles]
    vec_res = (
        client.schema(schema)
        .table("news_impact_vectors")
        .select("article_id, impact_json, top_dimensions")
        .in_("article_id", ids)
        .execute()
    )
    vecs = {v["article_id"]: v for v in (vec_res.data or [])}

    out = []
    for a in articles:
        v = vecs.get(a["id"])
        if not v:
            continue
        impact = _as_json(v["impact_json"], default={})
        magnitude = sum(abs(val) for val in impact.values() if isinstance(val, (int, float)))
        out.append({
            **a,
            "impact_json": impact,
            "top_dimensions": _as_json(v["top_dimensions"], default=[]),
            "magnitude": magnitude,
        })

    out.sort(key=lambda x: x["magnitude"], reverse=True)
    return out[:limit]


def fetch_tickers_for_articles(article_ids: list[int]) -> dict[int, list[str]]:
    """Map article IDs → list of associated ticker symbols."""
    if not article_ids:
        return {}
    client, schema = _client()
    res = (
        client.schema(schema)
        .table("news_article_tickers")
        .select("article_id, ticker")
        .in_("article_id", article_ids)
        .execute()
    )
    out: dict[int, list[str]] = {}
    for row in (res.data or []):
        out.setdefault(row["article_id"], []).append(row["ticker"])
    return out


def get_ticker_news(
    tickers: list[str],
    hours: int = 24,
    per_ticker_limit: int = 5,
) -> list[dict[str, Any]]:
    """Per-ticker articles with sentiment scores and relationship annotations.

    Uses get_relationship_node_news RPC (alias resolution + direct mentions)
    then enriches with TICKER_SENTIMENT and TICKER_RELATIONSHIPS heads.

    Returns: ticker, article_id, title, url, published_at,
             sentiment_score, sentiment_reason, relationships.
    """
    if not tickers:
        return []
    normalized = list(dict.fromkeys(t.upper().strip() for t in tickers if t and t.strip()))
    if not normalized:
        return []

    client, schema = _client()
    days_lookback = max(1, -(-hours // 24))

    article_rows: list[tuple[str, int, str, str, str | None]] = []
    seen_ids: set[tuple[str, int]] = set()
    for ticker in normalized:
        res = client.schema(schema).rpc("get_relationship_node_news", {
            "p_ticker": ticker,
            "p_page": 1,
            "p_page_size": per_ticker_limit,
            "p_days_lookback": days_lookback,
        }).execute()
        for r in (res.data or []):
            canonical = (r.get("canonical_ticker") or ticker).upper().strip()
            article_id = int(r["article_id"])
            key = (canonical, article_id)
            if key in seen_ids:
                continue
            seen_ids.add(key)
            article_rows.append((
                canonical, article_id,
                r.get("title") or "", r.get("url") or "",
                r.get("published_at"),
            ))

    if not article_rows:
        return []

    article_ids = list({r[1] for r in article_rows})
    heads_res = (
        client.schema(schema)
        .table("news_impact_heads")
        .select("article_id,cluster,scores_json,reasoning_json")
        .in_("article_id", article_ids)
        .in_("cluster", ["TICKER_SENTIMENT", "TICKER_RELATIONSHIPS"])
        .execute()
    )

    sentiment_by_article: dict[int, tuple[dict, dict]] = {}
    relationships_by_article: dict[int, list[dict]] = {}
    for r in (heads_res.data or []):
        aid = int(r["article_id"])
        scores = _as_json(r["scores_json"], {})
        reasoning = _as_json(r["reasoning_json"], {})
        if r["cluster"] == "TICKER_SENTIMENT":
            sentiment_by_article[aid] = (scores, reasoning)
        elif r["cluster"] == "TICKER_RELATIONSHIPS":
            parsed = []
            for key, strength in scores.items():
                parts = str(key).split("__")
                if len(parts) == 3:
                    parsed.append({
                        "from": parts[0], "to": parts[1], "type": parts[2],
                        "strength": strength, "notes": reasoning.get(key, ""),
                    })
            relationships_by_article[aid] = parsed

    out: list[dict[str, Any]] = []
    for canonical, article_id, title, url, published_at in article_rows:
        scores, reasons = sentiment_by_article.get(article_id, ({}, {}))
        sentiment_score = float(scores.get(canonical) or 0.0)
        sentiment_reason = str(reasons.get(canonical) or "")
        all_rels = relationships_by_article.get(article_id, [])
        relevant_rels = [r for r in all_rels if r["from"] == canonical or r["to"] == canonical]
        out.append({
            "ticker": canonical,
            "article_id": article_id,
            "title": title,
            "url": url,
            "published_at": published_at,
            "sentiment_score": sentiment_score,
            "sentiment_reason": sentiment_reason,
            "relationships": relevant_rels,
        })

    per_ticker: dict[str, list] = {}
    for item in out:
        per_ticker.setdefault(item["ticker"], []).append(item)

    flat: list[dict[str, Any]] = []
    for t in normalized:
        items = per_ticker.get(t, [])
        items.sort(key=lambda x: x.get("published_at") or "", reverse=True)
        flat.extend(items[:per_ticker_limit])
    return flat
