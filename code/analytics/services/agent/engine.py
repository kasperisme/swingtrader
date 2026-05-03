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
from services.rag import (
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
    TOOL_SCHEMAS as _RAG_TOOL_SCHEMAS,
    get_market_tools,
    get_user_tools,
)
from services.rag.screening import apply_scan_filters as _apply_scan_filters, get_filtered_tickers_from_scan as _get_filtered_tickers_from_scan
from services.rag.context import get_linked_scan_run_context as _get_linked_scan_run_context
from services.rag.taxonomy import CLUSTERS as _CLUSTERS

log = logging.getLogger(__name__)


def _format_cluster_block() -> str:
    lines = []
    for c in _CLUSTERS:
        dims = ", ".join(key for key, _label in c["dimensions"])
        lines.append(f"{c['id']}: {dims}")
    return "\n\n".join(lines)


_CLUSTER_BLOCK = _format_cluster_block()

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

{_CLUSTER_BLOCK_PLACEHOLDER}

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

_AGENT_SYSTEM = _AGENT_SYSTEM.replace("{_CLUSTER_BLOCK_PLACEHOLDER}", _CLUSTER_BLOCK)

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


_TOOLS_MARKET = {**get_market_tools(), "fetch_url": fetch_url}
_TOOLS_USER = get_user_tools()

_TOOL_SCHEMAS = _RAG_TOOL_SCHEMAS

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


# ── Scan filter helpers — logic lives in services/rag/screening.py ────────────


# _apply_scan_filters, _get_filtered_tickers_from_scan, _get_linked_scan_run_context
# are imported from services.rag at the top of this file.


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
