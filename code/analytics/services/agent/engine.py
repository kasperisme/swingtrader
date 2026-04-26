"""
engine.py — LLM agent that interprets a screening prompt, queries data tools,
evaluates trigger conditions, and writes a summary.

All screenings use the same agent with access to both market-wide and
user-specific tools. The prompt drives the behaviour.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

import httpx

from shared.db import get_supabase_client
from shared.telegram import (
    get_user_chat_id,
    log_telegram_message,
    send_telegram_chunks,
)
from .data_queries import (
    get_cluster_trends,
    get_dimension_trends,
    get_ticker_sentiment,
    get_top_articles,
    get_ticker_relationships,
    get_company_vectors,
    get_user_positions,
    get_user_alerts,
    get_user_screening_notes,
    search_news,
    get_ticker_news,
)

log = logging.getLogger(__name__)

_AGENT_SYSTEM = """\
You are a stock screening agent. You have access to data tools that query a \
news impact database — both market-wide analytics and user-specific portfolio \
data. Your job is to:

1. Read the user's screening prompt carefully.
2. Call the appropriate data tools to gather the information needed.
3. Decide whether the screening conditions are MET (triggered) or NOT MET.
4. If triggered, write a concise 2-3 sentence summary in plain English that \
   a swing trader can act on. Include specific data points, ticker names, \
   and dimension scores. If not triggered, return summary as null.

## Available tools

### Market-wide tools
get_cluster_trends(hours: int = 14)
  Returns cluster-level sentiment scores. Each row has:
  cluster_id (e.g. MACRO_SENSITIVITY), bucket_day, cluster_avg,
  cluster_weighted_avg (-1 to +1), bucket_article_count.

get_dimension_trends(cluster: str | None = None, hours: int = 14)
  Returns dimension-level scores within clusters. Filter by cluster_id.
  Each row has: dimension_key, cluster_id, bucket_day, dim_avg,
  dim_weighted_avg, article_count.

get_ticker_sentiment(tickers: list[str] | None = None, hours: int = 24)
  Returns per-article per-ticker sentiment scores.
  Each row has: article_id, ticker, sentiment_score, title, url, published_at.

get_top_articles(tickers: list[str] | None = None, hours: int = 14, limit: int = 10)
  Returns top-scored articles with full impact vectors.
  Each row has: title, url, source, published_at, impact_json (dict of \
  dimension_key -> score), top_dimensions, magnitude.

get_ticker_relationships(ticker: str, hops: int = 1)
  Returns graph neighborhood around a ticker. Has 'nodes' and 'edges' lists.

get_company_vectors(tickers: list[str])
  Returns latest company factor profiles. Each row has: ticker, vector_date,
  dimensions_json (dict of dimension_key -> score).

search_news(query: str, lookback_hours: int = 24, tickers: list[str] | None = None, limit: int = 12)
  Semantic search over news articles using vector similarity. Good for \
  finding macro themes or topic-specific articles.

get_ticker_news(tickers: list[str], hours: int = 24, per_ticker_limit: int = 5)
  Per-ticker articles with sentiment scores and relationship annotations. \
  Returns {ticker, article_id, title, url, published_at, sentiment_score, \
  sentiment_reason, relationships}. Resolves ticker aliases automatically.

### User-specific tools (scoped to this user's portfolio)
get_user_positions()
  Returns the user's open positions: {ticker, net_qty, side, avg_cost}.

get_user_alerts()
  Returns active price alerts: {ticker, alert_type, alert_price, direction, \
  notes, latest_price, pct_away}.

get_user_screening_notes()
  Returns list of active screening ticker symbols from the user's latest scan.

## 9 clusters and their dimensions

MACRO_SENSITIVITY: interest_rate_sensitivity_duration,
  interest_rate_sensitivity_debt, dollar_sensitivity,
  inflation_sensitivity, credit_spread_sensitivity,
  commodity_input_exposure, energy_cost_intensity

SECTOR_ROTATION: sector_financials, sector_technology,
  sector_healthcare, sector_energy, sector_realestate,
  sector_consumer, sector_industrials, sector_utilities

BUSINESS_MODEL: revenue_predictability, revenue_cyclicality,
  pricing_power_structural, pricing_power_cyclical, capex_intensity

FINANCIAL_STRUCTURE: debt_burden, floating_rate_debt_ratio,
  debt_maturity_nearterm, financial_health, earnings_quality,
  accruals_ratio, buyback_capacity

GROWTH_PROFILE: revenue_growth_rate, eps_growth_rate,
  eps_acceleration, forward_growth_expectations,
  earnings_revision_trend

VALUATION_POSITIONING: valuation_multiple, factor_value,
  short_interest_ratio, short_squeeze_risk, price_momentum

