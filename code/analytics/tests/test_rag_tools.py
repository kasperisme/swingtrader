"""Consistency invariants between TOOL_SCHEMAS and the tool registries."""

import pytest

from services.rag.tools import TOOL_SCHEMAS, get_market_tools, get_user_tools


def _schema_names():
    return {s["function"]["name"] for s in TOOL_SCHEMAS}


def test_schemas_are_well_formed():
    for s in TOOL_SCHEMAS:
        assert s["type"] == "function"
        fn = s["function"]
        assert isinstance(fn["name"], str) and fn["name"]
        assert isinstance(fn["description"], str) and fn["description"]
        assert fn["parameters"]["type"] == "object"
        assert "properties" in fn["parameters"]


def test_tool_schema_names_are_unique():
    names = [s["function"]["name"] for s in TOOL_SCHEMAS]
    assert len(names) == len(set(names))


def test_every_market_tool_has_a_schema():
    market = get_market_tools()
    schema_names = _schema_names()
    missing = set(market) - schema_names
    assert not missing, f"Market tools missing schemas: {missing}"


def test_every_user_tool_has_a_schema():
    user = get_user_tools()
    schema_names = _schema_names()
    missing = set(user) - schema_names
    assert not missing, f"User tools missing schemas: {missing}"


def test_market_and_user_tool_registries_do_not_overlap():
    """A given tool name must be either market-scoped or user-scoped, not both."""
    overlap = set(get_market_tools()) & set(get_user_tools())
    assert overlap == set()


def test_every_registered_tool_is_callable():
    for fn in {**get_market_tools(), **get_user_tools()}.values():
        assert callable(fn)


def test_required_market_tools_present():
    """Spot-check that the canonical market tools survive any future refactor."""
    market = get_market_tools()
    expected = {
        "get_cluster_trends",
        "get_dimension_trends",
        "get_ticker_sentiment",
        "get_top_articles",
        "get_ticker_relationships",
        "get_company_vectors",
        "get_ticker_news",
        "search_news",
    }
    assert expected.issubset(market.keys())


def test_required_user_tools_present():
    user = get_user_tools()
    expected = {"get_user_positions", "get_user_alerts", "get_user_screening_notes"}
    assert expected.issubset(user.keys())


@pytest.mark.parametrize("required_name", [
    "get_ticker_relationships",   # has required: ["ticker"]
    "get_company_vectors",        # has required: ["tickers"]
    "search_news",                # has required: ["query"]
    "get_ticker_news",            # has required: ["tickers"]
    "fetch_url",                  # has required: ["url"]
])
def test_required_params_documented_for_tools_that_need_them(required_name):
    schema = next(s for s in TOOL_SCHEMAS if s["function"]["name"] == required_name)
    required = schema["function"]["parameters"].get("required") or []
    assert len(required) >= 1
