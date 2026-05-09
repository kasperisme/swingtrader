"""
RAG — centralised retrieval-augmented generation support layer.

All services import data retrieval, context assembly, and tool schemas from here
rather than from each other's internals.
"""

from .articles import get_top_articles, get_ticker_news, fetch_tickers_for_articles
from .sentiment import (
    get_cluster_trends,
    get_dimension_trends,
    get_ticker_sentiment,
    compute_cluster_summary,
)
from .portfolio import (
    get_user_positions,
    get_user_alerts,
    get_user_screening_notes,
    get_user_trading_strategy,
)
from .graph import (
    get_ticker_relationships,
    get_company_vectors,
    RelationshipEdge,
    fetch_relationship_edges,
    expand_related_tickers,
    build_neighborhood_from_seed,
)
from .embeddings import search_news, embed_query
from .screening import apply_scan_filters, get_filtered_tickers_from_scan
from .screening_writes import (
    add_ticker_to_screening,
    set_screening_ticker_status,
    set_screening_ticker_note,
)
from .context import get_linked_scan_run_context
from .taxonomy import CLUSTERS, CLUSTER_ID_TO_LABEL, DIM_KEY_TO_LABEL
from .tools import (
    TOOL_SCHEMAS,
    get_market_tools,
    get_user_tools,
    get_screening_write_tools,
    SCREENING_WRITE_TOOL_SCHEMAS,
)

__all__ = [
    # articles
    "get_top_articles", "get_ticker_news", "fetch_tickers_for_articles",
    # sentiment
    "get_cluster_trends", "get_dimension_trends", "get_ticker_sentiment",
    "compute_cluster_summary",
    # portfolio
    "get_user_positions", "get_user_alerts", "get_user_screening_notes",
    "get_user_trading_strategy",
    # graph
    "get_ticker_relationships", "get_company_vectors",
    "RelationshipEdge", "fetch_relationship_edges",
    "expand_related_tickers", "build_neighborhood_from_seed",
    # embeddings
    "search_news", "embed_query",
    # screening
    "apply_scan_filters", "get_filtered_tickers_from_scan",
    "add_ticker_to_screening", "set_screening_ticker_status",
    "set_screening_ticker_note",
    # context assembly
    "get_linked_scan_run_context",
    # taxonomy
    "CLUSTERS", "CLUSTER_ID_TO_LABEL", "DIM_KEY_TO_LABEL",
    # tools
    "TOOL_SCHEMAS", "get_market_tools", "get_user_tools",
    "get_screening_write_tools", "SCREENING_WRITE_TOOL_SCHEMAS",
]


def __getattr__(name: str):
    """Lazy import for company scoring (pulls numpy/pandas)."""
    if name in ("CompanyScore", "score_companies"):
        from . import company
        return getattr(company, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
