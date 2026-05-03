"""Integration tests: services.agent <-> services.rag wiring.

Verifies the agent engine correctly imports tool registries, tool schemas,
cluster taxonomy, and screening helpers from RAG instead of duplicating them.
"""

from unittest import mock

from services.agent import data_queries, engine
from services.rag import (
    CLUSTERS,
    TOOL_SCHEMAS as RAG_TOOL_SCHEMAS,
    get_market_tools,
    get_user_tools,
)


# ── tool registries ────────────────────────────────────────────────────────

def test_market_registry_matches_rag_plus_fetch_url():
    """Engine adds fetch_url on top of RAG's market tools."""
    assert set(engine._TOOLS_MARKET) == set(get_market_tools()) | {"fetch_url"}


def test_user_registry_matches_rag_exactly():
    assert engine._TOOLS_USER == get_user_tools()


def test_every_registered_tool_has_a_schema():
    schema_names = {s["function"]["name"] for s in engine._TOOL_SCHEMAS}
    for name in {**engine._TOOLS_MARKET, **engine._TOOLS_USER}:
        assert name in schema_names, f"Tool {name} has no schema"


def test_no_duplicate_schemas():
    """Engine schemas = RAG schemas; the duplicate fetch_url entry was removed."""
    names = [s["function"]["name"] for s in engine._TOOL_SCHEMAS]
    assert len(names) == len(set(names))


def test_engine_schemas_equal_rag_schemas():
    """fetch_url is already in RAG TOOL_SCHEMAS, so engine just re-uses them."""
    assert engine._TOOL_SCHEMAS is RAG_TOOL_SCHEMAS


# ── system prompt cluster taxonomy ─────────────────────────────────────────

def test_cluster_block_was_expanded_into_system_prompt():
    assert "{_CLUSTER_BLOCK_PLACEHOLDER}" not in engine._AGENT_SYSTEM


def test_every_cluster_id_appears_in_system_prompt():
    for c in CLUSTERS:
        assert c["id"] in engine._AGENT_SYSTEM, f"Cluster {c['id']} missing from prompt"


def test_every_dimension_key_appears_in_system_prompt():
    """The dynamic cluster block must list each dimension key under its cluster."""
    for c in CLUSTERS:
        for key, _label in c["dimensions"]:
            assert key in engine._AGENT_SYSTEM, f"Dimension {key} missing from prompt"


# ── _call_tool dispatch ────────────────────────────────────────────────────

def test_call_tool_routes_market_tools():
    sentinel = {"called": "market"}
    with mock.patch.dict(engine._TOOLS_MARKET, {"get_cluster_trends": lambda **kw: sentinel}):
        assert engine._call_tool("get_cluster_trends", {"hours": 14}) is sentinel


def test_call_tool_routes_user_tools_with_user_id():
    captured = {}

    def fake(user_id):
        captured["user_id"] = user_id
        return ["AAPL"]

    with mock.patch.dict(engine._TOOLS_USER, {"get_user_positions": fake}):
        out = engine._call_tool("get_user_positions", {}, user_id="u1")

    assert out == ["AAPL"]
    assert captured["user_id"] == "u1"


def test_call_tool_user_tool_without_user_id_returns_error():
    with mock.patch.dict(engine._TOOLS_USER, {"get_user_positions": lambda u: ["X"]}):
        out = engine._call_tool("get_user_positions", {}, user_id=None)
    assert "error" in out


def test_call_tool_unknown_tool_returns_error_when_fmp_disabled():
    with mock.patch.object(engine, "_FMP_ENABLED", False):
        out = engine._call_tool("nonexistent_tool", {})
    assert "Unknown tool" in out["error"]


def test_call_tool_market_exception_is_wrapped_in_error():
    def boom(**_):
        raise RuntimeError("boom")

    with mock.patch.dict(engine._TOOLS_MARKET, {"get_cluster_trends": boom}):
        out = engine._call_tool("get_cluster_trends", {})
    assert out == {"error": "boom"}


# ── data_queries.py re-export shim ─────────────────────────────────────────

def test_data_queries_reexports_match_rag_objects():
    """The shim must hand back the canonical RAG callables — not copies."""
    from services.rag import (
        get_top_articles, get_ticker_news,
        get_cluster_trends, get_dimension_trends, get_ticker_sentiment,
        get_user_positions, get_user_alerts, get_user_screening_notes,
        get_user_trading_strategy,
        get_ticker_relationships, get_company_vectors,
        search_news,
    )
    assert data_queries.get_top_articles is get_top_articles
    assert data_queries.get_ticker_news is get_ticker_news
    assert data_queries.get_cluster_trends is get_cluster_trends
    assert data_queries.get_dimension_trends is get_dimension_trends
    assert data_queries.get_ticker_sentiment is get_ticker_sentiment
    assert data_queries.get_user_positions is get_user_positions
    assert data_queries.get_user_alerts is get_user_alerts
    assert data_queries.get_user_screening_notes is get_user_screening_notes
    assert data_queries.get_user_trading_strategy is get_user_trading_strategy
    assert data_queries.get_ticker_relationships is get_ticker_relationships
    assert data_queries.get_company_vectors is get_company_vectors
    assert data_queries.search_news is search_news


# ── screening helpers extracted from engine into RAG ───────────────────────

def test_engine_screening_helpers_come_from_rag():
    from services.rag.screening import (
        apply_scan_filters,
        get_filtered_tickers_from_scan,
    )
    assert engine._apply_scan_filters is apply_scan_filters
    assert engine._get_filtered_tickers_from_scan is get_filtered_tickers_from_scan


def test_engine_context_helper_comes_from_rag():
    from services.rag.context import get_linked_scan_run_context
    assert engine._get_linked_scan_run_context is get_linked_scan_run_context
