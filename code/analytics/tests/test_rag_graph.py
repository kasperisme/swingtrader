"""Pure-function tests for graph BFS algorithms.

Covers expand_related_tickers (multi-hop with decay) and
build_neighborhood_from_seed (bounded BFS).
"""

from services.rag.graph import (
    RelationshipEdge,
    build_neighborhood_from_seed,
    expand_related_tickers,
)


def E(a, b, rel="partner", strength=1.0, mentions=1):
    return RelationshipEdge(a, b, rel, strength, mentions)


# ── expand_related_tickers ─────────────────────────────────────────────────

def test_expand_empty_inputs():
    assert expand_related_tickers([], []) == ({}, {})
    assert expand_related_tickers(["AAPL"], []) == ({}, {})
    assert expand_related_tickers([], [E("AAPL", "MSFT")]) == ({}, {})


def test_expand_single_hop():
    edges = [E("AAPL", "MSFT", strength=0.9)]
    scores, paths = expand_related_tickers(["AAPL"], edges, hops=1, min_score=0.0, max_tickers=10)
    assert scores == {"MSFT": 0.9}
    assert paths == {"MSFT": ["AAPL -partner-> MSFT"]}


def test_expand_two_hops_applies_decay_after_first_hop():
    edges = [
        E("AAPL", "MSFT", strength=1.0),
        E("MSFT", "NVDA", rel="customer", strength=1.0),
    ]
    scores, _ = expand_related_tickers(
        ["AAPL"], edges, hops=2, decay=0.5, min_score=0.0, max_tickers=10
    )
    assert scores["MSFT"] == 1.0           # hop 1: no decay
    assert scores["NVDA"] == 0.5           # hop 2: 1.0 * 1.0 * 0.5


def test_expand_seed_tickers_are_excluded_from_results():
    edges = [E("AAPL", "MSFT"), E("MSFT", "AAPL")]
    scores, _ = expand_related_tickers(["AAPL"], edges, hops=2, min_score=0.0, max_tickers=10)
    assert "AAPL" not in scores


def test_expand_min_score_filters_weak_connections():
    edges = [
        E("AAPL", "MSFT", strength=0.9),
        E("AAPL", "WEAK", strength=0.1),
    ]
    scores, _ = expand_related_tickers(
        ["AAPL"], edges, hops=1, min_score=0.5, max_tickers=10
    )
    assert "MSFT" in scores
    assert "WEAK" not in scores


def test_expand_respects_max_tickers_and_orders_by_score():
    edges = [
        E("AAPL", "T1", strength=0.3),
        E("AAPL", "T2", strength=0.9),
        E("AAPL", "T3", strength=0.6),
    ]
    scores, _ = expand_related_tickers(
        ["AAPL"], edges, hops=1, min_score=0.0, max_tickers=2
    )
    assert set(scores) == {"T2", "T3"}     # top 2 by score


def test_expand_path_segments_use_relationship_types():
    edges = [
        E("AAPL", "MSFT", rel="supplier"),
        E("MSFT", "NVDA", rel="customer"),
    ]
    _, paths = expand_related_tickers(
        ["AAPL"], edges, hops=2, decay=1.0, min_score=0.0, max_tickers=10
    )
    assert paths["NVDA"] == ["AAPL -supplier-> MSFT", "MSFT -customer-> NVDA"]


def test_expand_does_not_revisit_a_ticker_already_in_path():
    """Cycles must not inflate scores; the visited check prevents re-entry."""
    edges = [E("A", "B"), E("B", "A"), E("B", "C")]
    scores, _ = expand_related_tickers(
        ["A"], edges, hops=3, decay=1.0, min_score=0.0, max_tickers=10
    )
    assert "A" not in scores
    assert "B" in scores and "C" in scores


# ── build_neighborhood_from_seed ───────────────────────────────────────────

def test_neighborhood_returns_seed_with_no_edges():
    visited, kept, depth_by, parent_by = build_neighborhood_from_seed("AAPL", [])
    assert visited == {"AAPL"}
    assert kept == []
    assert depth_by == {"AAPL": 0}
    assert parent_by == {}


def test_neighborhood_undirected_traversal():
    """Edges are traversed in both directions (UI parity)."""
    edges = [E("MSFT", "AAPL"), E("AAPL", "NVDA")]
    visited, _, depth_by, _ = build_neighborhood_from_seed("AAPL", edges, hops=1)
    assert visited == {"AAPL", "MSFT", "NVDA"}
    assert depth_by["MSFT"] == 1 and depth_by["NVDA"] == 1


def test_neighborhood_hops_capped_at_two():
    """Even when caller passes hops=5, the function clamps to 2."""
    edges = [E("A", "B"), E("B", "C"), E("C", "D"), E("D", "E")]
    visited, _, _, _ = build_neighborhood_from_seed("A", edges, hops=5)
    assert "C" in visited
    assert "D" not in visited
    assert "E" not in visited


def test_neighborhood_respects_node_limit():
    edges = [E("A", f"T{i}") for i in range(50)]
    visited, _, _, _ = build_neighborhood_from_seed("A", edges, hops=1, limit_nodes=5)
    assert len(visited) == 5


def test_neighborhood_respects_edge_limit():
    edges = [E("A", f"T{i}") for i in range(50)]
    _, kept, _, _ = build_neighborhood_from_seed("A", edges, hops=1, limit_edges=10)
    assert len(kept) == 10


def test_neighborhood_records_parent_relationships():
    edges = [E("A", "B"), E("B", "C")]
    _, _, _, parent_by = build_neighborhood_from_seed("A", edges, hops=2)
    assert parent_by["B"] == "A"
    assert parent_by["C"] == "B"
