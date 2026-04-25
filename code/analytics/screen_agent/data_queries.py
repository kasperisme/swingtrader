"""
data_queries.py — Supabase query wrappers exposed as tools to the LLM agent.

Each function returns plain Python dicts/lists that the agent can reason over.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from src.db import get_supabase_client, get_schema, _as_json

log = logging.getLogger(__name__)


def _client():
    return get_supabase_client(), get_schema()


def get_cluster_trends(hours: int = 14) -> list[dict[str, Any]]:
    """Latest cluster-level sentiment scores from news_trends_cluster_daily_v.

    Returns one row per cluster per day, most recent first.
    Columns: cluster_id, bucket_day, cluster_avg, cluster_weighted_avg,
             bucket_article_count, article_count.
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
    return res.data or []


def get_dimension_trends(cluster: str | None = None, hours: int = 14) -> list[dict[str, Any]]:
    """Dimension-level sentiment scores from news_trends_dimension_daily_v.

    Optionally filter to one cluster (e.g. 'MACRO_SENSITIVITY').
    Returns rows with: dimension_key, cluster_id, bucket_day, dim_avg,
                        dim_weighted_avg, article_count.
    """
    client, schema = _client()
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    q = (
        client.schema(schema)
        .table("news_trends_dimension_daily_v")
        .select("*")
        .gte("bucket_day", since.strftime("%Y-%m-%d"))
    )
    if cluster:
        q = q.eq("cluster_id", cluster)
    res = q.order("bucket_day", desc=True).limit(60).execute()
    return res.data or []


def get_ticker_sentiment(
    tickers: list[str] | None = None,
    hours: int = 24,
) -> list[dict[str, Any]]:
    """Per-article per-ticker sentiment from ticker_sentiment_heads_v.

    Returns rows with: article_id, ticker, sentiment_score, title, url, published_at.
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
    res = q.order("published_at", desc=True).limit(50).execute()
    return res.data or []


def get_top_articles(
    tickers: list[str] | None = None,
    hours: int = 14,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Top-scored articles with full impact vectors.

    Returns: title, url, source, published_at, impact_json, top_dimensions, magnitude.
    """
    client, schema = _client()
    since = datetime.now(timezone.utc) - timedelta(hours=hours)

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
    else:
        article_ids = None

    q = (
        client.schema(schema)
        .table("news_articles")
        .select("id, title, url, source, created_at, published_at")
        .gte("created_at", since.isoformat())
        .order("created_at", desc=True)
        .limit(limit * 3)
    )
    if article_ids is not None:
        q = q.in_("id", article_ids)
    art_res = q.execute()
    articles = art_res.data or []
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


def get_ticker_relationships(ticker: str, hops: int = 1) -> dict[str, Any]:
    """Graph neighborhood around a ticker via get_relationship_neighborhood RPC."""
    client, schema = _client()
    res = client.schema(schema).rpc(
        "get_relationship_neighborhood",
        {"p_seed": ticker.upper(), "p_hops": hops},
    ).execute()
    return res.data or {}


def get_company_vectors(tickers: list[str]) -> list[dict[str, Any]]:
    """Latest company factor vectors for the given tickers."""
    client, schema = _client()
    out = []
    for t in tickers:
        res = (
            client.schema(schema)
            .table("company_vectors")
            .select("ticker, vector_date, dimensions_json")
            .eq("ticker", t.upper())
            .order("vector_date", desc=True)
            .limit(1)
            .execute()
        )
        if res.data:
            row = res.data[0]
            row["dimensions_json"] = _as_json(row.get("dimensions_json"), default={})
            out.append(row)
    return out


# ── User-specific tools (require user_id) ────────────────────────────────────

