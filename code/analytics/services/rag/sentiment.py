"""
Market sentiment retrieval — cluster trends, dimension trends, ticker sentiment.

Consolidates:
  - services/agent/data_queries.get_cluster_trends  (+ label enrichment from video)
  - services/agent/data_queries.get_dimension_trends
  - services/agent/data_queries.get_ticker_sentiment
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from shared.db import get_supabase_client
from .taxonomy import CLUSTER_ID_TO_LABEL, DIM_KEY_TO_LABEL

log = logging.getLogger(__name__)


def _client():
    return get_supabase_client(), "swingtrader"


def get_cluster_trends(hours: int = 14) -> list[dict[str, Any]]:
    """Cluster-level sentiment scores, most recent first.

    Columns: cluster_id, cluster_label, bucket_day, cluster_avg,
             cluster_weighted_avg, bucket_article_count, article_count.
    """
    client, schema = _client()
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    res = (
        client.schema(schema)
        .table("news_trends_cluster_daily_v")
        .select("*")
        .gte("bucket_day", since.strftime("%Y-%m-%d"))
        .order("bucket_day", desc=True)
        .limit(30)
        .execute()
    )
    rows = res.data or []
    for r in rows:
        r["cluster_label"] = CLUSTER_ID_TO_LABEL.get(r.get("cluster_id", ""), r.get("cluster_id", ""))
    return rows


def get_dimension_trends(hours: int = 14) -> list[dict[str, Any]]:
    """Dimension-level sentiment scores, most recent first.

    Columns: dimension_key, dimension_label, bucket_day, dimension_avg,
             dimension_weighted_avg, article_count, bucket_article_count.
    """
    client, schema = _client()
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    res = (
        client.schema(schema)
        .table("news_trends_dimension_daily_v")
        .select("*")
        .gte("bucket_day", since.strftime("%Y-%m-%d"))
        .order("bucket_day", desc=True)
        .limit(60)
        .execute()
    )
    rows = res.data or []
    for r in rows:
        key = r.get("dimension_key", "")
        r["dimension_label"] = DIM_KEY_TO_LABEL.get(key, key.replace("_", " ").title())
    return rows


def get_ticker_sentiment(
    tickers: list[str] | None = None,
    hours: int = 24,
) -> list[dict[str, Any]]:
    """Per-article per-ticker sentiment from ticker_sentiment_heads_v.

    Columns: article_id, ticker, sentiment_score, title, url, published_at.
    """
    client, schema = _client()
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    q = (
        client.schema(schema)
        .table("ticker_sentiment_heads_v")
        .select("*")
        .gte("published_at", since.isoformat())
    )
    if tickers:
        q = q.in_("ticker", [t.upper() for t in tickers])
    return q.order("published_at", desc=True).limit(50).execute().data or []


def compute_cluster_summary(
    cluster_rows: list[dict],
    articles: list[dict],
) -> dict[str, Any]:
    """Aggregate cluster trends + article impact into a summary dict.

    Returns: cluster_ranking (sorted by abs score), top_dimensions (top 6),
             total_articles.
    """
    latest_by_cluster: dict[str, dict] = {}
    for r in cluster_rows:
        cid = r.get("cluster_id", "")
        if cid not in latest_by_cluster:
            latest_by_cluster[cid] = r

    ranked = sorted(
        latest_by_cluster.values(),
        key=lambda x: abs(x.get("cluster_weighted_avg", 0) or 0),
        reverse=True,
    )

    dim_totals: dict[str, float] = {}
    dim_counts: dict[str, int] = {}
    for a in articles:
        for dim, score in (a.get("impact_json") or {}).items():
            if isinstance(score, (int, float)):
                dim_totals[dim] = dim_totals.get(dim, 0.0) + score
                dim_counts[dim] = dim_counts.get(dim, 0) + 1

    dim_avgs = {
        dim: dim_totals[dim] / dim_counts[dim]
        for dim in dim_totals
        if dim_counts.get(dim, 0) >= 2
    }
    top_dims = sorted(dim_avgs.items(), key=lambda x: abs(x[1]), reverse=True)[:6]

    return {
        "cluster_ranking": [
            {
                "cluster": r.get("cluster_id", ""),
                "label": r.get("cluster_label") or CLUSTER_ID_TO_LABEL.get(r.get("cluster_id", ""), ""),
                "score": r.get("cluster_weighted_avg", 0) or 0,
                "article_count": r.get("bucket_article_count", 0) or 0,
            }
            for r in ranked
        ],
        "top_dimensions": [
            {
                "key": dim,
                "label": DIM_KEY_TO_LABEL.get(dim, dim.replace("_", " ").title()),
                "avg_score": score,
            }
            for dim, score in top_dims
        ],
        "total_articles": len(articles),
    }
