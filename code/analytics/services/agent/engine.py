"""
engine.py — LLM agent that interprets a screening prompt, queries data tools,
evaluates trigger conditions, and writes a summary.

All screenings use the same agent with access to both market-wide and
user-specific tools. The prompt drives the behaviour.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone, time
from typing import Any

import httpx

from shared.db import get_supabase_client
from shared.telegram import (
    get_user_chat_id,
    log_telegram_message,
    send_telegram_chunks,
)
from services.agent_core import (
    ToolRegistry,
    build_market_registry,
    build_user_registry,
    run_tool_loop,
)
from services.rag import get_user_trading_strategy
from services.rag.screening import (
    apply_scan_filters as _apply_scan_filters,
    get_filtered_tickers_from_scan as _get_filtered_tickers_from_scan,
)
from services.rag.context import (
    get_linked_scan_run_context as _get_linked_scan_run_context,
)
from services.rag.taxonomy import CLUSTERS as _CLUSTERS

from .fmp_tools import _FMP_SYSTEM_ADDON, call_fmp_tool, get_fmp_tool_schemas

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
{"triggered": true/false, "summary": "..." or null}

Do NOT include data_used in your response — the engine fills it in from your tool calls. Emit only the two fields above. Keep the summary tight (a few sentences); do not echo raw tool results back into it.
"""

_AGENT_SYSTEM = _AGENT_SYSTEM.replace("{_CLUSTER_BLOCK_PLACEHOLDER}", _CLUSTER_BLOCK)

# ── Config ──────────────────────────────────────────────────────────────────

_OLLAMA_URL_ENV = "OLLAMA_BASE_URL"
_OLLAMA_MODEL_ENV = "OLLAMA_TIKTOK_MODEL"

_FMP_ENABLED = bool(os.environ.get("FMP_API_KEY"))

_MAX_TOOL_ROUNDS = 10


# ── Agent loop ──────────────────────────────────────────────────────────────

def _build_registry(user_id: str | None) -> ToolRegistry:
    """Compose this agent's tool stack on top of the shared base.

    Layers (low → high precedence):
      1. base market RAG tools + fetch_url (services.agent_core)
      2. user-scoped RAG tools when a user_id is given
      3. FMP MCP tools when FMP_API_KEY is set
    """
    registry = build_market_registry()
    if user_id:
        registry.extend(build_user_registry(user_id))
    if _FMP_ENABLED:
        registry.add_schemas(get_fmp_tool_schemas(), call_fmp_tool)
    return registry


def run_agent(
    prompt: str,
    user_id: str | None = None,
    tickers: list[str] | None = None,
    linked_scan_run_ids: list[int] | None = None,
    filtered_tickers: list[str] | None = None,
    trigger_condition: str | None = None,
) -> dict:
    """Run the screening agent loop. Returns {triggered, summary, data_used}.

    When ``trigger_condition`` is a non-empty string, it acts as the
    user-defined send gate: the agent only sets ``triggered=true`` if the
    gathered data satisfies the condition. The informational-rundown
    override is suppressed in that mode so the gate is the only thing
    deciding delivery.
    """
    base_system = _AGENT_SYSTEM + (_FMP_SYSTEM_ADDON if _FMP_ENABLED else "")
    system = base_system
    if user_id:
        strategy = get_user_trading_strategy(user_id)
        if strategy:
            system = (
                f"{base_system}\n\n## User's Trading Strategy\n{strategy}\n"
                "Apply this strategy when evaluating screening conditions and writing summaries. "
                "Prioritise setups and signals that align with it."
            )
    if tickers:
        system += (
            f"\n\n## Focused Tickers\nThe user wants you to focus on: {', '.join(tickers)}.\n"
            "Prioritise these symbols in tool calls where a tickers parameter is available."
        )
    if linked_scan_run_ids:
        linked_context = _get_linked_scan_run_context(
            user_id, linked_scan_run_ids, filtered_tickers=filtered_tickers
        )
        if linked_context:
            system += (
                f"\n\n## Linked Screening Context\n{linked_context}\n"
                "Use this context alongside your own tool calls."
            )
    has_condition = bool(trigger_condition and trigger_condition.strip())
    if has_condition:
        system += (
            "\n\n## Send-to-Telegram condition (USER-SET — overrides every other trigger rule)\n"
            "This screening only sends a Telegram alert when the following condition is satisfied "
            "by the data your tools return:\n\n"
            f"CONDITION: {trigger_condition.strip()}\n\n"
            "Procedure:\n"
            "1. Run the tool calls needed to gather the relevant data.\n"
            "2. Evaluate the CONDITION against that data.\n"
            "3. If the CONDITION is clearly TRUE, set triggered=true and write the summary normally — "
            "include the specific data points that proved it.\n"
            "4. If the CONDITION is FALSE, ambiguous, or the data needed to evaluate it is missing, "
            "set triggered=false and summary=null.\n"
            "5. The 'informational rundown / give me / show me' override above does NOT apply when a "
            "CONDITION is set — the user has explicitly asked for a conditional alert. Do not flip "
            "to triggered=true just because the prompt sounds informational."
        )
    else:
        system += (
            "\n\n## Send-to-Telegram mode: ALWAYS SEND (no condition set)\n"
            "This screening has NO trigger condition, so it runs in always-send mode. You MUST "
            "set triggered=true regardless of whether the data is strong, weak, partial, or "
            "empty. Always write a summary describing what you found — even if signals are "
            "weak, even if tools returned no rows, even if the user has no positions, even if "
            "you couldn't satisfy every part of the prompt. The conservative rule above is "
            "SUPPRESSED in this mode; the informational override is mandatory. summary must "
            "never be null. If the data really is empty, say so plainly in the summary "
            "(e.g. 'No positions found in your portfolio' or 'No news in the last 24 hours "
            "for your holdings')."
        )

    registry = _build_registry(user_id)
    result = asyncio.run(_run_agent_async(system, prompt, registry))

    if not has_condition:
        result["triggered"] = True
        if not (result.get("summary") or "").strip():
            result["summary"] = (
                "Screening ran in always-send mode but the agent did not produce a summary. "
                "See data_used for the raw tool results."
            )

    return result


