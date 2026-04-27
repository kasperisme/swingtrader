"""
data_queries.py — Supabase query wrappers exposed as tools to the LLM agent.

Each function returns plain Python dicts/lists that the agent can reason over.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from shared.db import get_supabase_client, _as_json

log = logging.getLogger(__name__)


def _client():
    """Return (supabase_client, schema_name) — convenience shorthand for screening queries."""
    return get_supabase_client(), "swingtrader"


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


def get_dimension_trends(hours: int = 14) -> list[dict[str, Any]]:
    """Dimension-level sentiment scores from news_trends_dimension_daily_v.

    Returns rows with: dimension_key, bucket_day, dimension_avg,
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
    if not tickers:
        return []
    client, schema = _client()
    upper = list(dict.fromkeys(t.upper().strip() for t in tickers))
    res = (
        client.schema(schema)
        .table("company_vectors")
        .select("ticker, vector_date, dimensions_json")
        .in_("ticker", upper)
        .order("ticker")
        .order("vector_date", desc=True)
        .limit(len(upper) * 5)
        .execute()
    )
    best: dict[str, dict] = {}
    for r in (res.data or []):
        t = r["ticker"]
        if t not in best:
            r["dimensions_json"] = _as_json(r.get("dimensions_json"), default={})
            best[t] = r
    return list(best.values())


# ── User-specific tools (require user_id) ────────────────────────────────────

def get_user_positions(user_id: str) -> list[dict[str, Any]]:
    """Net open position per ticker from user_trades.

    Returns list of {ticker, net_qty, avg_cost, side}.
    net_qty > 0 = long, < 0 = short. avg_cost is weighted average entry price.
    """
    client, schema = _client()
    res = client.schema(schema).table("user_trades") \
        .select("ticker,side,position_side,quantity,price_per_unit") \
        .eq("user_id", user_id) \
        .execute()

    net_qty: dict[str, float] = defaultdict(float)
    buy_value: dict[str, float] = defaultdict(float)
    buy_qty: dict[str, float] = defaultdict(float)

    for t in (res.data or []):
        ticker = t["ticker"]
        qty = float(t["quantity"])
        side = t["side"]
        pos_side = t["position_side"]
        if side == "buy" and pos_side == "long":
            net_qty[ticker] += qty
        elif side == "sell" and pos_side == "long":
            net_qty[ticker] -= qty
        elif side == "sell" and pos_side == "short":
            net_qty[ticker] += qty
        elif side == "buy" and pos_side == "short":
            net_qty[ticker] -= qty
        if side == "buy":
            buy_value[ticker] += qty * float(t["price_per_unit"])
            buy_qty[ticker] += qty

    out = []
    for ticker in sorted(net_qty):
        nq = net_qty[ticker]
        if nq == 0:
            continue
        avg = round(buy_value[ticker] / buy_qty[ticker], 2) if buy_qty[ticker] else None
        out.append({"ticker": ticker, "net_qty": nq, "side": "long" if nq > 0 else "short", "avg_cost": avg})
    return out


def get_user_alerts(user_id: str) -> list[dict[str, Any]]:
    """Active alerts with latest prices and proximity.

    Returns list of {ticker, alert_type, alert_price, direction, notes,
                     latest_price, pct_away}.
    """
    client, schema = _client()
    alert_res = client.schema(schema).table("user_portfolio_alerts") \
        .select("ticker,alert_type,price,direction,notes") \
        .eq("user_id", user_id) \
        .eq("is_active", True) \
        .order("ticker").order("alert_type") \
        .execute()
    alert_rows = alert_res.data or []
    if not alert_rows:
        return []

    alert_tickers = list({r["ticker"] for r in alert_rows})
    scan_res = client.schema(schema).table("user_scan_rows") \
        .select("symbol,row_data,scan_date,id") \
        .eq("user_id", user_id) \
        .in_("symbol", alert_tickers) \
        .order("scan_date", desc=True) \
        .order("id", desc=True) \
        .execute()

    # Simulate DISTINCT ON (symbol) — keep first (most recent) row per symbol
    price_map: dict[str, float] = {}
    for r in (scan_res.data or []):
        sym = r["symbol"]
        if sym in price_map:
            continue
        row_data = _as_json(r.get("row_data"), default={})
        close = row_data.get("close")
        if close is not None:
            try:
                price_map[sym] = float(close)
            except (TypeError, ValueError):
                pass

    out = []
    for r in alert_rows:
        ticker = r["ticker"]
        alert_price = float(r["price"])
        latest = price_map.get(ticker)
        pct_away = round((latest - alert_price) / alert_price * 100, 2) if latest and alert_price > 0 else None
        out.append({
            "ticker": ticker,
            "alert_type": r["alert_type"],
            "alert_price": alert_price,
            "direction": r["direction"],
            "notes": r["notes"],
            "latest_price": latest,
            "pct_away": pct_away,
        })
    return out


