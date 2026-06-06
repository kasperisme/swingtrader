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
from datetime import datetime, timezone, time, timedelta
from typing import Any

import httpx

from shared.billing import agents_blocked
from shared.db import get_supabase_client
from shared.telegram import (
    get_user_chat_id,
    log_telegram_message,
    send_telegram_chunks,
)
from services.agent_core import (
    ToolRegistry,
    build_market_registry,
    build_screening_write_registry,
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
from .multi_ticker import run_multi_ticker_async
from .run_trace import RunTrace

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

get_user_screening_note_details(tickers: list[str] | None = None, statuses: list[str] | None = None)
  Returns the user's per-ticker notes for their latest scan run with full
  workflow context. Each row: {ticker, status, stage, highlighted, priority,
  tags, comment, entry?}. When the user has marked a planned entry on the
  chart, `entry` is {price, direction, date, take_profit?, stop_loss?,
  bar_idx?}. Defaults to active+watchlist+pipeline (excludes dismissed).
  Use this when the prompt references entry points, planned trades, or the
  research stage of tracked tickers. ALWAYS pass `tickers` when you already
  know which symbols you care about (e.g. the focused tickers below) —
  unfiltered responses are capped at ~25 rows and your target may not be in
  that slice.

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

_MAX_TOOL_ROUNDS = int(os.environ.get("AGENT_MAX_TOOL_ROUNDS", "10"))
# Hard wall-clock ceiling on a single run. Stays well below the scheduler's
# stuck cutoff so the worker fails itself (with a useful summary) instead of
# being killed externally — which previously left the queue blocked for the
# full 20-minute detection window.
_RUN_TIMEOUT_SECONDS = float(os.environ.get("AGENT_RUN_TIMEOUT_SECONDS", "240"))


# ── Agent loop ──────────────────────────────────────────────────────────────

def _build_registry(
    user_id: str | None,
    writeable_run_ids: list[int] | None = None,
) -> ToolRegistry:
    """Compose this agent's tool stack on top of the shared base.

    Layers (low → high precedence):
      1. base market RAG tools + fetch_url (services.agent_core)
      2. user-scoped RAG tools when a user_id is given
      3. screening write tools — only when the scheduled agent is connected
         to one or more screenings (writeable_run_ids non-empty). The build
         function rejects writes to any run_id outside this whitelist.
      4. FMP MCP tools when FMP_API_KEY is set
    """
    registry = build_market_registry()
    if user_id:
        registry.extend(build_user_registry(user_id))
        if writeable_run_ids:
            registry.extend(
                build_screening_write_registry(user_id, writeable_run_ids)
            )
    if _FMP_ENABLED:
        registry.add_schemas(get_fmp_tool_schemas(), call_fmp_tool)
    return registry


def _build_context_addon(user_id: str | None, linked_scan_run_ids: list[int] | None,
                         filtered_tickers: list[str] | None) -> str:
    """Compose the strategy + linked-context block passed to every stage of
    the multi-ticker pipeline. Returns empty string when neither applies."""
    parts: list[str] = []
    if user_id:
        strategy = (get_user_trading_strategy(user_id) or "").strip()
        if strategy:
            parts.append(
                f"User's trading strategy:\n{strategy}\n"
                "Apply this when evaluating tickers and writing verdicts."
            )
    if linked_scan_run_ids:
        linked = _get_linked_scan_run_context(
            user_id, linked_scan_run_ids, filtered_tickers=filtered_tickers
        )
        linked = (linked or "").strip()
        if linked:
            parts.append(f"Linked screening context:\n{linked}")
    return "\n\n".join(parts)


def _run_agent_multi_ticker(
    *,
    prompt: str,
    user_id: str | None,
    tickers: list[str],
    linked_scan_run_ids: list[int] | None,
    filtered_tickers: list[str] | None,
    trigger_condition: str | None,
    trace: RunTrace,
) -> dict:
    """Route a multi-ticker screening through the plan → fan-out → conclude
    pipeline. Mirrors ``run_agent``'s return contract and applies the same
    always-send / condition gating semantics on top of the pipeline's verdict.
    """
    has_condition = bool(trigger_condition and trigger_condition.strip())
    # Multi-ticker pipeline is read-only by design; write tools are filtered
    # out of the planner's catalog. We still build the registry with the user
    # scoped in so RAG queries (positions, alerts, etc.) work if the planner
    # picks them.
    writeable_run_ids = (
        list(linked_scan_run_ids) if (user_id and linked_scan_run_ids) else None
    )
    registry = _build_registry(user_id, writeable_run_ids=writeable_run_ids)
    context_addon = _build_context_addon(
        user_id, linked_scan_run_ids, filtered_tickers
    )

    log.info(
        "run_agent: routing to multi-ticker pipeline — tickers=%d has_condition=%s context_addon_len=%d",
        len(tickers), has_condition, len(context_addon),
    )

    try:
        result = asyncio.run(
            asyncio.wait_for(
                run_multi_ticker_async(
                    prompt=prompt,
                    tickers=tickers,
                    registry=registry,
                    trigger_condition=(
                        trigger_condition.strip() if has_condition else None
                    ),
                    context_addon=context_addon,
                    trace=trace,
                ),
                timeout=_RUN_TIMEOUT_SECONDS,
            )
        )
    except asyncio.TimeoutError:
        log.error(
            "Multi-ticker pipeline timed out after %.0fs (tickers=%d)",
            _RUN_TIMEOUT_SECONDS, len(tickers),
        )
        # The trace lives in this (synchronous) frame, not the cancelled
        # coroutine, so events recorded before the deadline are preserved.
        trace.event("run", "wall_clock_timeout", timeout_s=_RUN_TIMEOUT_SECONDS)
        result = {
            "triggered": False,
            # Mark as a real run failure so delivery renders the ⚠️ "Run failed"
            # alert instead of the misleading ✅ "no trigger" checkmark. A
            # wall-clock timeout is a failure, not "conditions not met".
            "error": True,
            "summary": (
                f"Multi-ticker pipeline exceeded the {_RUN_TIMEOUT_SECONDS:.0f}s "
                "wall-clock deadline before producing a result."
            ),
            "data_used": {
                "error": "wall_clock_timeout",
                "timeout_seconds": _RUN_TIMEOUT_SECONDS,
                "ticker_count": len(tickers),
            },
        }

    # Apply the same always-send override the single-agent path uses. Without
    # a user-set condition, screenings always fire — the pipeline's verdict
    # only shapes the summary copy. A run failure (e.g. wall-clock timeout) is
    # exempt: it must surface as an error alert, not a forced "always send".
    if not has_condition and not result.get("error"):
        result["triggered"] = True
        if not (result.get("summary") or "").strip():
            result["summary"] = (
                "Screening ran in always-send mode but the agent did not produce a summary. "
                "See data_used for the per-ticker verdicts."
            )

    return result


def run_agent(
    prompt: str,
    user_id: str | None = None,
    tickers: list[str] | None = None,
    linked_scan_run_ids: list[int] | None = None,
    filtered_tickers: list[str] | None = None,
    trigger_condition: str | None = None,
    trace: RunTrace | None = None,
) -> dict:
    """Run the screening agent loop. Returns {triggered, summary, data_used}.

    When ``trigger_condition`` is a non-empty string, it acts as the
    user-defined send gate: the agent only sets ``triggered=true`` if the
    gathered data satisfies the condition. The informational-rundown
    override is suppressed in that mode so the gate is the only thing
    deciding delivery.

    When ``tickers`` has 2+ entries, routes to the multi-ticker fan-out
    pipeline (``services.agent.multi_ticker``) so each ticker is processed
    in an isolated LLM context and the conclusion sees only compact
    per-ticker verdicts. Single-ticker / no-ticker runs use the existing
    single-agent tool-calling loop.

    ``trace`` (a RunTrace) accumulates the ordered run events and is attached to
    the returned result as ``result["trace"]`` so the caller can persist it.
    """
    trace = trace or RunTrace()
    if tickers and len(tickers) >= 2:
        result = _run_agent_multi_ticker(
            prompt=prompt,
            user_id=user_id,
            tickers=tickers,
            linked_scan_run_ids=linked_scan_run_ids,
            filtered_tickers=filtered_tickers,
            trigger_condition=trigger_condition,
            trace=trace,
        )
        result["trace"] = trace.as_dict()
        return result

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

    # Expose write tools only when the agent is connected to screenings AND a
    # user is in scope. With no user_id we wouldn't know whose screening to
    # mutate, so the writes are unavailable by design.
    writeable_run_ids = (
        list(linked_scan_run_ids) if (user_id and linked_scan_run_ids) else None
    )
    if writeable_run_ids:
        system += (
            "\n\n## Screening write tools\n"
            "This scheduled agent is connected to one or more screenings, so "
            "you also have write access to them via:\n"
            " - add_ticker_to_screening(run_id, ticker)\n"
            " - set_screening_ticker_status(run_id, ticker, status?, comment?, highlighted?)\n"
            " - set_screening_ticker_note(run_id, ticker, comment)\n\n"
            f"Allowed run_ids (the only screenings you can write to): "
            f"{writeable_run_ids}\n\n"
            "When to call:\n"
            " - Use add_ticker_to_screening when the data clearly surfaces a "
            "new ticker the user should track in their list (e.g. a fresh "
            "high-impact catalyst on a name not yet in the screening).\n"
            " - Use set_screening_ticker_status to mark workflow state on a "
            "ticker that's already in the list — for example, dismiss a "
            "ticker the news has invalidated, move a name from active to "
            "watchlist, or add a short note explaining why.\n"
            " - Use set_screening_ticker_note when you only want to add a "
            "note without changing status.\n\n"
            "Rules:\n"
            " - Only call write tools when the user prompt or data clearly "
            "warrants it — these mutate the user's screening list.\n"
            " - Write tools never decide whether the screening is triggered. "
            "Decide triggered/summary based on the data, then optionally use "
            "the writes as side-effects.\n"
            " - Notes should be short (1 sentence, under 200 chars) and "
            "explain WHY this ticker / state change matters today.\n"
            " - status values: active, dismissed, watchlist, pipeline. "
            "If unsure, prefer 'watchlist' over 'pipeline'.\n"
            " - You may NOT write to any run_id outside the allowed list "
            "above; out-of-scope writes are rejected automatically."
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

    registry = _build_registry(user_id, writeable_run_ids=writeable_run_ids)
    trace.event("run", "start", mode="single_agent", ticker_count=len(tickers or []),
                has_condition=has_condition)
    try:
        result = asyncio.run(
            asyncio.wait_for(
                _run_agent_async(system, prompt, registry, trace=trace),
                timeout=_RUN_TIMEOUT_SECONDS,
            )
        )
    except asyncio.TimeoutError:
        log.error(
            "Agent run timed out after %.0fs (max_tool_rounds=%d)",
            _RUN_TIMEOUT_SECONDS,
            _MAX_TOOL_ROUNDS,
        )
        trace.event("run", "wall_clock_timeout", timeout_s=_RUN_TIMEOUT_SECONDS)
        result = {
            "triggered": False,
            # Surface as a real failure (⚠️ alert) rather than a ✅ "no trigger"
            # checkmark — a wall-clock timeout means the run never completed.
            "error": True,
            "summary": (
                f"Agent run exceeded the {_RUN_TIMEOUT_SECONDS:.0f}s wall-clock "
                "deadline before producing a result."
            ),
            "data_used": {
                "error": "wall_clock_timeout",
                "timeout_seconds": _RUN_TIMEOUT_SECONDS,
                "max_tool_rounds": _MAX_TOOL_ROUNDS,
            },
        }

    if not has_condition and not result.get("error"):
        result["triggered"] = True
        if not (result.get("summary") or "").strip():
            result["summary"] = (
                "Screening ran in always-send mode but the agent did not produce a summary. "
                "See data_used for the raw tool results."
            )

    result["trace"] = trace.as_dict()
    return result


async def _run_agent_async(
    system: str, user_prompt: str, registry: ToolRegistry,
    trace: RunTrace | None = None,
) -> dict:
    base_url = os.environ.get(_OLLAMA_URL_ENV, "http://localhost:11434").rstrip("/")
    model = (
        os.environ.get(_OLLAMA_MODEL_ENV)
        or os.environ.get("OLLAMA_BLOG_MODEL")
        or "gemma4:e4b"
    )
    log.info(
        "Screening agent: starting run — model=%s registry_tools=%d "
        "system_len=%d prompt_len=%d prompt_preview=%r",
        model,
        len(registry.names()),
        len(system),
        len(user_prompt),
        user_prompt[:200],
    )
    log.debug("Screening agent: registered tools = %s", registry.names())
    async with httpx.AsyncClient() as client:
        final_message, tool_results, rounds = await run_tool_loop(
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
    if trace is not None:
        trace.event("tools", "done", rounds=rounds, tools_used=list(tool_results.keys()))
    raw = (final_message.get("content") or "").strip()
    raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        log.warning(
            "Agent returned non-JSON (len=%d, head=%r, tail=%r): %s",
            len(raw), raw[:120], raw[-120:] if len(raw) > 120 else "", raw,
        )
        if trace is not None:
            trace.event("parse", "non_json", raw_len=len(raw))
        parsed = {"triggered": False, "summary": None, "data_used": data_used}
    parsed.setdefault("data_used", data_used)
    if trace is not None:
        trace.event("run", "parsed", triggered=parsed.get("triggered"),
                    summary_len=len((parsed.get("summary") or "")))
    log.info(
        "Screening agent: parsed result — rounds=%d triggered=%s summary_len=%d "
        "tools_used=%s",
        rounds,
        parsed.get("triggered"),
        len((parsed.get("summary") or "")),
        list(tool_results.keys()),
    )
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


def _billing_url() -> str:
    base = os.environ.get("APP_BASE_URL", "https://www.newsimpactscreener.com").rstrip("/")
    return f"{base}/protected/profile"


def _format_billing_reminder() -> str:
    """Reminder-only message sent when the owner isn't on an active paid plan.
    No agent output — just the nudge to set up billing."""
    return (
        "<b>⚠️ Agent paused</b>\n\n"
        "Running scheduled agents requires an active paid plan. "
        "Set up billing to resume your alerts:\n"
        f'<a href="{_billing_url()}">Set up billing</a>'
    )


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
        if now_et.weekday() >= 5:
            return False
        t = now_et.time()
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

    # ── Plan gate ──
    # Scheduled agents only run for an active/trialing paid plan. The free
    # Observer tier and lapsed/failing subscriptions do NOT spend any LLM
    # resources — short-circuit before the prompt runs; delivery sends a
    # reminder-only Telegram message instead. Test runs always run so the user
    # can preview their agent. The agent stays scheduled and resumes
    # automatically once the user is on a paid plan in good standing.
    if not is_test and agents_blocked(screening.get("user_id")):
        log.info(
            "Plan-blocked screening %s (user=%s) — observer/lapsed tier, skipping LLM, sending reminder",
            screening["id"], screening.get("user_id"),
        )
        return {
            **base,
            "triggered": False,
            "billing_blocked": True,
            "summary": None,
            "data_used": {},
            "trace": None,
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
                "skipped": True,
                "summary": f"Skipped: market not open ({_SESSION_LABELS.get(trading_session, trading_session)})",
                "data_used": {},
            }

    # Own the trace here so it's attached even if run_agent raises before it can
    # return one — the error row then still carries the events up to the failure.
    trace = RunTrace()
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

        log.info(
            "Screening %s (%s) → run_agent: user=%s tickers_explicit=%d "
            "tickers_filtered=%d linked_runs=%d has_condition=%s prompt_len=%d",
            screening["id"],
            screening.get("name") or "(unnamed)",
            screening.get("user_id"),
            len(explicit_tickers),
            len(filtered_tickers or []),
            len(linked_ids),
            bool(trigger_condition),
            len(screening.get("prompt") or ""),
        )

        result = run_agent(
            screening["prompt"],
            user_id=screening.get("user_id"),
            tickers=resolved_tickers,
            linked_scan_run_ids=linked_ids or None,
            filtered_tickers=filtered_tickers,
            trigger_condition=trigger_condition or None,
            trace=trace,
        )
        result.update(base)
        result.setdefault("trace", trace.as_dict())
        return result
    except Exception as exc:
        log.exception("run_agent failed for screening %s", screening["id"])
        trace.event("run", "exception", error=f"{type(exc).__name__}: {str(exc)[:300]}")
        return {**base, "triggered": False, "summary": str(exc), "data_used": {},
                "error": True, "trace": trace.as_dict()}


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
    skipped = bool(result.get("skipped"))
    billing_blocked = bool(result.get("billing_blocked"))
    status = "error" if error else "skipped" if (skipped or billing_blocked) else "done"
    trace = result.get("trace")  # ordered event log; persisted even on error/timeout

    if result_id:
        try:
            client.schema(schema).table("user_screening_results").update({
                "triggered": triggered,
                "summary": result.get("summary"),
                "data_used": result.get("data_used", {}),
                "trace": trace,
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
            "trace": trace,
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

    if billing_blocked:
        _deliver_billing_reminder(client, schema, result, result_id, now)
        return

    if skipped:
        log.info(
            "Skipping Telegram delivery: screening=%s reason=%s",
            result["screening_id"], result.get("summary"),
        )
        return

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


_BILLING_REMINDER_THROTTLE_HOURS = 24


def _billing_reminder_recently_sent(client, schema: str, user_id: str) -> bool:
    """True if a billing reminder was sent to this user within the throttle
    window — so frequent agents don't spam the same nudge every run."""
    since = (
        datetime.now(timezone.utc) - timedelta(hours=_BILLING_REMINDER_THROTTLE_HOURS)
    ).isoformat()
    try:
        res = (
            client.schema(schema)
            .table("telegram_message_log")
            .select("id")
            .eq("user_id", user_id)
            .eq("message_type", "billing_reminder")
            .gte("sent_at", since)
            .limit(1)
            .execute()
        )
        return bool(res.data)
    except Exception as exc:
        log.warning("[billing] throttle lookup failed for %s: %s", user_id, exc)
        return False  # on error, prefer to send rather than go silent


def _deliver_billing_reminder(client, schema: str, result: dict, result_id: str | None, now: str) -> None:
    """Send a reminder-only Telegram message for a billing-blocked run, at most
    once per throttle window per user."""
    user_id = result["user_id"]
    chat_id = get_user_chat_id(user_id)
    if not chat_id:
        log.info("No Telegram chat_id for user %s — billing reminder in-app only", user_id)
        return

    if _billing_reminder_recently_sent(client, schema, user_id):
        log.info("Billing reminder throttled for user %s (sent within 24h)", user_id)
        return

    html = _format_billing_reminder()
    success, msg_id, err = send_telegram_chunks(chat_id, html)
    if success:
        log.info("Billing reminder delivered: user=%s chat_id=%s msg_id=%s", user_id, chat_id, msg_id)
    else:
        log.warning("Billing reminder FAILED: user=%s chat_id=%s err=%s", user_id, chat_id, err)

    log_telegram_message(
        user_id=user_id,
        chat_id=chat_id,
        message_type="billing_reminder",
        message_text=html,
        success=success,
        telegram_message_id=msg_id,
        error_text=err,
    )

    if success and result_id:
        client.schema(schema).table("user_screening_results").update(
            {"delivered": True},
        ).eq("id", result_id).execute()
