"""
LLM tool registry for agent-style prompting.

Extracted from services/agent/engine.py. Exposes the canonical tool schemas
and tool registries so any LLM agent (screening agent, podcast script generator,
future chat interface) can mount the same tool set without redefining it.
"""

from __future__ import annotations

from typing import Any, Callable

from .articles import get_top_articles, get_ticker_news, get_news_by_tag
from .sentiment import get_cluster_trends, get_dimension_trends, get_ticker_sentiment
from .graph import get_ticker_relationships, get_company_vectors
from .embeddings import search_news
from .portfolio import (
    get_user_positions,
    get_user_alerts,
    get_user_screening_notes,
    get_user_screening_note_details,
    get_ticker_chat_history,
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
            "name": "get_user_screening_note_details",
            "description": (
                "Get full per-ticker notes from the user's latest scan run — "
                "workflow status (active/watchlist/pipeline), stage, highlighted "
                "flag, priority, tags, comment, and any planned entry point "
                "({price, direction, date, take_profit, stop_loss, bar_idx}) the "
                "user has saved on the chart. Use this when the prompt asks "
                "about entries, planned trades, watchlist context, or research "
                "stage on tracked tickers. ALWAYS pass `tickers` when you "
                "already know which symbols you care about — unfiltered "
                "responses are capped to the top ~25 rows and may miss the "
                "ticker you need."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "tickers": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Restrict the lookup to these tickers "
                            "(case-insensitive). Strongly preferred when the "
                            "tickers of interest are known."
                        ),
                    },
                    "statuses": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": ["active", "watchlist", "pipeline", "dismissed"],
                        },
                        "description": (
                            "Filter to these workflow statuses. Defaults to "
                            "[active, watchlist, pipeline] (excludes dismissed)."
                        ),
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_ticker_chat_history",
            "description": (
                "Recent chat history from the user's chart-workspace conversation "
                "for one ticker. Includes prior bulk-analysis answers — the "
                "bulk-analysis worker appends its user prompt and assistant reply "
                "to this same thread with source='bulk_analysis'. Use this to see "
                "what the user (or a prior agent run) already concluded about a "
                "ticker before re-deriving it."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string", "description": "Symbol, case-insensitive."},
                    "limit": {"type": "integer", "description": "Most-recent N messages", "default": 20},
                },
                "required": ["ticker"],
            },
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
            "name": "get_news_by_tag",
            "description": (
                "Latest articles carrying any of the given tags (ticker symbols "
                "or theme/event slugs), newest first — the same tag feed as the "
                "/articles?tag=X page. Case-insensitive; a tag like 'SPCX' matches "
                "both the ticker and theme forms. Use for a news briefing/digest "
                "scoped to specific tags rather than per-article sentiment."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "hours": {"type": "integer", "default": 720},
                    "limit": {"type": "integer", "default": 20},
                    "article_stream": {"type": "string"},
                },
                "required": ["tags"],
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
        "get_news_by_tag": get_news_by_tag,
        "search_news": search_news,
    }


def get_user_tools() -> dict[str, Callable]:
    """Return user-scoped tool registry (caller must inject user_id at dispatch time)."""
    return {
        "get_user_positions": get_user_positions,
        "get_user_alerts": get_user_alerts,
        "get_user_screening_notes": get_user_screening_notes,
        "get_user_screening_note_details": get_user_screening_note_details,
        "get_ticker_chat_history": get_ticker_chat_history,
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