async def _run_agent_async(
    system: str, user_prompt: str, registry: ToolRegistry
) -> dict:
    base_url = os.environ.get(_OLLAMA_URL_ENV, "http://localhost:11434").rstrip("/")
    model = (
        os.environ.get(_OLLAMA_MODEL_ENV)
        or os.environ.get("OLLAMA_BLOG_MODEL")
        or "gemma4:e4b"
    )
    async with httpx.AsyncClient() as client:
        final_message, tool_results, _rounds = await run_tool_loop(
            client,
            base_url=base_url,
            model=model,
            system=system,
            user=user_prompt,
            registry=registry,
            max_rounds=_MAX_TOOL_ROUNDS,
            options={"num_predict": 4096},
            request_format="json",
            label="Screening agent",
        )

    data_used = {n: _summarise_tool_result(n, r) for n, r in tool_results.items()}
    raw = (final_message.get("content") or "").strip()
    raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        log.warning(
            "Agent returned non-JSON (len=%d, head=%r, tail=%r): %s",
            len(raw), raw[:120], raw[-120:] if len(raw) > 120 else "", raw,
        )
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

        condition_enabled = bool(screening.get("condition_enabled"))
        trigger_condition = (
            (screening.get("trigger_condition") or "").strip()
            if condition_enabled
            else None
        )

        result = run_agent(
            screening["prompt"],
            user_id=screening.get("user_id"),
            tickers=resolved_tickers,
            linked_scan_run_ids=linked_ids or None,
            filtered_tickers=filtered_tickers,
            trigger_condition=trigger_condition or None,
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
    message_type = (
        "screening_error" if error
        else "screening_alert" if triggered
        else "screening_no_trigger"
    )
    success, msg_id, err = send_telegram_chunks(chat_id, html)

    if success:
        log.info(
            "Telegram delivered: screening=%s user=%s type=%s chat_id=%s msg_id=%s",
            result["screening_id"], result["user_id"], message_type, chat_id, msg_id,
        )
    else:
        log.warning(
            "Telegram send FAILED: screening=%s user=%s type=%s chat_id=%s err=%s",
            result["screening_id"], result["user_id"], message_type, chat_id, err,
        )

    log_telegram_message(
        user_id=result["user_id"],
        chat_id=chat_id,
        message_type=message_type,
        message_text=html,
        success=success,
        telegram_message_id=msg_id,
        error_text=err,
    )

    if success and result_id:
        client.schema(schema).table("user_screening_results").update(
            {"delivered": True},
        ).eq("id", result_id).execute()
