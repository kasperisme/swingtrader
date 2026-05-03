"""
LLM tool registry for agent-style prompting.

Extracted from services/agent/engine.py. Exposes the canonical tool schemas
and tool registries so any LLM agent (screening agent, podcast script generator,
future chat interface) can mount the same tool set without redefining it.
"""

from __future__ import annotations

from typing import Any, Callable

from .articles import get_top_articles, get_ticker_news
from .sentiment import get_cluster_trends, get_dimension_trends, get_ticker_sentiment
from .graph import get_ticker_relationships, get_company_vectors
from .embeddings import search_news
from .portfolio import (
    get_user_positions,
    get_user_alerts,
    get_user_screening_notes,
)

# ── Tool schemas (Ollama-compatible function-calling format) ─────────────────

TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "get_cluster_trends",
            "description": "Get cluster-level sentiment scores from the news impact database.",
            "parameters": {
                "type": "object",
                "properties": {
                    "hours": {"type": "integer", "description": "Lookback hours", "default": 14},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_dimension_trends",
            "description": "Get dimension-level sentiment scores.",
            "parameters": {
                "type": "object",
                "properties": {
                    "hours": {"type": "integer", "description": "Lookback hours", "default": 14},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_ticker_sentiment",
            "description": "Get per-article per-ticker sentiment scores.",
            "parameters": {
                "type": "object",
                "properties": {
                    "tickers": {"type": "array", "items": {"type": "string"}},
                    "hours": {"type": "integer", "description": "Lookback hours", "default": 24},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_top_articles",
            "description": "Get top-scored articles with full impact vectors.",
            "parameters": {
                "type": "object",
                "properties": {
                    "tickers": {"type": "array", "items": {"type": "string"}, "description": "Filter to these tickers"},
                    "hours": {"type": "integer", "description": "Lookback hours", "default": 14},
                    "limit": {"type": "integer", "description": "Max articles", "default": 10},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_ticker_relationships",
            "description": "Get relationship graph neighborhood around a ticker.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string"},
                    "hops": {"type": "integer", "default": 1},
                },
                "required": ["ticker"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_company_vectors",
            "description": "Get latest company factor dimension profiles.",
            "parameters": {
                "type": "object",
                "properties": {
                    "tickers": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["tickers"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_user_positions",
            "description": "Get the user's current open positions (ticker, net_qty, side, avg_cost).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_user_alerts",
            "description": "Get the user's active price alerts with latest prices and % away.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_user_screening_notes",
            "description": "Get the user's active screening watchlist tickers from their latest scan.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_news",
            "description": "Semantic search over news articles using vector similarity.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "lookback_hours": {"type": "integer", "default": 24},
                    "tickers": {"type": "array", "items": {"type": "string"}},
                    "limit": {"type": "integer", "default": 12},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_ticker_news",
            "description": "Per-ticker articles with sentiment scores and relationship annotations. Resolves ticker aliases.",
            "parameters": {
                "type": "object",
                "properties": {
                    "tickers": {"type": "array", "items": {"type": "string"}},
                    "hours": {"type": "integer", "default": 24},
                    "per_ticker_limit": {"type": "integer", "default": 5},
                },
                "required": ["tickers"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_url",
            "description": "Fetch the full text content of a URL.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                },
                "required": ["url"],
            },
        },
    },
]


def get_market_tools() -> dict[str, Callable]:
    """Return the market-wide tool registry (no user context required)."""
    return {
        "get_cluster_trends": get_cluster_trends,
        "get_dimension_trends": get_dimension_trends,
        "get_ticker_sentiment": get_ticker_sentiment,
        "get_top_articles": get_top_articles,
        "get_ticker_relationships": get_ticker_relationships,
        "get_company_vectors": get_company_vectors,
        "get_ticker_news": get_ticker_news,
        "search_news": search_news,
    }


def get_user_tools() -> dict[str, Callable]:
    """Return user-scoped tool registry (caller must inject user_id at dispatch time)."""
    return {
        "get_user_positions": get_user_positions,
        "get_user_alerts": get_user_alerts,
        "get_user_screening_notes": get_user_screening_notes,
    }
