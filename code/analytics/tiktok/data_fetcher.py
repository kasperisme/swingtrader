from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from src.db import get_supabase_client, get_schema, _as_json

from .config import (
    LOOKBACK_HOURS,
    MAX_ARTICLES,
    CLUSTER_ID_TO_LABEL,
    DIM_KEY_TO_LABEL,
)

log = logging.getLogger(__name__)


def fetch_cluster_trends(hours: int | None = None) -> list[dict[str, Any]]:
    hours = hours or LOOKBACK_HOURS
    client = get_supabase_client()
    schema = get_schema()

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
    log.info("Fetched %d cluster daily trend rows", len(rows))
    return rows


def fetch_top_articles(max_articles: int | None = None) -> list[dict[str, Any]]:
    max_articles = max_articles or MAX_ARTICLES
    client = get_supabase_client()
    schema = get_schema()

    since = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)

    art_res = (
        client.schema(schema)
        .table("news_articles")
        .select("id, title, url, source, created_at")
        .gte("created_at", since.isoformat())
        .order("created_at", desc=True)
        .limit(max_articles * 3)
        .execute()
    )
    articles = art_res.data or []
    if not articles:
        log.warning("No articles in last %d hours", LOOKBACK_HOURS)
        return []

    article_ids = [a["id"] for a in articles]

    vec_res = (
        client.schema(schema)
        .table("news_impact_vectors")
        .select("article_id, impact_json, top_dimensions")
        .in_("article_id", article_ids)
        .execute()
    )
    vectors_by_id = {v["article_id"]: v for v in (vec_res.data or [])}

    enriched = []
    for a in articles:
        vec = vectors_by_id.get(a["id"])
        if vec is None:
            continue
        impact = _as_json(vec["impact_json"], default={})
        magnitude = sum(abs(v) for v in impact.values() if isinstance(v, (int, float)))
        enriched.append({
            **a,
            "impact_json": impact,
            "top_dimensions": _as_json(vec["top_dimensions"], default=[]),
            "magnitude": magnitude,
        })

    enriched.sort(key=lambda x: x["magnitude"], reverse=True)
    log.info("Fetched %d scored articles", len(enriched))
    return enriched[:max_articles]


def fetch_tickers_for_articles(article_ids: list[int]) -> dict[int, list[str]]:
    if not article_ids:
        return {}
    client = get_supabase_client()
    schema = get_schema()
    res = (
        client.schema(schema)
        .table("news_article_tickers")
        .select("article_id, ticker")
        .in_("article_id", article_ids)
        .execute()
    )
    out: dict[int, list[str]] = {}
    for row in res.data or []:
        out.setdefault(row["article_id"], []).append(row["ticker"])
    return out


def compute_cluster_summary(
    cluster_rows: list[dict],
    articles: list[dict],
) -> dict[str, Any]:
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
                "label": CLUSTER_ID_TO_LABEL.get(r.get("cluster_id", ""), r.get("cluster_id", "")),
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
