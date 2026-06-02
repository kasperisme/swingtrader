"""Integration tests: services.agent <-> services.rag wiring.

Verifies the screening engine builds its tool registry correctly by composing
the shared agent_core base with RAG market + user tools. Asserts against the
post-agent_core architecture: the engine no longer holds module-level tool
dicts; it builds a fresh ``ToolRegistry`` per ``run_agent`` call via
``engine._build_registry(user_id)``.
"""

import asyncio
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
    """No user_id → registry holds RAG market tools + fetch_url.

    When FMP is enabled (FMP_API_KEY set) the registry also carries the FMP MCP
    tools, so assert the RAG floor is present rather than exact equality.
    """
    reg = engine._build_registry(user_id=None)
    expected = set(get_market_tools()) | {"fetch_url"}
    assert expected <= set(reg.names())
    if not engine._FMP_ENABLED:
        assert set(reg.names()) == expected


def test_user_registry_layers_user_tools_on_top_of_market():
    """With a user_id, the registry adds RAG's user-scoped tools."""
    market_only = set(engine._build_registry(user_id=None).names())
    with_user = set(engine._build_registry(user_id="u1").names())
    assert with_user - market_only == set(get_user_tools())


def test_every_registered_tool_has_a_schema():
    """Every callable in the registry exposes a function-call schema."""
    reg = engine._build_registry(user_id="u1")
    schema_names = {s["function"]["name"] for s in reg.schemas()}
    assert schema_names == set(reg.names())


def test_no_duplicate_schemas():
    reg = engine._build_registry(user_id="u1")
    names = [s["function"]["name"] for s in reg.schemas()]
    assert len(names) == len(set(names))


def test_engine_schemas_are_canonical_rag_objects():
    """Registry holds RAG's schema dicts by identity — not copies.

    Only RAG tools are canonical objects; FMP MCP schemas (present when FMP is
    enabled) are built dynamically, so they're skipped here.
    """
    reg = engine._build_registry(user_id="u1")
    rag_by_name = {s["function"]["name"]: s for s in RAG_TOOL_SCHEMAS}
    for s in reg.schemas():
        name = s["function"]["name"]
        if name not in rag_by_name:
            continue  # FMP MCP tool — not a RAG canonical object
        assert s is rag_by_name[name], (
            f"Schema for {name} is a copy — it should be the RAG canonical object"
        )


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


# ── ToolRegistry.call dispatch ─────────────────────────────────────────────


def test_registry_routes_market_tools():
    """A market tool is dispatched by name through registry.call."""
    sentinel = {"called": "market"}
    reg = engine._build_registry(user_id=None)
    # add_function overwrites the existing entry for the same name.
    reg.add_function("get_cluster_trends", lambda **_: sentinel, description="stub")
    out = asyncio.run(reg.call("get_cluster_trends", {"hours": 14}))
    assert out is sentinel


def test_registry_binds_user_id_to_user_tools():
    """build_user_registry pre-binds user_id as the first positional arg."""
    captured: dict = {}

    def fake(user_id, **_kwargs):
        captured["user_id"] = user_id
        return ["AAPL"]

    with mock.patch(
        "services.agent_core.market_tools.get_user_tools",
        return_value={"get_user_positions": fake},
    ):
        reg = engine._build_registry(user_id="u1")
        out = asyncio.run(reg.call("get_user_positions", {}))

    assert out == ["AAPL"]
    assert captured["user_id"] == "u1"


def test_registry_excludes_user_tools_when_no_user_id():
    """Without a user_id, user-scoped tools are absent — call returns Unknown tool."""
    reg = engine._build_registry(user_id=None)
    assert "get_user_positions" not in reg.names()
    out = asyncio.run(reg.call("get_user_positions", {}))
    assert "Unknown tool" in out["error"]


def test_registry_unknown_tool_returns_error_when_fmp_disabled():
    with mock.patch.object(engine, "_FMP_ENABLED", False):
        reg = engine._build_registry(user_id=None)
    out = asyncio.run(reg.call("nonexistent_tool", {}))
    assert "Unknown tool" in out["error"]


def test_registry_wraps_tool_exceptions_in_error_dict():
    """A tool that raises is converted to {'error': ...} so it can't crash the loop."""
    def boom(**_):
        raise RuntimeError("boom")

    reg = engine._build_registry(user_id=None)
    reg.add_function("get_cluster_trends", boom, description="stub")
    out = asyncio.run(reg.call("get_cluster_trends", {}))
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
