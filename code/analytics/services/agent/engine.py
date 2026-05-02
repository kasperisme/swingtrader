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
from datetime import datetime, timezone, time
from typing import Any

import httpx

from shared.db import get_supabase_client
from .fmp_tools import get_fmp_tool_schemas, call_fmp_tool, _FMP_SYSTEM_ADDON
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
    get_user_trading_strategy,
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

get_dimension_trends(hours: int = 14)
  Returns dimension-level sentiment scores.
  Each row has: dimension_key, bucket_day, dimension_avg,
  dimension_weighted_avg, article_count, bucket_article_count.

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

fetch_url(url: str)
  Fetch the full text content of a URL. Use to read article body when the \
  title/snippet is not enough to evaluate a screening condition. \
  Returns {url, status, content (up to 8000 chars)}.

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
- If the prompt is a request for a rundown, summary, or overview (e.g. contains \
  "rundown", "summary", "overview", "show me", "give me", "what's happening"), \
  always set triggered=true and provide a comprehensive summary of what was found, \
  even if individual signals are weak. These are informational queries, not conditional alerts.

## Output format

Respond with ONLY valid JSON (no markdown, no commentary):
{"triggered": true/false, "summary": "..." or null, "data_used": {...}}

data_used should contain the tool names and a brief summary of what was returned.
"""

# ── Config ──────────────────────────────────────────────────────────────────

_OLLAMA_URL_ENV = "OLLAMA_BASE_URL"
_OLLAMA_MODEL_ENV = "OLLAMA_TIKTOK_MODEL"

def fetch_url(url: str) -> dict[str, Any]:
    """Fetch a URL and return its text content (truncated to 8000 chars)."""
    try:
        r = httpx.get(url, timeout=15.0, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"})
        text = r.text[:8000]
        return {"url": url, "status": r.status_code, "content": text}
    except Exception as exc:
        return {"error": str(exc)}


_TOOLS_MARKET = {
    "get_cluster_trends": get_cluster_trends,
    "get_dimension_trends": get_dimension_trends,
    "get_ticker_sentiment": get_ticker_sentiment,
    "get_top_articles": get_top_articles,
    "get_ticker_relationships": get_ticker_relationships,
    "get_company_vectors": get_company_vectors,
    "get_ticker_news": get_ticker_news,
    "search_news": search_news,
    "fetch_url": fetch_url,
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
    {
        "type": "function",
        "function": {
            "name": "fetch_url",
            "description": "Fetch the full text content of a URL. Use to read an article when title/snippet is insufficient.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL to fetch"},
                },
                "required": ["url"],
            },
        },
    },
]

_FMP_ENABLED = bool(os.environ.get("FMP_API_KEY"))

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

    r = httpx.post(f"{base}/api/chat", json=payload, timeout=300.0)
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

    if _FMP_ENABLED:
        return call_fmp_tool(name, args)

    return {"error": f"Unknown tool: {name}"}


# ── Scan filter helpers ───────────────────────────────────────────────────────

def _stringify_value(v: Any) -> str:
    """Mirror stringifyRowDataValueForFilter from screenings-row-data.ts."""
    if v is None:
        return ""
    if isinstance(v, str):
        return v.strip()
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    try:
        return json.dumps(v)
    except Exception:
        return str(v)


def _apply_scan_filters(rows: list[dict], filters: dict) -> list[str]:
    """Apply ScreeningsFilters (row-data + workflow note portions) to a list of
    scan rows. Returns the ordered, deduplicated list of matching ticker symbols.

    Workflow-note keys (__note_*) are merged in by _get_filtered_tickers_from_scan
    before this function runs.
    """
    symbol_contains = (filters.get("symbolContains") or "").strip().lower()
    bool_require: dict[str, bool] = filters.get("boolRequire") or {}
    bool_reject: dict[str, bool] = filters.get("boolReject") or {}
    num_min: dict[str, str] = filters.get("numMin") or {}
    num_max: dict[str, str] = filters.get("numMax") or {}
    num_gt: dict[str, str] = filters.get("numGt") or {}
    num_lt: dict[str, str] = filters.get("numLt") or {}
    str_one_of: dict[str, list[str]] = filters.get("stringOneOf") or {}
    str_contains: dict[str, str] = filters.get("stringContains") or {}
    str_equals: dict[str, str] = filters.get("stringEquals") or {}

    # Workflow-note filters
    wf_status = filters.get("status") or "all"
    wf_has_row_note = filters.get("hasRowNote") or "any"
    wf_highlighted = filters.get("noteHighlighted") or "any"
    wf_active_position = filters.get("activePosition") or "any"
    wf_comment = filters.get("noteComment") or "any"
    wf_stage = filters.get("noteStage") or ""
    wf_priority_eq = (filters.get("notePriorityEq") or "").strip()
    wf_priority_gt = (filters.get("notePriorityGt") or "").strip()
    wf_priority_lt = (filters.get("notePriorityLt") or "").strip()
    wf_priority_min = (filters.get("notePriorityMin") or "").strip()
    wf_priority_max = (filters.get("notePriorityMax") or "").strip()
    wf_tags_any: list[str] = filters.get("noteTagsAny") or []

    seen: set[str] = set()
    out: list[str] = []

    for row in rows:
        symbol = str(row.get("symbol") or "")
        rd: dict[str, Any] = row.get("row_data") or {}

        if symbol_contains and symbol_contains not in symbol.lower():
            continue

        skip = False

        # ── Workflow: status ──
        if wf_status != "all":
            if str(rd.get("__note_status")) != wf_status:
                continue

        # ── Workflow: hasRowNote ──
        if wf_has_row_note == "yes" and not rd.get("__note_hasRowNote"):
            continue
        elif wf_has_row_note == "no" and rd.get("__note_hasRowNote"):
            continue

        # ── Workflow: highlighted ──
        if wf_highlighted == "yes" and not rd.get("__note_highlighted"):
            continue
        elif wf_highlighted == "no" and rd.get("__note_highlighted"):
            continue

        # ── Workflow: activePosition ──
        if wf_active_position == "yes" and not rd.get("__note_activePosition"):
            continue
        elif wf_active_position == "no" and rd.get("__note_activePosition"):
            continue

        # ── Workflow: comment ──
        if wf_comment == "with" and not rd.get("__note_comment"):
            continue
        elif wf_comment == "without" and rd.get("__note_comment"):
            continue

        # ── Workflow: stage ──
        if wf_stage == "__none__":
            if rd.get("__note_stage"):
                continue
        elif wf_stage:
            if str(rd.get("__note_stage") or "") != wf_stage:
                continue

        # ── Workflow: priority ──
        def _num(v: Any) -> float | None:
            if v is None:
                return None
            try:
                return float(v)
            except (TypeError, ValueError):
                return None

        if wf_priority_eq:
            peq = float(wf_priority_eq)
            pv = _num(rd.get("__note_priority"))
            if pv is None or pv != peq:
                continue
        else:
            if wf_priority_gt:
                b = float(wf_priority_gt)
                pv = _num(rd.get("__note_priority"))
                if pv is None or not (pv > b):
                    continue
            if wf_priority_lt:
                b = float(wf_priority_lt)
                pv = _num(rd.get("__note_priority"))
                if pv is None or not (pv < b):
                    continue
            if wf_priority_min:
                b = float(wf_priority_min)
                pv = _num(rd.get("__note_priority"))
                if pv is None or pv < b:
                    continue
            if wf_priority_max:
                b = float(wf_priority_max)
                pv = _num(rd.get("__note_priority"))
                if pv is None or pv > b:
                    continue

        # ── Workflow: tags ──
        if wf_tags_any:
            note_tags: list[str] = rd.get("__note_tags") or []
            if not any(t in note_tags for t in wf_tags_any):
                continue

        # ── Row data filters (existing) ──

        for key, on in bool_require.items():
            if not on:
                continue
            if not rd.get(key):
                skip = True
                break
        if skip:
            continue

        for key, on in bool_reject.items():
            if not on:
                continue
            if rd.get(key):
                skip = True
                break
        if skip:
            continue

        for key, bound_s in num_min.items():
            if not (bound_s or "").strip():
                continue
            try:
                b = float(bound_s)
                v = rd.get(key)
                vf = v if isinstance(v, (int, float)) else float(str(v))
                if not (vf >= b):
                    skip = True
                    break
            except (TypeError, ValueError):
                skip = True
                break
        if skip:
            continue

        for key, bound_s in num_max.items():
            if not (bound_s or "").strip():
                continue
            try:
                b = float(bound_s)
                v = rd.get(key)
                vf = v if isinstance(v, (int, float)) else float(str(v))
                if not (vf <= b):
                    skip = True
                    break
            except (TypeError, ValueError):
                skip = True
                break
        if skip:
            continue

        for key, bound_s in num_gt.items():
            if not (bound_s or "").strip():
                continue
            try:
                b = float(bound_s)
                v = rd.get(key)
                vf = v if isinstance(v, (int, float)) else float(str(v))
                if not (vf > b):
                    skip = True
                    break
            except (TypeError, ValueError):
                skip = True
                break
        if skip:
            continue

        for key, bound_s in num_lt.items():
            if not (bound_s or "").strip():
                continue
            try:
                b = float(bound_s)
                v = rd.get(key)
                vf = v if isinstance(v, (int, float)) else float(str(v))
                if not (vf < b):
                    skip = True
                    break
            except (TypeError, ValueError):
                skip = True
                break
        if skip:
            continue

        for key, allowed in str_one_of.items():
            if not allowed:
                continue
            s = _stringify_value(rd.get(key))
            if s not in allowed:
                skip = True
                break
        if skip:
            continue

        for key, needle in str_contains.items():
            if not (needle or "").strip():
                continue
            s = _stringify_value(rd.get(key)).lower()
            if needle.strip().lower() not in s:
                skip = True
                break
        if skip:
            continue

        for key, expected in str_equals.items():
            if not (expected or "").strip():
                continue
            s = _stringify_value(rd.get(key))
            if s != expected.strip():
                skip = True
                break
        if skip:
            continue

        if symbol and symbol not in seen:
            seen.add(symbol)
            out.append(symbol)

    return out


def _get_filtered_tickers_from_scan(
    user_id: str | None, scan_run_ids: list[int], scan_filters: dict
) -> list[str]:
    """Fetch scan rows + user notes for the given run IDs, merge notes into
    row_data as __note_* keys, apply scan_filters, and return filtered symbols."""
    if not user_id or not scan_run_ids:
        return []
    client = get_supabase_client()
    schema = "swingtrader"

    rows_res = (
        client.schema(schema)
        .table("user_scan_rows")
        .select("id, symbol, row_data")
        .in_("run_id", scan_run_ids)
        .eq("user_id", user_id)
        .execute()
    )
    rows = rows_res.data or []

    notes_res = (
        client.schema(schema)
        .table("user_scan_row_notes")
        .select("scan_row_id, status, highlighted, comment, stage, priority, tags, metadata_json")
        .in_("run_id", scan_run_ids)
        .eq("user_id", user_id)
        .execute()
    )
    notes_by_row_id: dict[int, dict] = {}
    for n in (notes_res.data or []):
        notes_by_row_id[n["scan_row_id"]] = n

    for row in rows:
        rd: dict[str, Any] = row.get("row_data") or {}
        note = notes_by_row_id.get(row.get("id"))
        if note:
            rd["__note_status"] = note.get("status") or None
            rd["__note_highlighted"] = bool(note.get("highlighted"))
            rd["__note_hasRowNote"] = True
            rd["__note_comment"] = note.get("comment") or None
            rd["__note_stage"] = note.get("stage") or None
            rd["__note_priority"] = note.get("priority") if note.get("priority") is not None else None
            rd["__note_tags"] = note.get("tags") or []
            meta = note.get("metadata_json") or {}
            rd["__note_activePosition"] = bool(meta.get("activePosition"))
        else:
            rd["__note_status"] = None
            rd["__note_highlighted"] = False
            rd["__note_hasRowNote"] = False
            rd["__note_comment"] = None
            rd["__note_stage"] = None
            rd["__note_priority"] = None
            rd["__note_tags"] = []
            rd["__note_activePosition"] = False
        row["row_data"] = rd

    return _apply_scan_filters(rows, scan_filters)


# ── Linked screening context ──────────────────────────────────────────────────

def _get_linked_scan_run_context(
    user_id: str | None,
    scan_run_ids: list[int],
    filtered_tickers: list[str] | None = None,
) -> str:
    if not user_id or not scan_run_ids:
        return ""
    client = get_supabase_client()
    schema = "swingtrader"

    # Fetch runs
    runs_res = (
        client.schema(schema)
        .table("user_scan_runs")
        .select("id, scan_date, source")
        .in_("id", scan_run_ids)
        .eq("user_id", user_id)
        .execute()
    )
    runs = runs_res.data or []
    if not runs:
        return ""

    # Fetch notes for all linked runs
    notes_res = (
        client.schema(schema)
        .table("user_scan_row_notes")
        .select("run_id, ticker, status, highlighted, comment, stage, priority, tags")
        .in_("run_id", scan_run_ids)
        .eq("user_id", user_id)
        .execute()
    )
    notes_by_run: dict[int, list[dict]] = {}
    for n in notes_res.data or []:
        notes_by_run.setdefault(n["run_id"], []).append(n)

    lines: list[str] = []
    for r in runs:
        run_id = r.get("id", "")
        date = str(r.get("scan_date", ""))[:10]
        source = r.get("source") or ""
        label = f"Scan {run_id} ({date}"
        if source:
            label += f", {source}"
        label += ")"

        run_notes = notes_by_run.get(run_id, [])
        if run_notes:
            for n in run_notes[:20]:
                ticker = n.get("ticker", "")
                status = n.get("status", "")
                comment = (n.get("comment") or "")[:120]
                stage = n.get("stage") or ""
                highlighted = "★" if n.get("highlighted") else ""
                parts = [p for p in [highlighted, status, stage, comment] if p]
                note_str = f"{ticker} — {' '.join(parts)}" if parts else ticker
                lines.append(f"- {label}: {note_str}")
        else:
            lines.append(f"- {label}: (no notes)")

    if filtered_tickers:
        sample = filtered_tickers[:30]
        lines.append(
            f"\nFiltered tickers ({len(filtered_tickers)} total): "
            + ", ".join(sample)
            + (f" +{len(filtered_tickers) - 30} more" if len(filtered_tickers) > 30 else "")
        )

    return "\n".join(lines)


# ── Agent loop ──────────────────────────────────────────────────────────────

def run_agent(prompt: str, user_id: str | None = None, tickers: list[str] | None = None, linked_scan_run_ids: list[int] | None = None, filtered_tickers: list[str] | None = None) -> dict:
    """Run the screening agent loop. Returns {triggered, summary, data_used}."""
    _base_system = _AGENT_SYSTEM + (_FMP_SYSTEM_ADDON if _FMP_ENABLED else "")
    system = _base_system
    if user_id:
        strategy = get_user_trading_strategy(user_id)
        if strategy:
            system = (
                f"{_base_system}\n\n## User's Trading Strategy\n{strategy}\n"
                "Apply this strategy when evaluating screening conditions and writing summaries. "
                "Prioritise setups and signals that align with it."
            )
    if tickers:
        system += (
            f"\n\n## Focused Tickers\nThe user wants you to focus on: {', '.join(tickers)}.\n"
            "Prioritise these symbols in tool calls where a tickers parameter is available."
        )
    if linked_scan_run_ids:
        linked_context = _get_linked_scan_run_context(user_id, linked_scan_run_ids, filtered_tickers=filtered_tickers)
        if linked_context:
            system += (
                f"\n\n## Linked Screening Context\n{linked_context}\n"
                "Use this context alongside your own tool calls."
            )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": prompt},
    ]

    data_used: dict[str, Any] = {}
    resp: dict = {}

    tool_schemas = _TOOL_SCHEMAS + (get_fmp_tool_schemas() if _FMP_ENABLED else [])

    for _ in range(_MAX_TOOL_ROUNDS):
        resp = _ollama_chat(messages, tools=tool_schemas)

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

def _format_telegram_message(name: str, triggered: bool, summary: str | None, error: bool = False) -> str:
    if error:
        return f"<b>⚠️ {name}</b>\n\n<i>Run failed: {summary}</i>"
    if triggered:
        return f"<b>🔔 {name}</b>\n\n{summary}"
    return f"<b>✅ {name}</b>\n\n<i>No trigger — conditions not met.</i>"


# ── Trading session helpers ─────────────────────────────────────────────────

_SESSION_LABELS: dict[str, str] = {
    "nyse": "NYSE 9:30 AM – 4:00 PM ET",
}

_NYSE_OPEN = time(9, 30)
_NYSE_CLOSE = time(16, 0)


def _is_market_open(session: str) -> bool:
    """Check whether the current time falls within the given trading session."""
    if session == "nyse":
        # Use US Eastern time for NYSE
        try:
            from zoneinfo import ZoneInfo
            now_et = datetime.now(ZoneInfo("America/New_York"))
        except Exception:
            now_et = datetime.now(timezone.utc)
        t = now_et.timetz()
        # NYSE is also closed on weekdays
        if t.weekday() >= 5:
            return False
        return _NYSE_OPEN <= t < _NYSE_CLOSE
    return True



def run_screening(screening: dict, dry_run: bool = False, is_test: bool = False) -> dict:
    """Run a single screening. Returns the result dict (not yet persisted)."""
    base = {
        "screening_id": screening["id"],
        "user_id": screening.get("user_id"),
        "name": screening.get("name", "Screening"),
        "dry_run": dry_run,
        "is_test": is_test,
    }

    # ── Trading session gate ──
    # If the agent is configured to only run during a specific trading session,
    # check whether the market is currently open and skip if not.
    trading_session = (screening.get("trading_session") or "none")
    if trading_session != "none" and not is_test:
        if not _is_market_open(trading_session):
            log.info(
                "Skipping screening %s — market not open (session=%s)",
                screening["id"], trading_session,
            )
            return {
                **base,
                "triggered": False,
                "summary": f"Skipped: market not open ({_SESSION_LABELS.get(trading_session, trading_session)})",
                "data_used": {},
            }

    try:
        explicit_tickers: list[str] = screening.get("tickers") or []
        linked_ids: list[int] = screening.get("linked_scan_run_ids") or []
        scan_filters: dict | None = screening.get("scan_filters")

        # If scan_filters are set, resolve the filtered ticker list from linked runs
        # and merge with any explicitly pinned tickers.
        filtered_tickers: list[str] | None = None
        if scan_filters and linked_ids:
            filtered = _get_filtered_tickers_from_scan(
                screening.get("user_id"), linked_ids, scan_filters
            )
            filtered_tickers = filtered
            # Explicit tickers take priority; filtered symbols follow (deduped)
            seen: set[str] = set(explicit_tickers)
            merged = list(explicit_tickers)
            for t in filtered:
                if t not in seen:
                    seen.add(t)
                    merged.append(t)
            resolved_tickers: list[str] | None = merged or None
        else:
            resolved_tickers = explicit_tickers or None

        result = run_agent(
            screening["prompt"],
            user_id=screening.get("user_id"),
            tickers=resolved_tickers,
            linked_scan_run_ids=linked_ids or None,
            filtered_tickers=filtered_tickers,
        )
        result.update(base)
        return result
    except Exception as exc:
        log.exception("run_agent failed for screening %s", screening["id"])
        return {**base, "triggered": False, "summary": str(exc), "data_used": {}, "error": True}


def persist_and_deliver(result: dict, result_id: str | None = None) -> None:
    """Persist screening result to DB and deliver via Telegram.

    If result_id is given, updates the pre-inserted 'running' row created by
    the scheduler tick. Otherwise inserts a new row (legacy / dry-run path).
    """
    client = get_supabase_client()
    schema = "swingtrader"
    now = datetime.now(timezone.utc).isoformat()

    is_test = bool(result.get("is_test"))
    triggered = bool(result.get("triggered"))
    error = bool(result.get("error"))
    status = "error" if error else "done"

    if result_id:
        try:
            client.schema(schema).table("user_screening_results").update({
                "triggered": triggered,
                "summary": result.get("summary"),
                "data_used": result.get("data_used", {}),
                "status": status,
            }).eq("id", result_id).execute()
        except Exception as exc:
            log.error("Failed to update screening result %s: %s", result_id, exc)
            return
    else:
        row = {
            "screening_id": result["screening_id"],
            "user_id": result["user_id"],
            "run_at": now,
            "started_at": now,
            "triggered": triggered,
            "summary": result.get("summary"),
            "data_used": result.get("data_used", {}),
            "is_test": is_test,
            "delivered": False,
            "status": status,
        }
        try:
            ins = client.schema(schema).table("user_screening_results").insert(row).execute()
            result_id = (ins.data or [{}])[0].get("id")
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

    chat_id = get_user_chat_id(result["user_id"])
    if not chat_id:
        log.info("No Telegram chat_id for user %s — in-app only", result["user_id"])
        return

    html = _format_telegram_message(result["name"], triggered, result.get("summary"), error=error)
    success, msg_id, err = send_telegram_chunks(chat_id, html)

    log_telegram_message(
        user_id=result["user_id"],
        chat_id=chat_id,
        message_type="screening_error" if error else "screening_alert" if triggered else "screening_no_trigger",
        message_text=html,
        success=success,
        telegram_message_id=msg_id,
        error_text=err,
    )

    if success and result_id:
        client.schema(schema).table("user_screening_results").update(
            {"delivered": True},
        ).eq("id", result_id).execute()
