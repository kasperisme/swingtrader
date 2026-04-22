"""
Daily Narrative Generator
=========================

Synthesises a personalised pre-market briefing for one or all opted-in users.

Data sources
------------
  user_trades              → compute net open positions per ticker
  scan_row_notes (active)  → active screening candidates
  news_article_tickers     → which tickers appear in recent articles
  news_impact_heads        → TICKER_SENTIMENT and TICKER_RELATIONSHIPS clusters
  news_articles            → title, url, published_at
  user_portfolio_alerts    → stop losses / take profits to watch
  scan_rows                → latest price data for alert proximity

Output
------
  Writes one row per (user_id, narrative_date) to daily_narratives.
  Each section item may include sources [{article_id, title, url, published_at}];
  market_pulse_sources lists articles backing the macro summary.
  Returns the structured dict that was saved.

Usage
-----
  python -m news_impact.narrative_generator --user-id <uuid>
  python -m news_impact.narrative_generator  # all opted-in users
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

from src.db import get_pg_connection, get_supabase_client, get_schema, _tbl
from news_impact.ollama_client import chat as ollama_chat, OllamaError
from news_impact.semantic_retrieval import search_news_embeddings

logger = logging.getLogger(__name__)

_EASTERN = ZoneInfo("America/New_York")
_DEFAULT_LOOKBACK_HOURS = 24
_DEFAULT_NETWORK_LOOKBACK_DAYS = max(1, int(os.environ.get("NARRATIVE_NETWORK_LOOKBACK_DAYS", "365")))
_OLLAMA_NARRATIVE_MODEL = os.environ.get("OLLAMA_NARRATIVE_MODEL") or os.environ.get("OLLAMA_IMPACT_MODEL", "devstral")
_OLLAMA_NARRATIVE_TOKENS = int(os.environ.get("OLLAMA_NARRATIVE_TOKENS", "3072"))
_OLLAMA_NARRATIVE_TIMEOUT = float(os.environ.get("OLLAMA_NARRATIVE_TIMEOUT", "180"))
_USE_SEMANTIC_RETRIEVAL = os.environ.get("USE_SEMANTIC_RETRIEVAL", "true").strip().lower() not in {"0", "false", "no", "off"}
_REL_GRAPH_HOPS = max(1, int(os.environ.get("NARRATIVE_REL_GRAPH_HOPS", "2")))
_REL_DECAY = max(0.0, min(1.0, float(os.environ.get("NARRATIVE_REL_DECAY", "0.7"))))
_REL_MIN_SCORE = max(0.0, min(1.0, float(os.environ.get("NARRATIVE_REL_MIN_SCORE", "0.35"))))
_REL_MAX_TICKERS = max(1, int(os.environ.get("NARRATIVE_REL_MAX_TICKERS", "8")))
_REL_ARTICLES_PER_TICKER = max(1, int(os.environ.get("NARRATIVE_REL_ARTICLES_PER_TICKER", "2")))
_REL_MIN_STRENGTH = max(0.0, min(1.0, float(os.environ.get("NARRATIVE_REL_MIN_STRENGTH", "0.25"))))
_REL_MIN_MENTIONS = max(1, int(os.environ.get("NARRATIVE_REL_MIN_MENTIONS", "1")))
_REL_LIMIT_NODES = max(20, int(os.environ.get("NARRATIVE_REL_LIMIT_NODES", "140")))
_REL_LIMIT_EDGES = max(50, int(os.environ.get("NARRATIVE_REL_LIMIT_EDGES", "360")))
_BLOCKED_NODE_LABELS = {"N/A"}


# ── Data containers ───────────────────────────────────────────────────────────

@dataclass
class TickerNewsItem:
    article_id: int
    title: str
    url: str
    published_at: Optional[datetime]
    sentiment_score: float       # from TICKER_SENTIMENT head, scoped to this ticker
    sentiment_reason: str
    relationships: list[dict]    # [{from, to, type, notes}] from TICKER_RELATIONSHIPS head


@dataclass
class OpenPosition:
    ticker: str
    net_qty: float               # positive = long, negative = short
    avg_cost: Optional[float]    # weighted average entry price


@dataclass
class AlertItem:
    ticker: str
    alert_type: str              # stop_loss | take_profit | price_alert
    alert_price: float
    direction: str               # above | below
    notes: Optional[str]
    latest_price: Optional[float] = None
    pct_away: Optional[float] = None  # + means price is above alert, - means below


@dataclass
class UserContext:
    user_id: str
    narrative_date: date
    open_positions: list[OpenPosition] = field(default_factory=list)
    active_screen_tickers: list[str] = field(default_factory=list)
    portfolio_news: dict[str, list[TickerNewsItem]] = field(default_factory=dict)
    screening_news: dict[str, list[TickerNewsItem]] = field(default_factory=dict)
    related_news: dict[str, list[TickerNewsItem]] = field(default_factory=dict)
    related_ticker_scores: dict[str, float] = field(default_factory=dict)
    related_ticker_paths: dict[str, list[str]] = field(default_factory=dict)
    related_seed_diagnostics: list[dict[str, Any]] = field(default_factory=list)
    alert_items: list[AlertItem] = field(default_factory=list)
    semantic_evidence: list[dict] = field(default_factory=list)
    lookback_hours: int = _DEFAULT_LOOKBACK_HOURS
    network_lookback_days: int = _DEFAULT_NETWORK_LOOKBACK_DAYS


# ── DB queries ────────────────────────────────────────────────────────────────

@dataclass
class RelationshipEdge:
    from_ticker: str
    to_ticker: str
    rel_type: str
    strength: float
    mention_count: int = 0


def _normalize_ticker(ticker: Any) -> str:
    return str(ticker or "").upper().strip()


def _fetch_relationship_edges(conn, lookback_days: int) -> list[RelationshipEdge]:
    """
    Load canonicalized graph edges from ticker_relationship_network_resolved_v.
    Mirrors UI relationshipsGetNeighborhood() data source + filters.
    """
    schema = get_schema()
    since = datetime.now(_EASTERN) - timedelta(days=max(1, lookback_days))
    sql = f"""
        SELECT
            from_ticker,
            to_ticker,
            rel_type,
            strength_avg,
            mention_count
        FROM {schema}.ticker_relationship_network_resolved_v
        WHERE strength_avg >= %s
          AND mention_count >= %s
          AND last_seen_at >= %s
        ORDER BY strength_avg DESC
        LIMIT 5000
    """
    cur = conn.cursor()
    cur.execute(sql, (_REL_MIN_STRENGTH, _REL_MIN_MENTIONS, since))
    rows = cur.fetchall() or []
    merged_by_key: dict[tuple[str, str, str], RelationshipEdge] = {}
    for from_raw, to_raw, rel_raw, strength_raw, mention_raw in rows:
        from_ticker = _normalize_ticker(from_raw)
        to_ticker = _normalize_ticker(to_raw)
        rel_type = str(rel_raw or "").lower().strip()
        if (
            not from_ticker
            or not to_ticker
            or not rel_type
            or from_ticker == to_ticker
            or from_ticker in _BLOCKED_NODE_LABELS
            or to_ticker in _BLOCKED_NODE_LABELS
        ):
            continue
        try:
            strength = max(0.0, min(1.0, float(strength_raw)))
        except (TypeError, ValueError):
            continue
        try:
            mention_count = max(0, int(mention_raw or 0))
        except (TypeError, ValueError):
            mention_count = 0
        edge = RelationshipEdge(
            from_ticker=from_ticker,
            to_ticker=to_ticker,
            rel_type=rel_type,
            strength=strength,
            mention_count=mention_count,
        )
        key = (from_ticker, to_ticker, rel_type)
        prev = merged_by_key.get(key)
        if prev is None:
            merged_by_key[key] = edge
            continue
        prev_weight = max(1, prev.mention_count)
        next_weight = max(1, edge.mention_count)
        merged_by_key[key] = RelationshipEdge(
            from_ticker=from_ticker,
            to_ticker=to_ticker,
            rel_type=rel_type,
            strength=((prev.strength * prev_weight) + (edge.strength * next_weight))
            / (prev_weight + next_weight),
            mention_count=prev.mention_count + edge.mention_count,
        )
    return list(merged_by_key.values())


def _resolve_canonical_tickers(conn, tickers: list[str]) -> list[str]:
    """Resolve ticker aliases to canonical tickers like the UI does."""
    normalized = list(dict.fromkeys(_normalize_ticker(t) for t in tickers if _normalize_ticker(t)))
    if not normalized:
        return []
    schema = get_schema()
    sql = f"""
        SELECT alias_value_norm, canonical_ticker
        FROM {schema}.security_identity_map
        WHERE alias_kind = 'ticker'
          AND alias_value_norm = ANY(%s)
        ORDER BY verified DESC, confidence DESC, id ASC
    """
    alias_norms = [t.lower() for t in normalized]
    cur = conn.cursor()
    cur.execute(sql, (alias_norms,))
    rows = cur.fetchall() or []
    best: dict[str, str] = {}
    for alias_norm, canonical in rows:
        if alias_norm not in best:
            best[str(alias_norm)] = _normalize_ticker(canonical)
    return [best.get(t.lower(), t) for t in normalized]


def _expand_related_tickers(
    seed_tickers: list[str],
    edges: list[RelationshipEdge],
    hops: int = _REL_GRAPH_HOPS,
    decay: float = _REL_DECAY,
    min_score: float = _REL_MIN_SCORE,
    max_tickers: int = _REL_MAX_TICKERS,
) -> tuple[dict[str, float], dict[str, list[str]]]:
    """
    Multi-hop traversal (up to K steps) with per-hop decay.
    Returns (ticker_score_map, ticker_paths_map).
    """
    if not seed_tickers or not edges:
        return {}, {}

    adjacency: dict[str, list[RelationshipEdge]] = defaultdict(list)
    for edge in edges:
        adjacency[edge.from_ticker].append(edge)

    seeds = {_normalize_ticker(t) for t in seed_tickers if _normalize_ticker(t)}
    best_score: dict[str, float] = {}
    best_path: dict[str, list[str]] = {}
    path_rel_types: dict[str, list[str]] = {}

    queue: deque[tuple[str, int, float, list[str], list[str]]] = deque()
    for seed in seeds:
        queue.append((seed, 0, 1.0, [seed], []))

    while queue:
        ticker, depth, score, path_nodes, rel_types = queue.popleft()
        if depth >= hops:
            continue
        for edge in adjacency.get(ticker, []):
            next_ticker = edge.to_ticker
            if next_ticker in path_nodes:
                continue
            next_depth = depth + 1
            next_score = score * edge.strength * (decay if next_depth > 1 else 1.0)
            if next_score <= 0:
                continue
            next_path = path_nodes + [next_ticker]
            next_rel_types = rel_types + [edge.rel_type]

            if next_ticker not in seeds:
                should_update = (
                    next_ticker not in best_score
                    or next_score > best_score[next_ticker]
                    or (
                        abs(next_score - best_score[next_ticker]) < 1e-9
                        and len(next_path) < len(best_path.get(next_ticker, next_path))
                    )
                )
                if should_update:
                    best_score[next_ticker] = next_score
                    best_path[next_ticker] = next_path
                    path_rel_types[next_ticker] = next_rel_types

            queue.append((next_ticker, next_depth, next_score, next_path, next_rel_types))

    ranked = sorted(
        (
            (ticker, score)
            for ticker, score in best_score.items()
            if score >= min_score and ticker not in seeds
        ),
        key=lambda x: x[1],
        reverse=True,
    )[:max_tickers]

    final_scores = {ticker: score for ticker, score in ranked}
    final_paths: dict[str, list[str]] = {}
    for ticker in final_scores:
        nodes = best_path.get(ticker, [ticker])
        rel_types = path_rel_types.get(ticker, [])
        segments: list[str] = []
        for idx, src in enumerate(nodes[:-1]):
            rel = rel_types[idx] if idx < len(rel_types) else "related"
            dst = nodes[idx + 1]
            segments.append(f"{src} -{rel}-> {dst}")
        final_paths[ticker] = segments or [ticker]
    return final_scores, final_paths


def _build_neighborhood_from_seed(
    seed_ticker: str,
    all_edges: list[RelationshipEdge],
    hops: int = _REL_GRAPH_HOPS,
    limit_nodes: int = _REL_LIMIT_NODES,
    limit_edges: int = _REL_LIMIT_EDGES,
) -> tuple[set[str], list[RelationshipEdge], dict[str, int], dict[str, str]]:
    """
    Match UI neighborhood traversal:
    - BFS from seed
    - hop cap (UI enforces <=2)
    - global caps for node and edge count
    """
    bounded_hops = max(1, min(2, int(hops)))
    visited: set[str] = {seed_ticker}
    depth_by: dict[str, int] = {seed_ticker: 0}
    parent_by: dict[str, str] = {}
    queue: deque[str] = deque([seed_ticker])
    kept_edges: list[RelationshipEdge] = []

    while queue and len(visited) < limit_nodes and len(kept_edges) < limit_edges:
        current = queue.popleft()
        current_depth = depth_by.get(current, 0)
        if current_depth >= bounded_hops:
            continue
        neighbors = [e for e in all_edges if e.from_ticker == current or e.to_ticker == current]
        for edge in neighbors:
            if len(kept_edges) >= limit_edges:
                break
            kept_edges.append(edge)
            next_ticker = edge.to_ticker if edge.from_ticker == current else edge.from_ticker
            if next_ticker not in visited and len(visited) < limit_nodes:
                visited.add(next_ticker)
                depth_by[next_ticker] = current_depth + 1
                parent_by[next_ticker] = current
                queue.append(next_ticker)

    return visited, kept_edges, depth_by, parent_by

def _fetch_open_positions(conn, user_id: str) -> list[OpenPosition]:
    """
    Compute net open position per ticker from user_trades.
    Net long  = SUM(buy×long qty) - SUM(sell×long qty)  > 0
    Net short = SUM(sell×short qty) - SUM(buy×short qty) > 0 (returned as negative)
    """
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
    cur = conn.cursor()
    cur.execute(sql, (user_id,))
    rows = cur.fetchall() or []
    return [
        OpenPosition(ticker=r[0], net_qty=float(r[1]), avg_cost=float(r[2]) if r[2] else None)
        for r in rows
    ]


def _fetch_active_screen_tickers(conn, user_id: str) -> list[str]:
    """
    Return active screening tickers from the user's latest screening run only.

    This avoids mixing stale active notes from older runs into today's narrative.
    """
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
    cur = conn.cursor()
    cur.execute(sql, (user_id, user_id))
    return [r[0] for r in (cur.fetchall() or [])]


def _fetch_ticker_aliases(conn, canonical_tickers: list[str]) -> dict[str, str]:
    """
    Return a map of {alias_norm → canonical_ticker} for all known aliases of the
    given canonical tickers, using the same security_identity_map table as
    _resolve_canonical_tickers (i.e. the same method the UI uses).
    The canonical tickers themselves are included so the query covers everything.
    """
    if not canonical_tickers:
        return {}
    schema = get_schema()
    sql = f"""
        SELECT alias_value_norm, canonical_ticker
        FROM {schema}.security_identity_map
        WHERE alias_kind = 'ticker'
          AND canonical_ticker = ANY(%s)
        ORDER BY verified DESC, confidence DESC, id ASC
    """
    cur = conn.cursor()
    cur.execute(sql, ([t.upper() for t in canonical_tickers],))
    rows = cur.fetchall() or []
    alias_to_canonical: dict[str, str] = {}
    for alias_norm, canonical in rows:
        norm = _normalize_ticker(str(alias_norm))
        canon = _normalize_ticker(str(canonical))
        if norm and canon and norm not in alias_to_canonical:
            alias_to_canonical[norm] = canon
    # Always include the canonical tickers themselves as identity mappings
    for t in canonical_tickers:
        alias_to_canonical.setdefault(t, t)
    return alias_to_canonical


def _fetch_ticker_news(
    conn,
    tickers: list[str],
    lookback_hours: int,
) -> dict[str, list[TickerNewsItem]]:
    """
    For each ticker, find recent articles and the TICKER_SENTIMENT score.
    Also pulls TICKER_RELATIONSHIPS data for relationship insights.
    Articles tagged under any known alias of a ticker are included and mapped
    back to the canonical ticker (same alias table the UI uses).
    Returns {ticker: [TickerNewsItem, ...]}
    """
    if not tickers:
        return {}
    normalized_tickers = list(dict.fromkeys(_normalize_ticker(t) for t in tickers if _normalize_ticker(t)))
    if not normalized_tickers:
        return {}

    # Build full alias → canonical map and the expanded query set
    alias_to_canonical = _fetch_ticker_aliases(conn, normalized_tickers)
    all_query_tickers = list(alias_to_canonical.keys())  # canonical + all aliases

    schema = get_schema()
    since = datetime.now(_EASTERN) - timedelta(hours=lookback_hours)

    # Fetch articles mentioning these tickers (or any of their aliases)
    sql_articles = f"""
        SELECT
            nat.ticker,
            na.id            AS article_id,
            na.title,
            na.url,
            na.published_at
        FROM {schema}.news_article_tickers nat
        JOIN {schema}.news_articles na ON na.id = nat.article_id
        WHERE nat.ticker = ANY(%s)
          AND COALESCE(na.published_at, na.created_at) >= %s
        ORDER BY nat.ticker, COALESCE(na.published_at, na.created_at) DESC
    """
    cur = conn.cursor()
    cur.execute(sql_articles, (all_query_tickers, since))
    article_rows = cur.fetchall() or []

    # Collect unique article IDs to fetch heads in one query
    article_ids = list({r[1] for r in article_rows})
    if not article_ids:
        return {}

    # Fetch TICKER_SENTIMENT heads
    sql_sentiment = f"""
        SELECT article_id, scores_json, reasoning_json
        FROM {schema}.news_impact_heads
        WHERE article_id = ANY(%s)
          AND cluster = 'TICKER_SENTIMENT'
    """
    cur.execute(sql_sentiment, (article_ids,))
    sentiment_by_article: dict[int, tuple[dict, dict]] = {}
    for row in (cur.fetchall() or []):
        sentiment_by_article[row[0]] = (row[1] or {}, row[2] or {})

    # Fetch TICKER_RELATIONSHIPS heads
    sql_rel = f"""
        SELECT article_id, scores_json, reasoning_json
        FROM {schema}.news_impact_heads
        WHERE article_id = ANY(%s)
          AND cluster = 'TICKER_RELATIONSHIPS'
    """
    cur.execute(sql_rel, (article_ids,))
    relationships_by_article: dict[int, list[dict]] = {}
    for row in (cur.fetchall() or []):
        rel_scores = row[1] or {}
        rel_reasoning = row[2] or {}
        parsed = []
        for key, strength in rel_scores.items():
            parts = key.split("__")
            if len(parts) == 3:
                parsed.append({
                    "from": parts[0],
                    "to": parts[1],
                    "type": parts[2],
                    "strength": strength,
                    "notes": rel_reasoning.get(key, ""),
                })
        relationships_by_article[row[0]] = parsed

    # Build output grouped by canonical ticker
    result: dict[str, list[TickerNewsItem]] = {t: [] for t in normalized_tickers}
    seen: set[tuple[str, int]] = set()

    for raw_ticker, article_id, title, url, published_at in article_rows:
        # Map alias back to the canonical ticker we were asked about
        norm = _normalize_ticker(raw_ticker)
        canonical = alias_to_canonical.get(norm, norm)
        if canonical not in result:
            continue

        key = (canonical, article_id)
        if key in seen:
            continue
        seen.add(key)

        scores, reasons = sentiment_by_article.get(article_id, ({}, {}))
        # Sentiment scores may be keyed by either the alias or the canonical ticker;
        # try canonical first, then the alias that matched.
        canonical_upper = canonical.upper()
        alias_upper = norm.upper()
        sentiment_score = float(
            scores.get(canonical_upper) or scores.get(alias_upper) or 0.0
        )
        sentiment_reason = reasons.get(canonical_upper) or reasons.get(alias_upper) or ""

        # Filter relationships to ones involving this ticker (canonical or alias)
        all_rels = relationships_by_article.get(article_id, [])
        relevant_rels = [
            r for r in all_rels
            if r["from"] in (canonical_upper, alias_upper)
            or r["to"] in (canonical_upper, alias_upper)
        ]

        result[canonical].append(TickerNewsItem(
            article_id=article_id,
            title=title or "",
            url=url or "",
            published_at=published_at,
            sentiment_score=sentiment_score,
            sentiment_reason=sentiment_reason,
            relationships=relevant_rels,
        ))

    return result


def _merge_news_maps(
    base: dict[str, list[TickerNewsItem]],
    incoming: dict[str, list[TickerNewsItem]],
) -> dict[str, list[TickerNewsItem]]:
    merged: dict[str, list[TickerNewsItem]] = {}
    all_tickers = set(base.keys()) | set(incoming.keys())
    for ticker in all_tickers:
        by_article: dict[int, TickerNewsItem] = {}
        for item in base.get(ticker, []):
            by_article[item.article_id] = item
        for item in incoming.get(ticker, []):
            by_article.setdefault(item.article_id, item)
        merged[ticker] = sorted(
            by_article.values(),
            key=lambda item: item.published_at or datetime.min,
            reverse=True,
        )
    return merged


def _fetch_related_news_from_relationship_edges(
    conn,
    candidate_tickers: list[str],
    network_nodes: set[str],
    lookback_hours: int,
) -> dict[str, list[TickerNewsItem]]:
    """
    Pull related news directly from TICKER_RELATIONSHIPS heads for the constructed network.
    This captures edge evidence even when news_article_tickers lacks certain entities (e.g. OPENAI).
    """
    normalized_candidates = list(
        dict.fromkeys(_normalize_ticker(t) for t in candidate_tickers if _normalize_ticker(t))
    )
    if not normalized_candidates or not network_nodes:
        return {}
    node_set = {_normalize_ticker(t) for t in network_nodes if _normalize_ticker(t)}
    if not node_set:
        return {}

    schema = get_schema()
    since = datetime.now(_EASTERN) - timedelta(hours=lookback_hours)
    cur = conn.cursor()

    sql_rel = f"""
        SELECT
            h.article_id,
            na.title,
            na.url,
            na.published_at,
            h.scores_json,
            h.reasoning_json
        FROM {schema}.news_impact_heads h
        JOIN {schema}.news_articles na ON na.id = h.article_id
        WHERE h.cluster = 'TICKER_RELATIONSHIPS'
          AND COALESCE(na.published_at, na.created_at) >= %s
        ORDER BY COALESCE(na.published_at, na.created_at) DESC
        LIMIT 5000
    """
    cur.execute(sql_rel, (since,))
    relationship_rows = cur.fetchall() or []

    article_ids = list({int(r[0]) for r in relationship_rows if r and r[0] is not None})
    sentiment_by_article: dict[int, tuple[dict, dict]] = {}
    if article_ids:
        sql_sentiment = f"""
            SELECT article_id, scores_json, reasoning_json
            FROM {schema}.news_impact_heads
            WHERE article_id = ANY(%s)
              AND cluster = 'TICKER_SENTIMENT'
        """
        cur.execute(sql_sentiment, (article_ids,))
        for article_id, scores_json, reasoning_json in (cur.fetchall() or []):
            sentiment_by_article[int(article_id)] = (scores_json or {}, reasoning_json or {})

    result: dict[str, list[TickerNewsItem]] = {t: [] for t in normalized_candidates}
    seen: set[tuple[str, int]] = set()
    candidate_set = set(normalized_candidates)

    for article_id_raw, title, url, published_at, scores_json, reasoning_json in relationship_rows:
        article_id = int(article_id_raw)
        rel_scores = scores_json or {}
        rel_reasons = reasoning_json or {}
        if not isinstance(rel_scores, dict):
            continue

        candidate_relationships: dict[str, list[dict[str, Any]]] = {t: [] for t in normalized_candidates}
        connected_candidates: set[str] = set()

        for key, strength in rel_scores.items():
            parts = str(key).split("__")
            if len(parts) != 3:
                continue
            from_ticker = _normalize_ticker(parts[0])
            to_ticker = _normalize_ticker(parts[1])
            rel_type = str(parts[2]).strip().lower() or "related"
            if (
                not from_ticker
                or not to_ticker
                or from_ticker == to_ticker
                or from_ticker not in node_set
                or to_ticker not in node_set
            ):
                continue
            rel_obj = {
                "from": from_ticker,
                "to": to_ticker,
                "type": rel_type,
                "strength": strength,
                "notes": rel_reasons.get(key, ""),
            }
            if from_ticker in candidate_set:
                candidate_relationships[from_ticker].append(rel_obj)
                connected_candidates.add(from_ticker)
            if to_ticker in candidate_set:
                candidate_relationships[to_ticker].append(rel_obj)
                connected_candidates.add(to_ticker)

        if not connected_candidates:
            continue

        sentiment_scores, sentiment_reasons = sentiment_by_article.get(article_id, ({}, {}))
        for ticker in connected_candidates:
            row_key = (ticker, article_id)
            if row_key in seen:
                continue
            seen.add(row_key)
            result[ticker].append(
                TickerNewsItem(
                    article_id=article_id,
                    title=title or "",
                    url=url or "",
                    published_at=published_at,
                    sentiment_score=float(sentiment_scores.get(ticker, 0.0)),
                    sentiment_reason=str(sentiment_reasons.get(ticker, "") or ""),
                    relationships=candidate_relationships.get(ticker, []),
                )
            )

    for ticker in list(result.keys()):
        result[ticker] = sorted(
            result[ticker],
            key=lambda item: item.published_at or datetime.min,
            reverse=True,
        )
    return result


def _fetch_alert_items(conn, user_id: str) -> list[AlertItem]:
    """Load active alerts and try to enrich with latest price from scan_rows."""
    schema = get_schema()

    sql_alerts = f"""
        SELECT ticker, alert_type, price, direction, notes
        FROM {schema}.user_portfolio_alerts
        WHERE user_id = %s AND is_active = TRUE
        ORDER BY ticker, alert_type
    """
    cur = conn.cursor()
    cur.execute(sql_alerts, (user_id,))
    alert_rows = cur.fetchall() or []
    if not alert_rows:
        return []

    alert_tickers = list({r[0] for r in alert_rows})

    # Try to get latest price from the most recent scan_rows row_data
    sql_price = f"""
        SELECT DISTINCT ON (sr.symbol)
            sr.symbol,
            (sr.row_data->>'close')::numeric AS close_price
        FROM {schema}.user_scan_rows sr
        WHERE sr.user_id = %s
          AND sr.symbol = ANY(%s)
          AND sr.row_data ? 'close'
        ORDER BY sr.symbol, sr.scan_date DESC, sr.id DESC
    """
    cur.execute(sql_price, (user_id, alert_tickers))
    price_map: dict[str, float] = {}
    for r in (cur.fetchall() or []):
        if r[1] is not None:
            price_map[r[0]] = float(r[1])

    items: list[AlertItem] = []
    for ticker, alert_type, alert_price, direction, notes in alert_rows:
        latest = price_map.get(ticker)
        pct_away: Optional[float] = None
        if latest and float(alert_price) > 0:
            pct_away = round((latest - float(alert_price)) / float(alert_price) * 100, 2)
        items.append(AlertItem(
            ticker=ticker,
            alert_type=alert_type,
            alert_price=float(alert_price),
            direction=direction,
            notes=notes,
            latest_price=latest,
            pct_away=pct_away,
        ))
    return items


def _fetch_opted_in_users(conn) -> list[tuple[str, int]]:
    """
    Return (user_id, lookback_hours) for all users where
    narrative_preferences.is_enabled = TRUE.
    Falls back to all users who have trades or active notes if no preferences exist.
    """
    schema = get_schema()
    sql = f"""
        SELECT user_id, lookback_hours
        FROM {schema}.user_narrative_preferences
        WHERE is_enabled = TRUE
    """
    cur = conn.cursor()
    try:
        cur.execute(sql)
        rows = cur.fetchall() or []
    except Exception:
        conn.rollback()
        rows = []

    if rows:
        return [(str(r[0]), int(r[1])) for r in rows]

    # Fallback: users with any trades
    sql2 = f"""
        SELECT DISTINCT user_id FROM {schema}.user_trades
    """
    cur.execute(sql2)
    return [(str(r[0]), _DEFAULT_LOOKBACK_HOURS) for r in (cur.fetchall() or [])]


# ── Ollama narrative synthesis ────────────────────────────────────────────────

_NARRATIVE_SYSTEM = """\
You are a concise pre-market briefing assistant for a swing trader.
Your job: synthesise recent news and its impact on specific portfolio positions \
and screening candidates. Be direct and actionable. Avoid waffle. No markdown.
Return ONLY valid JSON as specified — no preamble, no explanation outside the JSON."""

_NARRATIVE_USER_TEMPLATE = """\
Date: {date} (US Eastern premarket)