def get_user_positions(user_id: str) -> list[dict[str, Any]]:
    """Net open position per ticker from user_trades.

    Returns list of {ticker, net_qty, avg_cost, side}.
    net_qty > 0 = long, < 0 = short. avg_cost is weighted average entry price.
    """
    from src.db import get_pg_connection

    schema = get_schema()
    sql = f"""
        SELECT
            ticker,
            SUM(
                CASE
                    WHEN side = 'buy'  AND position_side = 'long'  THEN  quantity
                    WHEN side = 'sell' AND position_side = 'long'  THEN -quantity
                    WHEN side = 'sell' AND position_side = 'short' THEN  quantity
                    WHEN side = 'buy'  AND position_side = 'short' THEN -quantity
                    ELSE 0
                END
            ) AS net_qty,
            SUM(
                CASE WHEN side = 'buy' THEN quantity * price_per_unit ELSE 0 END
            ) / NULLIF(SUM(CASE WHEN side = 'buy' THEN quantity ELSE 0 END), 0)
                AS avg_cost
        FROM {schema}.user_trades
        WHERE user_id = %s
        GROUP BY ticker
        HAVING SUM(
            CASE
                WHEN side = 'buy'  AND position_side = 'long'  THEN  quantity
                WHEN side = 'sell' AND position_side = 'long'  THEN -quantity
                WHEN side = 'sell' AND position_side = 'short' THEN  quantity
                WHEN side = 'buy'  AND position_side = 'short' THEN -quantity
                ELSE 0
            END
        ) != 0
        ORDER BY ticker
    """
    conn = get_pg_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql, (user_id,))
        rows = cur.fetchall() or []
        return [
            {
                "ticker": r[0],
                "net_qty": float(r[1]),
                "side": "long" if float(r[1]) > 0 else "short",
                "avg_cost": round(float(r[2]), 2) if r[2] else None,
            }
            for r in rows
        ]
    finally:
        conn.close()


def get_user_alerts(user_id: str) -> list[dict[str, Any]]:
    """Active alerts with latest prices and proximity.

    Returns list of {ticker, alert_type, alert_price, direction, notes,
                     latest_price, pct_away}.
    """
    from src.db import get_pg_connection

    schema = get_schema()
    conn = get_pg_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            f"""
            SELECT ticker, alert_type, price, direction, notes
            FROM {schema}.user_portfolio_alerts
            WHERE user_id = %s AND is_active = TRUE
            ORDER BY ticker, alert_type
            """,
            (user_id,),
        )
        alert_rows = cur.fetchall() or []
        if not alert_rows:
            return []

        alert_tickers = list({r[0] for r in alert_rows})

        cur.execute(
            f"""
            SELECT DISTINCT ON (sr.symbol)
                sr.symbol,
                (sr.row_data->>'close')::numeric AS close_price
            FROM {schema}.user_scan_rows sr
            WHERE sr.user_id = %s
              AND sr.symbol = ANY(%s)
              AND sr.row_data ? 'close'
            ORDER BY sr.symbol, sr.scan_date DESC, sr.id DESC
            """,
            (user_id, alert_tickers),
        )
        price_map: dict[str, float] = {}
        for r in (cur.fetchall() or []):
            if r[1] is not None:
                price_map[r[0]] = float(r[1])

        out = []
        for ticker, alert_type, alert_price, direction, notes in alert_rows:
            latest = price_map.get(ticker)
            pct_away = None
            if latest and float(alert_price) > 0:
                pct_away = round((latest - float(alert_price)) / float(alert_price) * 100, 2)
            out.append({
                "ticker": ticker,
                "alert_type": alert_type,
                "alert_price": float(alert_price),
                "direction": direction,
                "notes": notes,
                "latest_price": latest,
                "pct_away": pct_away,
            })
        return out
    finally:
        conn.close()


def get_user_screening_notes(user_id: str) -> list[str]:
    """Active screening tickers from the user's latest scan run.

    Returns a flat list of ticker symbols.
    """
    from src.db import get_pg_connection

    schema = get_schema()
    sql = f"""
        WITH latest_run AS (
            SELECT id
            FROM {schema}.user_scan_runs
            WHERE user_id = %s
              AND COALESCE(status, 'active') = 'active'
            ORDER BY scan_date DESC, id DESC
            LIMIT 1
        )
        SELECT DISTINCT n.ticker
        FROM {schema}.user_scan_row_notes n
        JOIN latest_run lr ON lr.id = n.run_id
        WHERE n.user_id = %s
          AND n.status = 'active'
          AND n.ticker IS NOT NULL
          AND btrim(n.ticker) <> ''
        ORDER BY n.ticker
    """
    conn = get_pg_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql, (user_id, user_id))
        return [r[0] for r in (cur.fetchall() or [])]
    finally:
        conn.close()


def search_news(
    query: str,
    *,
    lookback_hours: int = 24,
    tickers: list[str] | None = None,
    limit: int = 12,
) -> list[dict[str, Any]]:
    """Semantic search over news articles using vector similarity.

    Returns list of {article_id, title, url, published_at, snippet, similarity}.
    """
    from news_impact.semantic_retrieval import search_news_embeddings

    results = search_news_embeddings(
        query,
        lookback_hours=lookback_hours,
        tickers=tickers,
        limit=limit,
    )
    return results