def get_user_screening_notes(user_id: str) -> list[str]:
    """Active screening tickers from the user's latest scan run.

    Returns a flat list of ticker symbols.
    """
    client, schema = _client()
    run_res = client.schema(schema).table("user_scan_runs") \
        .select("id") \
        .eq("user_id", user_id) \
        .or_("status.eq.active,status.is.null") \
        .order("scan_date", desc=True) \
        .order("id", desc=True) \
        .limit(1) \
        .execute()
    runs = run_res.data or []
    if not runs:
        return []

    run_id = runs[0]["id"]
    notes_res = client.schema(schema).table("user_scan_row_notes") \
        .select("ticker") \
        .eq("user_id", user_id) \
        .eq("run_id", run_id) \
        .eq("status", "active") \
        .execute()
    return sorted({
        r["ticker"].strip()
        for r in (notes_res.data or [])
        if r.get("ticker") and r["ticker"].strip()
    })


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
    from services.news.embeddings.semantic_retrieval import search_news_embeddings

    results = search_news_embeddings(
        query,
        lookback_hours=lookback_hours,
        tickers=tickers,
        limit=limit,
    )
    return results


def get_ticker_news(
    tickers: list[str],
    hours: int = 24,
    per_ticker_limit: int = 5,
) -> list[dict[str, Any]]:
    """Per-ticker articles with sentiment scores and relationship annotations.

    Uses the get_relationship_node_news RPC (alias resolution + direct mentions +
    relationship traceability) then enriches with TICKER_SENTIMENT and
    TICKER_RELATIONSHIPS from news_impact_heads.

    Returns list of {ticker, article_id, title, url, published_at,
                     sentiment_score, sentiment_reason, relationships}.
    """
    if not tickers:
        return []
    normalized = list(dict.fromkeys(t.upper().strip() for t in tickers if t and t.strip()))
    if not normalized:
        return []

    client, schema = _client()
    days_lookback = max(1, -(-hours // 24))  # ceil division

    # One RPC call per ticker — the RPC handles alias resolution internally
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
            article_rows.append((canonical, article_id, r.get("title") or "", r.get("url") or "", r.get("published_at")))

    if not article_rows:
        return []

    article_ids = list({r[1] for r in article_rows})

    heads_res = client.schema(schema).table("news_impact_heads") \
        .select("article_id,cluster,scores_json,reasoning_json") \
        .in_("article_id", article_ids) \
        .in_("cluster", ["TICKER_SENTIMENT", "TICKER_RELATIONSHIPS"]) \
        .execute()

    sentiment_by_article: dict[int, tuple[dict, dict]] = {}
    relationships_by_article: dict[int, list[dict]] = {}
    for r in (heads_res.data or []):
        aid = int(r["article_id"])
        cluster = r["cluster"]
        scores = _as_json(r["scores_json"], {})
        reasoning = _as_json(r["reasoning_json"], {})
        if cluster == "TICKER_SENTIMENT":
            sentiment_by_article[aid] = (scores, reasoning)
        elif cluster == "TICKER_RELATIONSHIPS":
            parsed = []
            for key, strength in scores.items():
                parts = str(key).split("__")
                if len(parts) == 3:
                    parsed.append({"from": parts[0], "to": parts[1], "type": parts[2],
                                    "strength": strength, "notes": reasoning.get(key, "")})
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


def get_user_trading_strategy(user_id: str) -> str:
    """Return the user's saved trading strategy text, or empty string if none."""
    client, schema = _client()
    res = client.schema(schema).table("user_trading_strategy") \
        .select("strategy") \
        .eq("user_id", user_id) \
        .maybe_single() \
        .execute()
    return (res.data or {}).get("strategy") or ""