=== PORTFOLIO POSITIONS ===
{portfolio_block}

=== ACTIVE SCREENING CANDIDATES ===
{screening_block}

=== RECENT NEWS HITS (last {lookback_hours}h) ===
Each line starts with article_id=... — cite these integer ids in "sources" and market_pulse_sources only.
{news_block}

=== RELATED NETWORK NEWS (graph-expanded) ===
{related_news_block}

=== ACTIVE ALERTS ===
{alerts_block}

=== SEMANTIC EVIDENCE (retrieved chunks) ===
{semantic_block}

Generate a daily narrative JSON with this exact structure:
{{
  "portfolio_watch": [
    {{
      "ticker": "AAPL",
      "sentiment": 0.65,
      "narrative": "One or two sentences on what happened and why it matters for this position.",
      "action": "monitor",
      "sources": [{{"article_id": 12345}}]
    }}
  ],
  "screening_update": [
    {{
      "ticker": "MSFT",
      "narrative": "One sentence on news impact for this setup candidate.",
      "sources": [{{"article_id": 67890}}]
    }}
  ],
  "related_network_update": [
    {{
      "ticker": "LLY",
      "anchor_ticker": "NOVO.B",
      "narrative": "One sentence about why this related-company news matters for the anchor ticker.",
      "sources": [{{"article_id": 22222}}]
    }}
  ],
  "alert_watch": [
    {{
      "ticker": "TSLA",
      "alert_type": "stop_loss",
      "alert_price": 220.0,
      "pct_away": -3.2,
      "narrative": "Approaching stop. Negative sentiment from earnings miss narrative.",
      "sources": [{{"article_id": 111}}]
    }}
  ],
  "market_pulse": "Two or three sentences summarising the key macro themes from today's news that affect these positions.",
  "market_pulse_sources": [12345, 67890]
}}

