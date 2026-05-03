"""
Relationship graph retrieval and traversal.

  - get_ticker_relationships     — RPC-based neighborhood (1-2 hops)
  - get_company_vectors          — latest company factor vectors
  - fetch_relationship_edges     — bulk edge load from ticker_relationship_network_resolved_v
  - expand_related_tickers       — multi-hop BFS with decay (returns scored ticker map)
  - build_neighborhood_from_seed — bounded BFS (returns visited/edges/depth/parent)

Extracted from agent/data_queries and narrative/narrative_generator.
"""

from __future__ import annotations

import logging
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from shared.db import get_supabase_client

log = logging.getLogger(__name__)

_BLOCKED_NODE_LABELS = {"N/A"}


@dataclass
class RelationshipEdge:
    from_ticker: str
    to_ticker: str
    rel_type: str
    strength: float
    mention_count: int = 0


def _normalize_ticker(ticker: Any) -> str:
    return str(ticker or "").upper().strip()


def _client():
    return get_supabase_client(), "swingtrader"


def get_ticker_relationships(ticker: str, hops: int = 1) -> dict[str, Any]:
    """Graph neighborhood around a ticker via get_relationship_neighborhood RPC.

    Returns dict with 'nodes' and 'edges' lists.
    """
    client, schema = _client()
    res = client.schema(schema).rpc(
        "get_relationship_neighborhood",
        {"p_seed": ticker.upper(), "p_hops": hops},
    ).execute()
    return res.data or {}


def get_company_vectors(tickers: list[str]) -> list[dict[str, Any]]:
    """Latest company factor dimension vectors for the given tickers.

    Returns: [{ticker, vector_date, dimensions_json}].
    """
    if not tickers:
        return []
    from shared.db import _as_json
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


def fetch_relationship_edges(
    lookback_days: int,
    min_strength: float = 0.25,
    min_mentions: int = 1,
    limit: int = 2000,
) -> list[RelationshipEdge]:
    """Load canonicalised edges from ticker_relationship_network_resolved_v.

    Mirrors the same filters the UI's relationshipsGetNeighborhood() uses.
    Aggregates duplicate (from, to, rel_type) keys with mention-weighted strength.
    """
    client, schema = _client()
    since = (datetime.now(timezone.utc) - timedelta(days=max(1, lookback_days))).isoformat()
    res = (
        client.schema(schema)
        .table("ticker_relationship_network_resolved_v")
        .select("from_ticker, to_ticker, rel_type, strength_avg, mention_count")
        .gte("strength_avg", min_strength)
        .gte("mention_count", min_mentions)
        .gte("last_seen_at", since)
        .order("strength_avg", desc=True)
        .limit(limit)
        .execute()
    )

    merged: dict[tuple[str, str, str], RelationshipEdge] = {}
    for row in (res.data or []):
        from_ticker = _normalize_ticker(row.get("from_ticker"))
        to_ticker = _normalize_ticker(row.get("to_ticker"))
        rel_type = str(row.get("rel_type") or "").lower().strip()
        if (
            not from_ticker or not to_ticker or not rel_type
            or from_ticker == to_ticker
            or from_ticker in _BLOCKED_NODE_LABELS
            or to_ticker in _BLOCKED_NODE_LABELS
        ):
            continue
        try:
            strength = max(0.0, min(1.0, float(row.get("strength_avg") or 0)))
        except (TypeError, ValueError):
            continue
        try:
            mentions = max(0, int(row.get("mention_count") or 0))
        except (TypeError, ValueError):
            mentions = 0
        edge = RelationshipEdge(from_ticker, to_ticker, rel_type, strength, mentions)
        key = (from_ticker, to_ticker, rel_type)
        prev = merged.get(key)
        if prev is None:
            merged[key] = edge
            continue
        pw, nw = max(1, prev.mention_count), max(1, mentions)
        merged[key] = RelationshipEdge(
            from_ticker, to_ticker, rel_type,
            ((prev.strength * pw) + (strength * nw)) / (pw + nw),
            prev.mention_count + mentions,
        )
    return list(merged.values())


def expand_related_tickers(
    seed_tickers: list[str],
    edges: list[RelationshipEdge],
    hops: int = 2,
    decay: float = 0.7,
    min_score: float = 0.35,
    max_tickers: int = 8,
) -> tuple[dict[str, float], dict[str, list[str]]]:
    """Multi-hop BFS with per-hop decay. Returns (ticker→score, ticker→path-segments)."""
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
            nxt = edge.to_ticker
            if nxt in path_nodes:
                continue
            next_depth = depth + 1
            next_score = score * edge.strength * (decay if next_depth > 1 else 1.0)
            if next_score <= 0:
                continue
            next_path = path_nodes + [nxt]
            next_rels = rel_types + [edge.rel_type]
            if nxt not in seeds:
                update = (
                    nxt not in best_score
                    or next_score > best_score[nxt]
                    or (
                        abs(next_score - best_score[nxt]) < 1e-9
                        and len(next_path) < len(best_path.get(nxt, next_path))
                    )
                )
                if update:
                    best_score[nxt] = next_score
                    best_path[nxt] = next_path
                    path_rel_types[nxt] = next_rels
            queue.append((nxt, next_depth, next_score, next_path, next_rels))

    ranked = sorted(
        ((t, s) for t, s in best_score.items() if s >= min_score and t not in seeds),
        key=lambda x: x[1], reverse=True,
    )[:max_tickers]

    final_scores = {t: s for t, s in ranked}
    final_paths: dict[str, list[str]] = {}
    for t in final_scores:
        nodes = best_path.get(t, [t])
        rels = path_rel_types.get(t, [])
        segments = [
            f"{nodes[i]} -{rels[i] if i < len(rels) else 'related'}-> {nodes[i + 1]}"
            for i in range(len(nodes) - 1)
        ]
        final_paths[t] = segments or [t]
    return final_scores, final_paths


def build_neighborhood_from_seed(
    seed_ticker: str,
    all_edges: list[RelationshipEdge],
    hops: int = 2,
    limit_nodes: int = 140,
    limit_edges: int = 360,
) -> tuple[set[str], list[RelationshipEdge], dict[str, int], dict[str, str]]:
    """Bounded BFS that mirrors the UI neighborhood traversal (hops capped at 2)."""
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
            nxt = edge.to_ticker if edge.from_ticker == current else edge.from_ticker
            if nxt not in visited and len(visited) < limit_nodes:
                visited.add(nxt)
                depth_by[nxt] = current_depth + 1
                parent_by[nxt] = current
                queue.append(nxt)

    return visited, kept_edges, depth_by, parent_by
