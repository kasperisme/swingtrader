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
from .screening_writes import (
    add_ticker_to_screening,
    set_screening_ticker_status,
    set_screening_ticker_note,
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


# ── Screening write tools (mutations) ────────────────────────────────────────
#
# These let a scheduled agent push tickers and update workflow state on the
# screening it's *connected to*. They are NOT in TOOL_SCHEMAS by default —
# they only get exposed to an agent when the engine knows which run_ids the
# agent is allowed to write to (see ``build_screening_write_registry`` in
# services.agent_core.market_tools).

SCREENING_WRITE_TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "add_ticker_to_screening",
            "description": (
                "Add a ticker symbol to one of the screenings this agent is "
                "connected to. Idempotent: returns the existing row if the "
                "ticker is already there. Use this when the news / data "
                "shows a ticker the user should track in their list."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "run_id": {
                        "type": "integer",
                        "description": (
                            "ID of the screening run to add the ticker to. "
                            "Must be one of the IDs the agent is connected to."
                        ),
                    },
                    "ticker": {
                        "type": "string",
                        "description": "Symbol to add (case-insensitive).",
                    },
                },
                "required": ["run_id", "ticker"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_screening_ticker_status",
            "description": (
                "Update workflow state on a ticker that already exists in a "
                "connected screening. status is one of: active, dismissed, "
                "watchlist, pipeline. Pass `comment` to set/clear the note "
                "and `highlighted` to pin the row. Any field omitted is "
                "preserved from the previous note."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "run_id": {"type": "integer"},
                    "ticker": {"type": "string"},
                    "status": {
                        "type": "string",
                        "enum": ["active", "dismissed", "watchlist", "pipeline"],
                    },
                    "comment": {
                        "type": "string",
                        "description": "Note text (max 4000 chars). Empty string clears the note.",
                    },
                    "highlighted": {"type": "boolean"},
                },
                "required": ["run_id", "ticker"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_screening_ticker_note",
            "description": (
                "Set just the comment / note on a ticker in a connected "
                "screening. Convenience wrapper for set_screening_ticker_status "
                "when you only want to add a note."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "run_id": {"type": "integer"},
                    "ticker": {"type": "string"},
                    "comment": {"type": "string"},
                },
                "required": ["run_id", "ticker", "comment"],
            },
        },
    },
]


def get_screening_write_tools() -> dict[str, Callable]:
    """Return write-side screening tools.

    Each fn takes ``user_id`` as its first positional arg. The agent_core
    layer wraps these to also enforce the agent's allowed run_id whitelist.
    """
    return {
        "add_ticker_to_screening": add_ticker_to_screening,
        "set_screening_ticker_status": set_screening_ticker_status,
        "set_screening_ticker_note": set_screening_ticker_note,
    }