Rules:
- Only include tickers that appear in the news hits above. Skip tickers with no news.
- sentiment: -1.0 (very negative) to +1.0 (very positive) for this specific ticker.
- action: one of "monitor" | "review" | "urgent" (urgent = needs attention today).
- alert_watch: only include alerts where pct_away is within 5% of the trigger level.
- market_pulse: required even if brief.
- related_network_update: use only tickers from the RELATED NETWORK NEWS block and include anchor_ticker when clear from the provided path.
- sources: for each portfolio_watch, screening_update, related_network_update, and alert_watch item, include "sources" as a JSON array of objects {{"article_id": <int>}} for every article you relied on. Use only article_id values that appear in the news hits block or related network block. Omit "sources" or use [] if none apply.
- market_pulse_sources: array of article_id integers drawn from the news hits that informed market_pulse; use [] if not article-specific.
- Return {{"portfolio_watch":[],"screening_update":[],"related_network_update":[],"alert_watch":[],"market_pulse":"No significant news in the lookback window.","market_pulse_sources":[]}} if nothing relevant found.
"""


def _build_portfolio_block(positions: list[OpenPosition]) -> str:
    if not positions:
        return "  (no open positions)"
    lines = []
    for p in positions:
        side = "LONG" if p.net_qty > 0 else "SHORT"
        cost = f"avg cost ${p.avg_cost:.2f}" if p.avg_cost else "cost unknown"
        lines.append(f"  {p.ticker} {side} {abs(p.net_qty):.0f} shares, {cost}")
    return "\n".join(lines)


def _build_screening_block(tickers: list[str]) -> str:
    if not tickers:
        return "  (no active screening candidates)"
    return "\n".join(f"  {t}" for t in tickers)


def _build_news_block(
    portfolio_news: dict[str, list[TickerNewsItem]],
    screening_news: dict[str, list[TickerNewsItem]],
) -> str:
    combined: dict[str, list[TickerNewsItem]] = {}
    for t, items in {**portfolio_news, **screening_news}.items():
        combined.setdefault(t, []).extend(items)

    if not any(v for v in combined.values()):
        return "  (no news hits in the lookback window)"

    lines: list[str] = []
    for ticker, items in sorted(combined.items()):
        if not items:
            continue
        lines.append(f"\n  [{ticker}]")
        for item in items[:3]:  # cap at 3 articles per ticker to control token budget
            ts = item.published_at.strftime("%H:%M") if item.published_at else "?"
            score_str = f"{item.sentiment_score:+.2f}" if item.sentiment_score else " 0.00"
            lines.append(
                f"    article_id={item.article_id} | {ts} sentiment={score_str} | {item.title[:100]}"
            )
            if item.sentiment_reason:
                lines.append(f"           reason: {item.sentiment_reason[:120]}")
            for rel in item.relationships[:2]:
                lines.append(
                    f"           related: {rel['from']}→{rel['to']} ({rel['type']}) {rel['notes'][:80]}"
                )
    return "\n".join(lines) if lines else "  (no news hits)"


def _build_related_news_block(
    related_news: dict[str, list[TickerNewsItem]],
    related_scores: dict[str, float],
    related_paths: dict[str, list[str]],
    per_ticker_limit: int = _REL_ARTICLES_PER_TICKER,
) -> str:
    if not related_news:
        return "  (no graph-related ticker news in the lookback window)"

    lines: list[str] = []
    for ticker, items in sorted(
        related_news.items(),
        key=lambda kv: related_scores.get(kv[0], 0.0),
        reverse=True,
    ):
        if not items:
            continue
        score = related_scores.get(ticker, 0.0)
        path_text = "; ".join(related_paths.get(ticker, []))[:180]
        lines.append(f"\n  [{ticker}] graph_score={score:.3f}")
        if path_text:
            lines.append(f"    path: {path_text}")
        for item in items[:per_ticker_limit]:
            ts = item.published_at.strftime("%H:%M") if item.published_at else "?"
            score_str = f"{item.sentiment_score:+.2f}" if item.sentiment_score else " 0.00"
            lines.append(
                f"    article_id={item.article_id} | {ts} sentiment={score_str} | {item.title[:100]}"
            )
            if item.sentiment_reason:
                lines.append(f"           reason: {item.sentiment_reason[:120]}")
    return "\n".join(lines) if lines else "  (no graph-related ticker news in the lookback window)"


def _build_alerts_block(alerts: list[AlertItem]) -> str:
    if not alerts:
        return "  (no active alerts)"
    lines: list[str] = []
    for a in alerts:
        price_str = f"current=${a.latest_price:.2f}" if a.latest_price else "price unknown"
        away_str = f"{a.pct_away:+.1f}%" if a.pct_away is not None else "?"
        lines.append(
            f"  {a.ticker} {a.alert_type.upper()} @ ${a.alert_price:.2f} | {price_str} | {away_str} away"
        )
    return "\n".join(lines)


def _build_semantic_block(items: list[dict]) -> str:
    if not items:
        return "  (no semantic evidence)"
    lines: list[str] = []
    for it in items[:12]:
        ts = (it.get("published_at") or "?")[:16].replace("T", " ")
        sim = it.get("similarity", 0.0)
        lines.append(
            f"  article_id={it.get('article_id')} | sim={sim:.3f} | {ts} | {it.get('title','')[:90]}"
        )
        if it.get("snippet"):
            lines.append(f"    snippet: {str(it.get('snippet'))[:220]}")
    return "\n".join(lines)


def _article_catalog_from_context(ctx: UserContext) -> dict[int, dict[str, Any]]:
    """Map article_id -> stable title/url for post-processing model citations."""
    cat: dict[int, dict[str, Any]] = {}
    for items in list(ctx.portfolio_news.values()) + list(ctx.screening_news.values()) + list(ctx.related_news.values()):
        for it in items:
            cat[it.article_id] = {
                "article_id": it.article_id,
                "title": it.title,
                "url": it.url,
                "published_at": it.published_at.isoformat() if it.published_at else None,
            }
    for it in ctx.semantic_evidence:
        aid = int(it.get("article_id") or 0)
        if aid <= 0:
            continue
        cat.setdefault(
            aid,
            {
                "article_id": aid,
                "title": it.get("title") or "",
                "url": it.get("url") or "",
                "published_at": it.get("published_at"),
            },
        )
    return cat


def _coerce_article_id(entry: Any) -> Optional[int]:
    if isinstance(entry, int):
        return entry
    if isinstance(entry, dict):
        v = entry.get("article_id")
        if v is None:
            return None
        try:
            return int(v)
        except (TypeError, ValueError):
            return None
    try:
        return int(entry)
    except (TypeError, ValueError):
        return None


def _enrich_narrative_sources(narrative: dict[str, Any], catalog: dict[int, dict[str, Any]]) -> None:
    """Replace model article_id citations with title/url from DB; drop unknown ids. Mutates narrative."""
    for section in ("portfolio_watch", "screening_update", "related_network_update", "alert_watch"):
        for item in narrative.get(section) or []:
            if not isinstance(item, dict):
                continue
            raw = item.get("sources")
            if not isinstance(raw, list):
                item.pop("sources", None)
                continue
            enriched: list[dict[str, Any]] = []
            for ent in raw:
                aid = _coerce_article_id(ent)
                if aid is not None and aid in catalog:
                    enriched.append(dict(catalog[aid]))
            if enriched:
                item["sources"] = enriched
            else:
                item.pop("sources", None)

    mp = narrative.get("market_pulse_sources")
    if not isinstance(mp, list):
        narrative["market_pulse_sources"] = []
        return
    enriched_mp: list[dict[str, Any]] = []
    for ent in mp:
        aid = _coerce_article_id(ent)
        if aid is not None and aid in catalog:
            enriched_mp.append(dict(catalog[aid]))
    narrative["market_pulse_sources"] = enriched_mp


def _enforce_section_ticker_integrity(narrative: dict[str, Any], ctx: UserContext) -> dict[str, Any]:
    """
    Prevent model leakage between sections:
    - portfolio_watch tickers must exist in actual open positions
    - screening_update tickers must come from active screening candidates
    - screening_update excludes portfolio tickers
    """
    portfolio_tickers = {p.ticker.upper() for p in ctx.open_positions}
    screening_tickers = {t.upper() for t in ctx.active_screen_tickers}
    related_tickers = {t.upper() for t in ctx.related_ticker_scores.keys()}

    portfolio_watch = narrative.get("portfolio_watch")
    if isinstance(portfolio_watch, list):
        filtered_portfolio: list[dict[str, Any]] = []
        for item in portfolio_watch:
            if not isinstance(item, dict):
                continue
            ticker = str(item.get("ticker") or "").upper().strip()
            if ticker and ticker in portfolio_tickers:
                filtered_portfolio.append(item)
        narrative["portfolio_watch"] = filtered_portfolio
    else:
        narrative["portfolio_watch"] = []

    screening_update = narrative.get("screening_update")
    if isinstance(screening_update, list):
        filtered_screening: list[dict[str, Any]] = []
        for item in screening_update:
            if not isinstance(item, dict):
                continue
            ticker = str(item.get("ticker") or "").upper().strip()
            if ticker and ticker in screening_tickers and ticker not in portfolio_tickers:
                filtered_screening.append(item)
        narrative["screening_update"] = filtered_screening
    else:
        narrative["screening_update"] = []

    related_update = narrative.get("related_network_update")
    if isinstance(related_update, list):
        filtered_related: list[dict[str, Any]] = []
        for item in related_update:
            if not isinstance(item, dict):
                continue
            ticker = str(item.get("ticker") or "").upper().strip()
            if not ticker or ticker not in related_tickers:
                continue
            if ticker in portfolio_tickers or ticker in screening_tickers:
                continue
            anchor = str(item.get("anchor_ticker") or "").upper().strip()
            if anchor and anchor not in portfolio_tickers and anchor not in screening_tickers:
                item.pop("anchor_ticker", None)
            filtered_related.append(item)
        narrative["related_network_update"] = filtered_related
    else:
        narrative["related_network_update"] = []

    return narrative


def _parse_narrative_json(raw: str) -> dict:
    """Best-effort JSON extraction from Ollama response."""
    import re
    # Strip markdown fences
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.MULTILINE).strip()
    # Find outermost { }
    start = raw.find("{")
    if start < 0:
        return {}
    depth, i, in_str, esc = 0, start, False, False
    while i < len(raw):
        c = raw[i]
        if in_str:
            esc = (not esc and c == "\\")
            if not esc and c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(raw[start: i + 1])
                except json.JSONDecodeError:
                    return {}
        i += 1
    return {}


async def _generate_narrative_text(ctx: UserContext) -> tuple[dict, int]:
    """
    Call Ollama with context; returns (parsed_narrative_dict, latency_ms).
    Falls back to an empty narrative structure on any error.
    """
    portfolio_block = _build_portfolio_block(ctx.open_positions)
    screening_block = _build_screening_block(ctx.active_screen_tickers)
    news_block = _build_news_block(ctx.portfolio_news, ctx.screening_news)
    related_news_block = _build_related_news_block(
        ctx.related_news,
        ctx.related_ticker_scores,
        ctx.related_ticker_paths,
    )
    alerts_block = _build_alerts_block(ctx.alert_items)
    semantic_block = _build_semantic_block(ctx.semantic_evidence)

    prompt = _NARRATIVE_USER_TEMPLATE.format(
        date=ctx.narrative_date.strftime("%A %B %-d, %Y"),
        portfolio_block=portfolio_block,
        screening_block=screening_block,
        news_block=news_block,
        related_news_block=related_news_block,
        alerts_block=alerts_block,
        semantic_block=semantic_block,
        lookback_hours=ctx.lookback_hours,
    )

    t0 = time.monotonic()
    try:
        raw, latency_ms = await ollama_chat(
            prompt=prompt,
            system=_NARRATIVE_SYSTEM,
            model=_OLLAMA_NARRATIVE_MODEL,
            timeout=_OLLAMA_NARRATIVE_TIMEOUT,
        )
    except OllamaError as exc:
        logger.error("[narrative] Ollama error for user %s: %s", ctx.user_id, exc)
        return _empty_narrative(), 0

    parsed = _parse_narrative_json(raw)
    if not parsed:
        logger.warning("[narrative] could not parse Ollama response for user %s: %r", ctx.user_id, raw[:200])
        return _empty_narrative(), latency_ms

    catalog = _article_catalog_from_context(ctx)
    _enrich_narrative_sources(parsed, catalog)
    parsed = _enforce_section_ticker_integrity(parsed, ctx)

    return parsed, latency_ms


def _empty_narrative() -> dict:
    return {
        "portfolio_watch": [],
        "screening_update": [],
        "related_network_update": [],
        "alert_watch": [],
        "market_pulse": "Could not generate narrative. Check Ollama connectivity.",
        "market_pulse_sources": [],
    }


# ── Persistence ───────────────────────────────────────────────────────────────

def _save_narrative(
    client,
    user_id: str,
    narrative_date: date,
    portfolio_section: list,
    screening_section: list,
    alert_warnings: list,
    market_pulse: str,
    market_pulse_sources: list,
    model: str,
    latency_ms: int,
) -> None:
    """Upsert the daily narrative for this user+date."""
    schema = get_schema()
    row = {
        "user_id": user_id,
        "narrative_date": narrative_date.isoformat(),
        "portfolio_section": portfolio_section,
        "screening_section": screening_section,
        "alert_warnings": alert_warnings,
        "market_pulse": market_pulse,
        "market_pulse_sources": market_pulse_sources,
        "model": model,
        "latency_ms": latency_ms,
        "generated_at": datetime.now().isoformat(),
    }
    client.schema(schema).table("daily_narratives").upsert(
        row, on_conflict="user_id,narrative_date"
    ).execute()


# ── Main entry point ──────────────────────────────────────────────────────────

def _build_user_context(
    user_id: str,
    narrative_date: date,
    lookback_hours: int,
    network_lookback_days: int = _DEFAULT_NETWORK_LOOKBACK_DAYS,
) -> UserContext:
    """
    Fetch all DB/embedding data for one user and return a populated UserContext.
    Does NOT call Ollama — safe to call for dry-run / inspection.
    """
    conn = get_pg_connection()
    try:
        ctx = UserContext(
            user_id=user_id,
            narrative_date=narrative_date,
            lookback_hours=lookback_hours,
            network_lookback_days=max(1, int(network_lookback_days)),
        )

        ctx.open_positions = _fetch_open_positions(conn, user_id)
        ctx.active_screen_tickers = _fetch_active_screen_tickers(conn, user_id)
        ctx.alert_items = _fetch_alert_items(conn, user_id)

        portfolio_tickers = _resolve_canonical_tickers(conn, [p.ticker for p in ctx.open_positions])
        all_tickers = list(dict.fromkeys(portfolio_tickers + ctx.active_screen_tickers))

        if all_tickers:
            news_map = _fetch_ticker_news(conn, all_tickers, lookback_hours)
            portfolio_set = {_normalize_ticker(t) for t in portfolio_tickers}
            ctx.portfolio_news = {t: v for t, v in news_map.items() if t in portfolio_set}
            ctx.screening_news = {t: v for t, v in news_map.items() if t not in portfolio_set}

            relationship_edges = _fetch_relationship_edges(
                conn,
                lookback_days=ctx.network_lookback_days,
            )
            related_scores: dict[str, float] = {}
            related_paths: dict[str, list[str]] = {}
            network_nodes_all: set[str] = set()

            # Portfolio-first neighborhood expansion: mirrors UI graph construction and focuses
            # related context on held names instead of broad screening-only expansion.
            seed_tickers = portfolio_tickers or all_tickers
            for seed in seed_tickers:
                seed_norm = _normalize_ticker(seed)
                if not seed_norm:
                    continue
                seed_candidate_scores: dict[str, float] = {}
                seed_candidate_paths: dict[str, str] = {}
                visited, kept_edges, depth_by, parent_by = _build_neighborhood_from_seed(
                    seed_norm,
                    relationship_edges,
                    hops=_REL_GRAPH_HOPS,
                    limit_nodes=_REL_LIMIT_NODES,
                    limit_edges=_REL_LIMIT_EDGES,
                )
                network_nodes_all.update(visited)
                incident: dict[str, list[RelationshipEdge]] = defaultdict(list)
                for edge in kept_edges:
                    incident[edge.from_ticker].append(edge)
                    incident[edge.to_ticker].append(edge)
                for ticker in visited:
                    if ticker == seed_norm:
                        continue
                    depth = depth_by.get(ticker, _REL_GRAPH_HOPS)
                    depth_penalty = 0.85 ** max(0, depth - 1)
                    score = max(
                        (e.strength * depth_penalty for e in incident.get(ticker, [])),
                        default=0.0,
                    )
                    if score < _REL_MIN_SCORE:
                        continue
                    path_nodes: list[str] = [ticker]
                    parent = parent_by.get(ticker)
                    while parent:
                        path_nodes.append(parent)
                        if parent == seed_norm:
                            break
                        parent = parent_by.get(parent)
                    path_nodes.reverse()
                    candidate_path = " -> ".join(path_nodes)
                    if score > seed_candidate_scores.get(ticker, 0.0):
                        seed_candidate_scores[ticker] = score
                        seed_candidate_paths[ticker] = candidate_path
                    if score > related_scores.get(ticker, 0.0):
                        related_scores[ticker] = score
                        related_paths[ticker] = [candidate_path]
                seed_ranked = sorted(
                    seed_candidate_scores.items(),
                    key=lambda x: x[1],
                    reverse=True,
                )[:5]
                ctx.related_seed_diagnostics.append(
                    {
                        "seed_ticker": seed_norm,
                        "visited_nodes": len(visited),
                        "traversed_edges": len(kept_edges),
                        "qualified_candidates": len(
                            [
                                ticker
                                for ticker in visited
                                if ticker != seed_norm and ticker in related_scores
                            ]
                        ),
                        "top_candidates": [
                            {
                                "ticker": ticker,
                                "score": score,
                                "path": seed_candidate_paths.get(ticker, ""),
                            }
                            for ticker, score in seed_ranked
                        ],
                    }
                )

            if related_scores:
                ranked = sorted(related_scores.items(), key=lambda x: x[1], reverse=True)[:_REL_MAX_TICKERS]
                related_scores = {t: s for t, s in ranked}
                related_paths = {t: related_paths.get(t, []) for t in related_scores}
            if related_scores:
                related_map_mentions = _fetch_ticker_news(conn, list(related_scores.keys()), lookback_hours)
                related_map_relationships = _fetch_related_news_from_relationship_edges(
                    conn,
                    candidate_tickers=list(related_scores.keys()),
                    network_nodes=network_nodes_all,
                    lookback_hours=lookback_hours,
                )
                related_map = _merge_news_maps(related_map_mentions, related_map_relationships)
                related_map = {t: items[:_REL_ARTICLES_PER_TICKER] for t, items in related_map.items() if items}
                ctx.related_news = related_map
                ctx.related_ticker_scores = {t: s for t, s in related_scores.items() if t in related_map}
                ctx.related_ticker_paths = {t: related_paths.get(t, []) for t in related_map}
                if ctx.related_ticker_scores:
                    top_related = sorted(ctx.related_ticker_scores.items(), key=lambda x: x[1], reverse=True)[:5]
                    logger.info("[narrative] user=%s related candidates=%s", user_id, top_related)

            if _USE_SEMANTIC_RETRIEVAL:
                retrieval_query = (
                    f"Portfolio: {', '.join(portfolio_tickers) or 'none'}. "
                    f"Screening: {', '.join(ctx.active_screen_tickers) or 'none'}. "
                    f"Alerts: {', '.join(a.ticker for a in ctx.alert_items) or 'none'}. "
                    "Find the most relevant recent news snippets for a pre-market swing-trading brief."
                )
                ctx.semantic_evidence = search_news_embeddings(
                    retrieval_query,
                    lookback_hours=lookback_hours,
                    tickers=all_tickers,
                    limit=14,
                )
        else:
            logger.info("[narrative] user=%s has no positions or active screens", user_id)
    finally:
        conn.close()

    return ctx


def build_prompt_for_user(
    user_id: str,
    narrative_date: Optional[date] = None,
    lookback_hours: int = _DEFAULT_LOOKBACK_HOURS,
    network_lookback_days: int = _DEFAULT_NETWORK_LOOKBACK_DAYS,
) -> tuple["UserContext", str]:
    """
    Build and return the full Ollama prompt for one user without calling the model.
    Useful for dry-run inspection and input validation.

    Returns (ctx, prompt_string).
    """
    if narrative_date is None:
        narrative_date = datetime.now(_EASTERN).date()
    ctx = _build_user_context(
        user_id,
        narrative_date,
        lookback_hours,
        network_lookback_days=network_lookback_days,
    )
    portfolio_block = _build_portfolio_block(ctx.open_positions)
    screening_block = _build_screening_block(ctx.active_screen_tickers)
    news_block = _build_news_block(ctx.portfolio_news, ctx.screening_news)
    related_news_block = _build_related_news_block(
        ctx.related_news,
        ctx.related_ticker_scores,
        ctx.related_ticker_paths,
    )
    alerts_block = _build_alerts_block(ctx.alert_items)
    semantic_block = _build_semantic_block(ctx.semantic_evidence)
    prompt = _NARRATIVE_USER_TEMPLATE.format(
        date=ctx.narrative_date.strftime("%A %B %-d, %Y"),
        portfolio_block=portfolio_block,
        screening_block=screening_block,
        news_block=news_block,
        related_news_block=related_news_block,
        alerts_block=alerts_block,
        semantic_block=semantic_block,
        lookback_hours=ctx.lookback_hours,
    )
    return ctx, prompt


async def generate_for_user(
    user_id: str,
    narrative_date: Optional[date] = None,
    lookback_hours: int = _DEFAULT_LOOKBACK_HOURS,
    network_lookback_days: int = _DEFAULT_NETWORK_LOOKBACK_DAYS,
) -> dict:
    """
    Generate and persist the daily narrative for one user.
    Returns the saved narrative dict.
    """
    if narrative_date is None:
        narrative_date = datetime.now(_EASTERN).date()

    logger.info(
        "[narrative] generating for user=%s date=%s lookback=%dh network_lookback=%dd",
        user_id,
        narrative_date,
        lookback_hours,
        network_lookback_days,
    )
    ctx = _build_user_context(
        user_id,
        narrative_date,
        lookback_hours,
        network_lookback_days=network_lookback_days,
    )

    narrative, latency_ms = await _generate_narrative_text(ctx)
    related_section = narrative.get("related_network_update", [])
    screening_section = narrative.get("screening_update", [])
    if isinstance(related_section, list) and related_section:
        merged_screening: list[dict[str, Any]] = []
        if isinstance(screening_section, list):
            for row in screening_section:
                if isinstance(row, dict):
                    merged_screening.append({"kind": "screening", **row})
        for row in related_section:
            if isinstance(row, dict):
                merged_screening.append({"kind": "related", **row})
        screening_section = merged_screening

    client = get_supabase_client()
    _save_narrative(
        client=client,
        user_id=user_id,
        narrative_date=narrative_date,
        portfolio_section=narrative.get("portfolio_watch", []),
        screening_section=screening_section if isinstance(screening_section, list) else [],
        alert_warnings=narrative.get("alert_watch", []),
        market_pulse=narrative.get("market_pulse", ""),
        market_pulse_sources=narrative.get("market_pulse_sources") or [],
        model=_OLLAMA_NARRATIVE_MODEL,
        latency_ms=latency_ms,
    )
    logger.info("[narrative] saved for user=%s date=%s latency=%dms", user_id, narrative_date, latency_ms)
    return narrative


async def generate_all(
    network_lookback_days: int = _DEFAULT_NETWORK_LOOKBACK_DAYS,
) -> tuple[list[str], list[str]]:
    """
    Generate narratives for all opted-in users (sequentially — Ollama is single-GPU).
    Returns (processed_user_ids, failed_user_ids).
    """
    conn = get_pg_connection()
    try:
        users = _fetch_opted_in_users(conn)
    finally:
        conn.close()

    if not users:
        logger.info("[narrative] no opted-in users found")
        return [], []

    processed: list[str] = []
    failed: list[str] = []
    for user_id, lookback_hours in users:
        try:
            await generate_for_user(
                user_id,
                lookback_hours=lookback_hours,
                network_lookback_days=network_lookback_days,
            )
            processed.append(user_id)
        except Exception as exc:
            logger.error("[narrative] failed for user=%s: %s", user_id, exc)
            failed.append(user_id)
    return processed, failed


if __name__ == "__main__":
    import argparse
    import pathlib
    from dotenv import load_dotenv

    load_dotenv(pathlib.Path(__file__).parent.parent / ".env")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Generate daily narrative")
    parser.add_argument("--user-id", help="Generate for a specific user UUID only")
    parser.add_argument("--lookback-hours", type=int, default=_DEFAULT_LOOKBACK_HOURS)
    parser.add_argument("--network-lookback-days", type=int, default=_DEFAULT_NETWORK_LOOKBACK_DAYS)
    args = parser.parse_args()

    if args.user_id:
        result = asyncio.run(
            generate_for_user(
                args.user_id,
                lookback_hours=args.lookback_hours,
                network_lookback_days=args.network_lookback_days,
            )
        )
        print(json.dumps(result, indent=2))
    else:
        processed = asyncio.run(generate_all(network_lookback_days=args.network_lookback_days))
        print(f"Generated narratives for {len(processed)} users: {processed}")