GEOGRAPHY_TRADE: china_revenue_exposure, emerging_market_exposure,
  domestic_revenue_concentration, tariff_sensitivity

SUPPLY_CHAIN_EXPOSURE: upstream_concentration,
  geographic_supply_risk, inventory_intensity, input_specificity,
  supplier_bargaining_power, downstream_customer_concentration

MARKET_BEHAVIOUR: institutional_appeal,
  institutional_ownership_change, short_squeeze_potential,
  earnings_surprise_volatility

## Rules

- Be CONSERVATIVE: only trigger when the data clearly supports it.
- Scores range from -1 (strong bearish) to +1 (strong bullish).
- A score with |value| < 0.1 is essentially neutral.
- Call the minimum number of tools needed to evaluate the prompt.
- Never fabricate data — only use what the tools return.

## Output format

Respond with ONLY valid JSON (no markdown, no commentary):
{"triggered": true/false, "summary": "..." or null, "data_used": {...}}

data_used should contain the tool names and a brief summary of what was returned.
"""

# ── Config ──────────────────────────────────────────────────────────────────

_OLLAMA_URL_ENV = "OLLAMA_BASE_URL"
_OLLAMA_MODEL_ENV = "OLLAMA_TIKTOK_MODEL"

_TOOLS_MARKET = {
    "get_cluster_trends": get_cluster_trends,
    "get_dimension_trends": get_dimension_trends,
    "get_ticker_sentiment": get_ticker_sentiment,
    "get_top_articles": get_top_articles,
    "get_ticker_relationships": get_ticker_relationships,
    "get_company_vectors": get_company_vectors,
    "get_ticker_news": get_ticker_news,
    "search_news": search_news,
}

_TOOLS_USER = {
    "get_user_positions": get_user_positions,
    "get_user_alerts": get_user_alerts,
    "get_user_screening_notes": get_user_screening_notes,
}

_TOOL_SCHEMAS = [
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
            "description": "Get dimension-level sentiment scores within clusters.",
            "parameters": {
                "type": "object",
                "properties": {
                    "cluster": {"type": "string", "description": "Cluster ID to filter, e.g. MACRO_SENSITIVITY"},
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
                    "tickers": {"type": "array", "items": {"type": "string"}, "description": "Ticker symbols"},
                    "hours": {"type": "integer", "description": "Lookback hours", "default": 24},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_top_articles",
            "description": "Get top-scored articles with impact vectors.",
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
                    "ticker": {"type": "string", "description": "Seed ticker symbol"},
                    "hops": {"type": "integer", "description": "Graph traversal depth", "default": 1},
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
                    "tickers": {"type": "array", "items": {"type": "string"}, "description": "Ticker symbols"},
                },
                "required": ["tickers"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_user_positions",
            "description": "Get the user's current open positions (from their trade journal). Returns ticker, net_qty, side, avg_cost.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_user_alerts",
            "description": "Get the user's active price alerts (stop_loss, take_profit, price_alert) with latest prices and % away.",
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
            "description": "Semantic search over news articles using vector similarity. Good for finding macro themes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query text"},
                    "lookback_hours": {"type": "integer", "description": "Lookback hours", "default": 24},
                    "tickers": {"type": "array", "items": {"type": "string"}, "description": "Optional ticker filter"},
                    "limit": {"type": "integer", "description": "Max results", "default": 12},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_ticker_news",
            "description": "Per-ticker articles with sentiment scores and relationship annotations. Resolves ticker aliases. Use for portfolio/watchlist news analysis.",
            "parameters": {
                "type": "object",
                "properties": {
                    "tickers": {"type": "array", "items": {"type": "string"}, "description": "Ticker symbols to fetch news for"},
                    "hours": {"type": "integer", "description": "Lookback hours", "default": 24},
                    "per_ticker_limit": {"type": "integer", "description": "Max articles per ticker", "default": 5},
                },
                "required": ["tickers"],
            },
        },
    },
]

_MAX_TOOL_ROUNDS = 10


# ── Ollama chat ─────────────────────────────────────────────────────────────

def _ollama_chat(messages: list[dict], tools: list[dict] | None = None, num_predict: int = 1024) -> dict:
    base = os.environ.get(_OLLAMA_URL_ENV, "http://localhost:11434").rstrip("/")
    model = (
        os.environ.get(_OLLAMA_MODEL_ENV)
        or os.environ.get("OLLAMA_BLOG_MODEL")
        or "gemma4:e4b"
    )
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": False,
        "format": "json",
        "options": {"num_predict": num_predict},
    }
    if tools:
        payload["tools"] = tools

    r = httpx.post(f"{base}/api/chat", json=payload, timeout=180.0)
    if r.status_code != 200:
        raise RuntimeError(f"Ollama returned {r.status_code}: {r.text[:300]}")
    return r.json()["message"]


def _call_tool(name: str, args: dict, user_id: str | None = None) -> Any:
    fn = _TOOLS_MARKET.get(name)
    if fn:
        try:
            return fn(**args)
        except Exception as exc:
            return {"error": str(exc)}

    user_fn = _TOOLS_USER.get(name)
    if user_fn:
        if user_id is None:
            return {"error": f"Tool {name} requires an authenticated user"}
        try:
            return user_fn(user_id, **args)
        except Exception as exc:
            return {"error": str(exc)}

    return {"error": f"Unknown tool: {name}"}


# ── Agent loop ──────────────────────────────────────────────────────────────

def run_agent(prompt: str, user_id: str | None = None) -> dict:
    """Run the screening agent loop. Returns {triggered, summary, data_used}."""
    messages = [
        {"role": "system", "content": _AGENT_SYSTEM},
        {"role": "user", "content": prompt},
    ]

    data_used: dict[str, Any] = {}
    resp: dict = {}

    for _ in range(_MAX_TOOL_ROUNDS):
        resp = _ollama_chat(messages, tools=_TOOL_SCHEMAS)

        tool_calls = resp.get("tool_calls")
        if not tool_calls:
            break

        messages.append(resp)

        for tc in tool_calls:
            fn_name = tc["function"]["name"]
            fn_args = tc["function"].get("arguments", {})
            result = _call_tool(fn_name, fn_args, user_id=user_id)
            data_used[fn_name] = _summarise_tool_result(fn_name, result)
            messages.append({
                "role": "tool",
                "name": fn_name,
                "content": json.dumps(result, default=str)[:8000],
            })

    raw = (resp.get("content") or "").strip()
    raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        log.warning("Agent returned non-JSON: %s", raw[:300])
        parsed = {"triggered": False, "summary": None, "data_used": data_used}

    parsed.setdefault("data_used", data_used)
    return parsed


def _summarise_tool_result(name: str, result: Any) -> Any:
    if isinstance(result, list) and len(result) > 10:
        return f"{len(result)} rows (showing first 3): {json.dumps(result[:3], default=str)}"
    return result


# ── Telegram formatting ────────────────────────────────────────────────────

def _format_telegram_alert(name: str, summary: str) -> str:
    return f"<b>🔔 {name}</b>\n\n{summary}"


# ── Run + persist ───────────────────────────────────────────────────────────

def run_screening(screening: dict, dry_run: bool = False, is_test: bool = False) -> dict:
    """Run a single screening. Returns the result dict (not yet persisted)."""
    result = run_agent(screening["prompt"], user_id=screening.get("user_id"))
    result["screening_id"] = screening["id"]
    result["user_id"] = screening.get("user_id")
    result["name"] = screening.get("name", "Screening")
    result["dry_run"] = dry_run
    result["is_test"] = is_test
    return result


def persist_and_deliver(result: dict) -> None:
    """Persist screening result to DB and deliver via Telegram if triggered."""
    client = get_supabase_client()
    schema = "swingtrader"
    now = datetime.now(timezone.utc).isoformat()

    is_test = bool(result.get("is_test"))
    triggered = bool(result.get("triggered"))
    row = {
        "screening_id": result["screening_id"],
        "user_id": result["user_id"],
        "run_at": now,
        "triggered": triggered,
        "summary": result.get("summary"),
        "data_used": result.get("data_used", {}),
        "is_test": is_test,
        "delivered": False,
    }
    try:
        client.schema(schema).table("user_screening_results").insert(row).execute()
    except Exception as exc:
        log.error("Failed to persist screening result: %s", exc)
        return

    update_fields: dict[str, Any] = {
        "last_run_at": now,
        "last_triggered": triggered,
    }
    if is_test:
        update_fields["run_requested_at"] = None

    client.schema(schema).table("user_scheduled_screenings").update(
        update_fields,
    ).eq("id", result["screening_id"]).execute()

    if not triggered:
        return

    chat_id = get_user_chat_id(result["user_id"])
    if not chat_id:
        log.info("No Telegram chat_id for user %s — in-app only", result["user_id"])
        return

    html = _format_telegram_alert(result["name"], result["summary"] or "")
    success, msg_id, err = send_telegram_chunks(chat_id, html)

    log_telegram_message(
        user_id=result["user_id"],
        chat_id=chat_id,
        message_type="screening_alert",
        message_text=html,
        success=success,
        telegram_message_id=msg_id,
        error_text=err,
    )

    if success:
        client.schema(schema).table("user_screening_results").update(
            {"delivered": True},
        ).eq("screening_id", result["screening_id"]).eq("run_at", now).execute()
