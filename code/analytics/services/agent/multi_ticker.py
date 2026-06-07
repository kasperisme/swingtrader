"""
multi_ticker.py — fan-out screening pipeline.

When a screening has >= 2 tickers in scope, route here instead of the single
agentic loop. Three isolated LLM contexts:

  Stage 1 (plan):       one call sees the full tool catalog and decides which
                        tools to invoke per ticker, with the literal "{TICKER}"
                        as a placeholder.
  Stage 2 (per-ticker): execute the planned tools per ticker (parallel within
                        a ticker), then evaluate tickers in mini-batches — one
                        LLM call reads {prompt, B tickers' tool data} and emits
                        one verdict per ticker. Batching cuts the call count
                        from N to ceil(N/B), the main lever for large
                        screenings (set AGENT_MULTI_TICKER_BATCH_SIZE=1 to
                        restore one-ticker-per-call). Each batch gets a fresh
                        context — tool output from one batch never enters
                        another's prompt — and the evaluator judges each ticker
                        independently. Bounded concurrency at the batch level.
  Stage 3 (conclude):   one call sees only the per-ticker verdicts (not raw
                        tool dumps) and synthesises the overall
                        {triggered, summary}.

Token usage stays roughly flat as N grows: stage 3 always sees N x compact
verdicts (~300 tokens each), not N x raw tool results.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from services.agent_core import ToolRegistry, simple_chat
from shared.i18n import language_instruction

from .fmp_tools import looks_like_access_denied
from .run_trace import RunTrace
from .skills import (
    ScreeningSkill,
    TickerSignal,
    _INTERNAL_TOOLS,
    classify_skill,
)

log = logging.getLogger(__name__)

_OLLAMA_URL_ENV = "OLLAMA_BASE_URL"
_OLLAMA_MODEL_ENV = "OLLAMA_TIKTOK_MODEL"

_TICKER_CONCURRENCY = int(os.environ.get("AGENT_MULTI_TICKER_CONCURRENCY", "3"))
_PLAN_TIMEOUT = float(os.environ.get("AGENT_PLAN_TIMEOUT", "90"))
_CONCLUDE_TIMEOUT = float(os.environ.get("AGENT_CONCLUDE_TIMEOUT", "60"))

# Mini-batching: evaluate several tickers per LLM call instead of one-each. The
# dominant wall-clock cost of a large screening is the N sequential per-ticker
# eval calls against a local (serially-served) Ollama. Grouping B tickers into
# a single eval call turns N calls into ceil(N/B), the biggest lever for runs
# with many tickers. Each batch still gets its own fresh context — tool data
# for a batch never enters another batch's prompt — and the evaluator is told
# to judge each ticker independently. Set to 1 to restore strict one-ticker-
# per-call isolation.
_BATCH_SIZE = max(1, int(os.environ.get("AGENT_MULTI_TICKER_BATCH_SIZE", "5")))
# A batch emits ~B verdicts, so it needs a larger ceiling than a single eval.
_BATCH_EVAL_TIMEOUT = float(os.environ.get("AGENT_BATCH_EVAL_TIMEOUT", "120"))
# Per-tool char cap inside a batched prompt. Tighter than the single-ticker cap
# because B tickers' worth of tool data share one prompt — keeps prefill bounded.
_BATCH_PER_TOOL_CHARS = int(os.environ.get("AGENT_BATCH_PER_TOOL_CHARS", "2500"))

_TICKER_PLACEHOLDER = "{TICKER}"
_MAX_TOOL_RESULT_CHARS = 4000

# Write tools mutate state — the planner must not pick them. The single-agent
# path still uses them via run_tool_loop; this pipeline is read-only.
_WRITE_TOOL_PREFIXES = ("add_ticker_to_screening", "set_screening_")

# Process-local memo of tool names that failed availability in this worker's
# lifetime (typically FMP endpoints the current API plan can't access). The
# trial-run validator adds to it; the planner's catalog builder reads from it
# to keep the prompt small on subsequent runs. NOT persisted to disk — a
# worker restart resets it, so this never outlives the running process.
_session_unavailable_tools: set[str] = set()


def reset_session_unavailable_tools() -> None:
    """Clear the per-process unavailable-tools memo. Test seam."""
    _session_unavailable_tools.clear()


def _today_str() -> str:
    """Current date (US Eastern, the market timezone) as ISO YYYY-MM-DD.

    Injected into every LLM stage so the planner emits correct date-range
    args (from_date/to_date) and the evaluator reasons about "today" against
    the real calendar — without this, models default to dates baked into
    their training data and request stale price windows.
    """
    try:
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo("America/New_York"))
    except Exception:
        now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%d")


# ── Stage 1: plan ───────────────────────────────────────────────────────────


_PLAN_SYSTEM = """You are a screening planner. You will be given a screening \
prompt and a list of tickers. Decide which data tools to call for EACH ticker \
so every ticker is evaluated against the same evidence base.

Rules:
- Pick the minimum tools needed (2-5 is normal).
- Use the literal string "{TICKER}" wherever the ticker should be substituted.
- Tools that accept a list of tickers should receive ["{TICKER}"] — fan-out \
is per-ticker, not batched.
- You MAY include market-wide tools whose args do not contain "{TICKER}" \
(e.g. cluster trends). They will run once and be shared across all tickers.
- Parameters shown as ``name={a|b|c}`` are ENUMS — you MUST use one of the \
listed values verbatim. Never guess or shorten enum values (e.g. for FMP \
``chart`` use ``endpoint="intraday-1-hour"``, not ``"1hr"``).
- For any date arguments (e.g. ``from_date``/``to_date``), compute them \
RELATIVE to TODAY'S DATE given in the user message. ``to_date`` should be \
today's date and ``from_date`` an appropriate lookback before it. NEVER use a \
date from memory or training data — always derive from the provided TODAY.
- Only pick from the AVAILABLE TOOLS list — do NOT invent tool names or \
assume tools exist beyond the catalog.
- If an "EXCLUDED TOOLS" list is given, those tools failed a trial-run \
availability check (typically a subscription-tier rejection). Do NOT pick \
them — choose alternatives from AVAILABLE TOOLS instead.
- Do NOT plan write tools (anything starting with "add_ticker_to_screening" \
or "set_screening_").

Respond with ONLY this JSON (no markdown, no commentary):
{
  "tool_plan": [
    {"name": "<tool_name>", "args": {<args, with "{TICKER}" where applicable>}}
  ],
  "per_ticker_brief": "<1-3 sentences: what each per-ticker evaluation should check, in plain English>",
  "rationale": "<1 sentence: why these tools>"
}
"""


def _format_param(name: str, schema: Any) -> str:
    """Render one parameter for the planner catalog.

    When a param has an ``enum`` constraint (common for FMP MCP tools whose
    ``endpoint`` arg selects which API to hit), expose every allowed value so
    the planner can pick a valid one rather than guessing. Without this hint
    the planner produces invalid enum values and FMP rejects the call.
    """
    if isinstance(schema, dict):
        enum_vals = schema.get("enum")
        if isinstance(enum_vals, list) and enum_vals:
            shown = (
                [str(v) for v in enum_vals]
                if len(enum_vals) <= 20
                else [str(v) for v in enum_vals[:20]] + ["..."]
            )
            return f"{name}={{{'|'.join(shown)}}}"
        typ = schema.get("type") or "any"
        return f"{name}:{typ}"
    return name


def _build_tool_catalog(
    registry: ToolRegistry,
    *,
    excluded: set[str] | None = None,
) -> str:
    """Build the planner-facing tool catalog.

    Drops write tools (pipeline is read-only), any names in ``excluded``
    (passed in by the re-plan path), and any tool the trial run has already
    flagged unavailable earlier in this worker's lifetime. Keeping the catalog
    small directly controls planner latency.
    """
    excluded = (excluded or set()) | _session_unavailable_tools
    lines: list[str] = []
    skipped_session: list[str] = []
    for schema in registry.schemas():
        fn = schema.get("function") or {}
        name = fn.get("name")
        if not name or any(name.startswith(p) for p in _WRITE_TOOL_PREFIXES):
            continue
        if name in excluded:
            if name in _session_unavailable_tools:
                skipped_session.append(name)
            continue
        desc = (fn.get("description") or "").strip().split("\n", 1)[0][:220]
        props = (fn.get("parameters") or {}).get("properties") or {}
        param_parts = [
            _format_param(p, props.get(p) or {})
            for p in list(props.keys())[:10]
        ]
        lines.append(f"- {name}({', '.join(param_parts)}): {desc}")
    if skipped_session:
        log.info(
            "Tool catalog: excluded %d tool(s) memoised unavailable this "
            "session — %s",
            len(skipped_session), sorted(skipped_session),
        )
    return "\n".join(lines)


async def _plan_tools(
    client: httpx.AsyncClient,
    *,
    base_url: str,
    model: str,
    prompt: str,
    tickers: list[str],
    registry: ToolRegistry,
    context_addon: str,
    excluded_tools: set[str] | None = None,
) -> dict:
    catalog = _build_tool_catalog(registry, excluded=excluded_tools)
    user_parts = [
        f"TODAY'S DATE: {_today_str()}",
        f"SCREENING PROMPT:\n{prompt}",
        f"TICKERS ({len(tickers)}): {', '.join(tickers)}",
        f"AVAILABLE TOOLS:\n{catalog}",
    ]
    if excluded_tools:
        user_parts.append(
            "EXCLUDED TOOLS (failed a trial-run availability check — do not pick):\n"
            + ", ".join(sorted(excluded_tools))
        )
    if context_addon:
        user_parts.append(f"CONTEXT:\n{context_addon}")
    user_parts.append("Return the JSON plan now.")
    raw = await simple_chat(
        client,
        base_url=base_url,
        model=model,
        system=_PLAN_SYSTEM,
        user="\n\n".join(user_parts),
        request_format="json",
        label="Multi-ticker planner",
    )
    log.info(
        "Multi-ticker planner: raw response len=%d head=%r tail=%r",
        len(raw),
        raw[:200],
        raw[-200:] if len(raw) > 200 else "",
    )
    return _parse_plan(raw)


def _parse_plan(raw: str) -> dict:
    raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    if not raw:
        log.warning("Multi-ticker planner: empty response (no content emitted)")
        return {"tool_plan": [], "per_ticker_brief": "", "rationale": ""}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        log.warning("Multi-ticker planner: non-JSON plan, head=%r", raw[:200])
        return {"tool_plan": [], "per_ticker_brief": "", "rationale": ""}
    plan_raw = data.get("tool_plan")
    plan_in = plan_raw if isinstance(plan_raw, list) else []
    cleaned: list[dict] = []
    for entry in plan_in:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        args = entry.get("args") or {}
        if not isinstance(name, str) or not name.strip() or not isinstance(args, dict):
            continue
        nm = name.strip()
        if any(nm.startswith(p) for p in _WRITE_TOOL_PREFIXES):
            continue
        cleaned.append({"name": nm, "args": args})
    return {
        "tool_plan": cleaned,
        "per_ticker_brief": str(data.get("per_ticker_brief") or "").strip(),
        "rationale": str(data.get("rationale") or "").strip(),
    }


def _default_fallback_plan(registry: ToolRegistry) -> dict:
    """Construct a sensible plan when the LLM planner returns nothing.

    Thinking-model planners (glm-*, qwen-thinking, etc.) sometimes burn the
    `num_predict` budget on hidden reasoning and emit no JSON. Rather than
    abort the whole screening, fall back to the canonical per-ticker
    news-impact tool set — the ones that motivate this product in the first
    place. Only tools actually in the registry are included.
    """
    candidates: list[tuple[str, dict]] = [
        (
            "get_ticker_news",
            {"tickers": ["{TICKER}"], "hours": 24, "per_ticker_limit": 5},
        ),
        ("get_ticker_sentiment", {"tickers": ["{TICKER}"], "hours": 24}),
        ("get_ticker_relationships", {"ticker": "{TICKER}", "hops": 1}),
        ("get_company_vectors", {"tickers": ["{TICKER}"]}),
    ]
    plan: list[dict] = [
        {"name": name, "args": args}
        for name, args in candidates
        if registry.has(name)
    ]
    return {
        "tool_plan": plan,
        "per_ticker_brief": (
            "Evaluate this ticker against the screening prompt using the "
            "latest news, sentiment scores, relationship graph, and company "
            "factor profile. Cite specific data points."
        ),
        "rationale": "fallback: planner returned no plan, using canonical per-ticker tools",
    }


def _ensure_latest_news_in_plan(
    plan: list[dict], registry: ToolRegistry
) -> list[dict]:
    """Guarantee ``get_ticker_news`` is in the planned per-ticker tool set.

    The LLM planner can pick anything, and some configurations skip news
    altogether (e.g. when it leans hard on sentiment + relationships). For a
    *news* impact screener that's a bad floor — we always want the actual
    headlines available to each per-ticker evaluator. If the registry doesn't
    expose ``get_ticker_news`` (custom environment) we leave the plan alone.
    """
    if not registry.has("get_ticker_news"):
        return plan
    for entry in plan:
        if entry.get("name") == "get_ticker_news":
            return plan
    return list(plan) + [
        {
            "name": "get_ticker_news",
            "args": {
                "tickers": [_TICKER_PLACEHOLDER],
                "hours": 72,
                "per_ticker_limit": 8,
            },
        }
    ]


def _split_plan(plan: list[dict]) -> tuple[list[dict], list[dict]]:
    """Split into (per_ticker_calls, shared_market_wide_calls).

    A call is per-ticker if its args contain the {TICKER} placeholder anywhere;
    otherwise it's market-wide and should run only once across the fan-out.
    """
    per_ticker: list[dict] = []
    shared: list[dict] = []
    for entry in plan:
        try:
            args_str = json.dumps(entry.get("args") or {}, default=str)
        except Exception:
            args_str = repr(entry.get("args"))
        if _TICKER_PLACEHOLDER in args_str:
            per_ticker.append(entry)
        else:
            shared.append(entry)
    return per_ticker, shared


# ── Stage 1.5: trial-run availability check ─────────────────────────────────


def _result_unavailable(result: Any) -> bool:
    """True when ``result`` looks like a subscription-tier rejection.

    Handles both shapes the FMP client can produce: an ``{"error": msg}``
    envelope (raised exception path) and a structured/text body returned by
    the MCP server that contains an access-denied marker in its payload.
    """
    if result is None:
        return False
    if isinstance(result, dict):
        err = result.get("error")
        if isinstance(err, str) and looks_like_access_denied(err):
            return True
        try:
            payload = json.dumps(result, default=str)
        except Exception:
            return False
        return looks_like_access_denied(payload)
    if isinstance(result, str):
        return looks_like_access_denied(result)
    return False


async def _trial_run_plan(
    registry: ToolRegistry,
    plan: list[dict],
    probe_ticker: str,
) -> tuple[set[str], dict[str, Any]]:
    """Probe every unique tool in ``plan`` once to verify availability.

    Per-ticker tools (args contain ``{TICKER}``) are substituted with
    ``probe_ticker``; shared tools are called with their planned args.
    Returns ``(unavailable_tool_names, results_by_name)`` where the result
    map can be reused as the shared-tool cache so we don't re-execute on the
    real fan-out.
    """
    if not plan:
        return set(), {}

    # Dedup by name — same tool listed twice gets probed once.
    seen: set[str] = set()
    unique: list[dict] = []
    for entry in plan:
        name = entry.get("name")
        if not isinstance(name, str) or name in seen:
            continue
        seen.add(name)
        unique.append(entry)

    async def _probe(entry: dict) -> tuple[str, Any]:
        name = entry["name"]
        args = _substitute_ticker(entry.get("args") or {}, probe_ticker)
        if not registry.has(name):
            return name, {"error": f"unknown tool {name!r}"}
        try:
            return name, await registry.call(name, args)
        except Exception as exc:  # noqa: BLE001
            return name, {"error": str(exc)}

    pairs = await asyncio.gather(*(_probe(e) for e in unique))
    results: dict[str, Any] = {n: r for n, r in pairs}
    unavailable = {n for n, r in results.items() if _result_unavailable(r)}
    return unavailable, results


# ── Stage 2: per-ticker execution ───────────────────────────────────────────


# Date-window lookbacks for skills that request a price/history range via the
# {FROM_DATE}/{TO_DATE} placeholders. The daily window (~45 calendar days)
# covers a 20-trading-bar lookback through weekends/holidays; the intraday
# window ({FROM_DATE_INTRADAY}) is short so an hourly series stays small.
_DATE_LOOKBACK_DAYS = int(os.environ.get("AGENT_PRICE_LOOKBACK_DAYS", "45"))
_INTRADAY_LOOKBACK_DAYS = int(os.environ.get("AGENT_INTRADAY_LOOKBACK_DAYS", "5"))


def _et_today():
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("America/New_York")).date()
    except Exception:
        return datetime.now(timezone.utc).date()


def _date_window() -> tuple[str, str]:
    """(from_date, to_date) as ISO dates — to_date is today (US Eastern)."""
    to_d = _et_today()
    return (to_d - timedelta(days=_DATE_LOOKBACK_DAYS)).isoformat(), to_d.isoformat()


def _substitute_ticker(value: Any, ticker: str) -> Any:
    if isinstance(value, str):
        v = value.replace(_TICKER_PLACEHOLDER, ticker)
        if "{FROM_DATE}" in v or "{TO_DATE}" in v or "{FROM_DATE_INTRADAY}" in v:
            from_d, to_d = _date_window()
            intraday_from = (_et_today() - timedelta(days=_INTRADAY_LOOKBACK_DAYS)).isoformat()
            v = (v.replace("{FROM_DATE_INTRADAY}", intraday_from)
                  .replace("{FROM_DATE}", from_d)
                  .replace("{TO_DATE}", to_d))
        return v
    if isinstance(value, list):
        return [_substitute_ticker(v, ticker) for v in value]
    if isinstance(value, dict):
        return {k: _substitute_ticker(v, ticker) for k, v in value.items()}
    return value


def _plan_key(entry: dict) -> str:
    """Result-slot key for a tool-plan entry.

    Defaults to the tool name, but an entry may set an explicit ``key`` so the
    SAME tool can appear multiple times under distinct slots — e.g. breakout
    calls ``chart`` twice (daily + intraday) and reads them back separately.
    """
    return str(entry.get("key") or entry["name"])


async def _execute_plan(
    registry: ToolRegistry, plan: list[dict], ticker: str
) -> dict[str, Any]:
    """Execute every planned tool call for one ticker, in parallel.

    Tool errors are captured as ``{"error": ...}`` results rather than raised,
    so one bad tool doesn't take out the per-ticker verdict.
    """

    async def _one(idx: int, entry: dict) -> tuple[str, Any]:
        name = entry["name"]
        key = _plan_key(entry)
        args = _substitute_ticker(entry.get("args") or {}, ticker)
        if not registry.has(name):
            return key, {"error": f"unknown tool {name!r}"}
        try:
            return key, await registry.call(name, args)
        except Exception as exc:  # noqa: BLE001 — keep one bad tool from killing the ticker
            return key, {"error": str(exc)}

    pairs = await asyncio.gather(*(_one(i, e) for i, e in enumerate(plan)))
    results: dict[str, Any] = {}
    for key, result in pairs:
        # Keyed by slot, so the same tool under two slots (e.g. chart daily +
        # intraday) both survive; a repeated slot lets the later win.
        results[key] = result
    return results


_BATCH_TICKER_SYSTEM = """You are evaluating SEVERAL tickers against ONE \
screening prompt.

You receive:
  - The screening prompt
  - A planner brief on what to check
  - For EACH ticker: its symbol and pre-fetched tool data
  - Optional market-wide data shared across all tickers

Evaluate EACH ticker INDEPENDENTLY. Judge each ticker ONLY on its own \
pre-fetched data and the shared market-wide data — never let one ticker's \
findings leak into another's verdict.

Respond with ONLY this JSON (no markdown, no commentary):
{
  "verdicts": [
    {
      "ticker": "<symbol>",
      "triggered_for_ticker": true | false,
      "key_findings": "<1-3 sentences citing concrete data points (scores, headlines, prices)>",
      "confidence": "high" | "medium" | "low"
    }
  ]
}

Rules:
- Output EXACTLY ONE verdict object per ticker provided. Do not skip any ticker.
- Be CONSERVATIVE: triggered_for_ticker=true only when that ticker's data \
clearly supports it.
- Cite concrete evidence (numbers, headlines, scores). Never speculate.
- If a ticker's data is empty or inconclusive, triggered_for_ticker=false and \
say so in its key_findings.
- Cap each key_findings at ~400 characters.
"""


def _format_tool_data(
    data: dict[str, Any],
    *,
    header: str | None = None,
    max_chars: int = _MAX_TOOL_RESULT_CHARS,
) -> str:
    if not data:
        return ""
    lines: list[str] = []
    if header:
        lines.append(header)
    for name, result in data.items():
        try:
            payload = json.dumps(result, default=str)
        except Exception:
            payload = repr(result)
        if len(payload) > max_chars:
            payload = payload[: max_chars - 1] + "..."
        lines.append(f"=== {name} ===\n{payload}")
    return "\n\n".join(lines)


async def _evaluate_ticker_batch(
    client: httpx.AsyncClient,
    *,
    base_url: str,
    model: str,
    prompt: str,
    tickers: list[str],
    per_ticker_brief: str,
    per_ticker_data_map: dict[str, dict[str, Any]],
    shared_data: dict[str, Any],
    context_addon: str,
    eval_focus: str = "",
    computed_map: dict[str, str] | None = None,
    language: str = "en",
) -> list[dict]:
    """Evaluate a batch of tickers in a single LLM call.

    Each ticker's pre-fetched tool data is laid out in its own labelled block;
    the model is instructed to judge each independently. Returns one verdict
    per ticker (defaults filled for any the model omits).

    ``eval_focus`` (skill path) appends intent-specific judging guidance to the
    canonical evaluator system prompt — the JSON output contract stays defined
    in one place. ``computed_map`` carries the deterministic analytics facts
    (pct_from_high, sentiment aggregates, …) so the model reasons over computed
    numbers, not just raw tool dumps.
    """
    system = _BATCH_TICKER_SYSTEM
    if eval_focus:
        system = f"{_BATCH_TICKER_SYSTEM}\n\n## Skill focus\n{eval_focus}"
    system += language_instruction(language)
    computed_map = computed_map or {}
    user_parts = [
        f"TODAY'S DATE: {_today_str()}",
        f"SCREENING PROMPT:\n{prompt}",
        f"PLANNER BRIEF:\n{per_ticker_brief or '(none)'}",
        f"TICKERS TO EVALUATE ({len(tickers)}): {', '.join(tickers)}",
    ]
    for ticker in tickers:
        block = _format_tool_data(
            per_ticker_data_map.get(ticker) or {},
            max_chars=_BATCH_PER_TOOL_CHARS,
        )
        computed = computed_map.get(ticker)
        prefix = f"COMPUTED METRICS: {computed}\n" if computed else ""
        user_parts.append(
            f"----- TICKER {ticker} DATA -----\n{prefix}{block or '(no data returned)'}"
        )
    shared_block = _format_tool_data(shared_data)
    if shared_block:
        user_parts.append(
            f"MARKET-WIDE DATA (shared across all tickers):\n{shared_block}"
        )
    if context_addon:
        user_parts.append(f"CONTEXT:\n{context_addon}")
    user_parts.append(
        "Return the JSON object with one verdict per ticker now."
    )
    raw = await simple_chat(
        client,
        base_url=base_url,
        model=model,
        system=system,
        user="\n\n".join(user_parts),
        request_format="json",
        label=f"Batch eval [{', '.join(tickers)}]",
    )
    return _parse_batch_verdicts(raw, tickers)


def _parse_batch_verdicts(raw: str, tickers: list[str]) -> list[dict]:
    """Parse a batched eval response into one verdict per requested ticker.

    Matches returned verdicts to requested tickers by symbol so order/omissions
    don't misalign results. Any ticker the model skipped gets a low-confidence
    not-triggered placeholder, so a partial response never drops a ticker.
    """
    raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        log.warning(
            "Batch eval [%s]: non-JSON response, head=%r",
            ", ".join(tickers), raw[:200],
        )
        return [_failed_verdict(t, "Batch evaluation failed to parse.") for t in tickers]

    raw_verdicts = data.get("verdicts") if isinstance(data, dict) else None
    if not isinstance(raw_verdicts, list):
        # Tolerate a model that returned a bare list, or a single object.
        if isinstance(data, list):
            raw_verdicts = data
        elif isinstance(data, dict) and "ticker" in data:
            raw_verdicts = [data]
        else:
            raw_verdicts = []

    by_symbol: dict[str, dict] = {}
    for entry in raw_verdicts:
        if not isinstance(entry, dict):
            continue
        sym = str(entry.get("ticker") or "").strip().upper()
        if sym:
            by_symbol[sym] = _normalize_verdict(entry, sym)

    out: list[dict] = []
    missing: list[str] = []
    for t in tickers:
        v = by_symbol.get(t.upper())
        if v is None:
            missing.append(t)
            out.append(_failed_verdict(t, "No verdict returned for this ticker."))
        else:
            out.append(v)
    if missing:
        log.warning(
            "Batch eval [%s]: model omitted %d ticker(s): %s",
            ", ".join(tickers), len(missing), missing,
        )
    return out


def _normalize_verdict(data: dict, ticker: str) -> dict:
    """Coerce a raw verdict dict into the canonical per-ticker verdict shape."""
    return {
        "ticker": str(data.get("ticker") or ticker).upper(),
        "triggered_for_ticker": bool(data.get("triggered_for_ticker")),
        "key_findings": str(data.get("key_findings") or "").strip()[:600],
        "confidence": str(data.get("confidence") or "low").strip().lower(),
    }


def _failed_verdict(ticker: str, reason: str) -> dict:
    return {
        "ticker": ticker.upper(),
        "triggered_for_ticker": False,
        "key_findings": reason,
        "confidence": "low",
    }


# ── Stage 3: conclude ───────────────────────────────────────────────────────


_CONCLUDE_SYSTEM = """You are synthesising a multi-ticker screening result \
from per-ticker verdicts.

You receive:
  - The original screening prompt
  - An optional user-set trigger condition (the ONLY gate when present)
  - One verdict per ticker, already evaluated against the prompt

Your job: decide the overall {triggered, summary}.

Respond with ONLY this JSON (no markdown):
{
  "triggered": true | false,
  "summary": "<2-3 sentences for a Telegram alert. Name the triggered tickers and cite the strongest evidence. Mention non-triggers only if they add context.>" | null
}

Rules:
- If a trigger condition is set, it is the ONLY gate: triggered=true ONLY when \
the condition is clearly satisfied by the verdicts. Set summary=null when not.
- If no trigger condition, triggered=true when at least one ticker's verdict \
warrants action.
- Keep the summary tight — a swing trader scans this on mobile.
"""


async def _conclude(
    client: httpx.AsyncClient,
    *,
    base_url: str,
    model: str,
    prompt: str,
    trigger_condition: str | None,
    verdicts: list[dict],
    context_addon: str,
    conclude_hint: str = "",
    language: str = "en",
) -> dict:
    verdict_lines = [
        f"- {v['ticker']}: triggered={v['triggered_for_ticker']} "
        f"confidence={v['confidence']} — {v['key_findings']}"
        for v in verdicts
    ]
    user_parts = [
        f"TODAY'S DATE: {_today_str()}",
        f"SCREENING PROMPT:\n{prompt}",
        f"PER-TICKER VERDICTS ({len(verdicts)}):\n" + "\n".join(verdict_lines),
    ]
    if trigger_condition:
        user_parts.append(f"TRIGGER CONDITION (the only gate):\n{trigger_condition}")
    if conclude_hint:
        user_parts.append(f"SYNTHESIS GUIDANCE:\n{conclude_hint}")
    if context_addon:
        user_parts.append(f"CONTEXT:\n{context_addon}")
    user_parts.append("Return the JSON conclusion now.")
    raw = await simple_chat(
        client,
        base_url=base_url,
        model=model,
        system=_CONCLUDE_SYSTEM + language_instruction(language),
        user="\n\n".join(user_parts),
        request_format="json",
        label="Multi-ticker concluder",
    )
    return _parse_conclusion(raw)


def _parse_conclusion(raw: str) -> dict:
    raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        log.warning("Multi-ticker concluder: non-JSON, head=%r", raw[:200])
        return {"triggered": False, "summary": None}
    summary = data.get("summary")
    return {
        "triggered": bool(data.get("triggered")),
        "summary": (str(summary).strip() if summary else None),
    }


# ── Skill resolution (the optimized primary path) ───────────────────────────


def _render_metrics(sig: TickerSignal) -> str:
    """Compact one-line rendering of a TickerSignal's facts + metrics, fed to
    the per-ticker LLM evaluator so it reasons over computed numbers."""
    parts: list[str] = []
    if sig.facts:
        parts.append(sig.facts)
    if sig.metrics:
        parts.append("[" + ", ".join(f"{k}={v}" for k, v in sig.metrics.items()) + "]")
    return " ".join(parts)


async def _resolve_skill_plan(
    client: httpx.AsyncClient,
    skill: ScreeningSkill,
    registry: ToolRegistry,
    tickers: list[str],
) -> tuple[list[dict], set[str], dict[str, Any]]:
    """Turn a matched skill into a ready-to-run tool plan.

    Unlike the dynamic path there is NO planner call and NO re-plan loop: the
    plan is the skill's literal ``tool_plan``. We only (a) drop any tool the
    registry doesn't know (handles renamed/absent FMP tools cleanly) and
    (b) trial-probe just the FMP calls once to drop access-denied ones. The
    internal ``requires`` floor — checked by the caller — guarantees the plan
    never empties out, so we never need to fall back to the planner here.
    """
    plan = [e for e in skill.tool_plan if registry.has(e["name"])]
    dropped = [e["name"] for e in skill.tool_plan if not registry.has(e["name"])]
    if dropped:
        log.info("Skill %s: dropped %d unknown tool(s): %s", skill.id, len(dropped), dropped)

    unavailable: set[str] = set()
    trial_results: dict[str, Any] = {}
    fmp_entries = [e for e in plan if e["name"] not in _INTERNAL_TOOLS]
    if fmp_entries:
        t_trial = time.monotonic()
        unavailable, trial_results = await _trial_run_plan(
            registry, fmp_entries, tickers[0]
        )
        if unavailable:
            log.warning(
                "Skill %s: %d FMP tool(s) unavailable — %s (%.1fs); "
                "running on the internal floor",
                skill.id, len(unavailable), sorted(unavailable),
                time.monotonic() - t_trial,
            )
            _session_unavailable_tools.update(unavailable)
            plan = [e for e in plan if e["name"] not in unavailable]
    return plan, unavailable, trial_results


# ── Public entry point ─────────────────────────────────────────────────────


async def run_multi_ticker_async(
    *,
    prompt: str,
    tickers: list[str],
    registry: ToolRegistry,
    trigger_condition: str | None = None,
    context_addon: str = "",
    trace: RunTrace | None = None,
    language: str = "en",
) -> dict:
    """Classify → (skill recipe | dynamic plan) → fan-out per-ticker → conclude.

    Returns {triggered, summary, data_used} compatible with run_agent.

    ``trace`` (a RunTrace) records the ordered sequence of events so the run can
    be reconstructed from the DB even if it errors or times out. A fresh one is
    created when not supplied.

    A cheap classifier first tries to route the prompt to a predefined
    ``ScreeningSkill`` (services.agent.skills). On a match the skill's literal
    tool plan + deterministic analytics run as the optimized primary path,
    skipping the dynamic LLM planner entirely. Only when no skill fits (or its
    required internal tools are missing) does the run divert to the dynamic
    planner — the same plan/trial/re-plan path as before.
    """
    trace = trace or RunTrace()
    base_url = os.environ.get(_OLLAMA_URL_ENV, "http://localhost:11434").rstrip("/")
    model = (
        os.environ.get(_OLLAMA_MODEL_ENV)
        or os.environ.get("OLLAMA_BLOG_MODEL")
        or "gemma4:e4b"
    )
    log.info(
        "Multi-ticker pipeline: start — tickers=%d (%s) model=%s tools=%d has_condition=%s",
        len(tickers),
        ",".join(tickers[:10]) + ("..." if len(tickers) > 10 else ""),
        model,
        len(registry.schemas()),
        bool(trigger_condition),
    )
    trace.event(
        "run", "start", ticker_count=len(tickers),
        tickers=tickers[:25], model=model, has_condition=bool(trigger_condition),
    )

    async with httpx.AsyncClient() as client:
        t0 = time.monotonic()

        # Stage 0 — route to a predefined skill (one cheap classify call).
        skill = await classify_skill(
            client,
            base_url=base_url,
            model=model,
            prompt=prompt,
            trigger_condition=trigger_condition,
        )
        trace.event("classify", "done", skill=skill.id if skill else None)
        if skill is not None and not all(registry.has(t) for t in skill.requires):
            missing = [t for t in skill.requires if not registry.has(t)]
            log.warning(
                "Skill %s required tools missing %s — diverting to dynamic planner",
                skill.id, missing,
            )
            trace.event("classify", "skill_disqualified", skill=skill.id, missing=missing)
            skill = None

        # Per-run knobs that a skill may override (defaults = dynamic path).
        eval_focus = ""
        conclude_hint = ""
        batch_size = _BATCH_SIZE
        eff_model = model
        plan_rationale = ""

        if skill is not None:
            eff_model = skill.model or model
            batch_size = skill.batch_size or _BATCH_SIZE
            eval_focus = skill.eval_focus
            conclude_hint = skill.conclude_hint
            per_ticker_brief = f"Skill '{skill.id}': {skill.description}"
            plan_rationale = f"skill:{skill.id}"
            tool_plan, unavailable, trial_results = await _resolve_skill_plan(
                client, skill, registry, tickers
            )
            trace.event(
                "plan", "skill",
                skill=skill.id,
                tools=[e["name"] for e in tool_plan],
                fmp_unavailable=sorted(unavailable),
                batch_size=batch_size,
            )
            if not tool_plan:
                trace.event("plan", "empty_skill", skill=skill.id)
                return {
                    "triggered": False,
                    "summary": (
                        f"Skill '{skill.id}' had no runnable tools "
                        "(all unavailable); nothing to evaluate."
                    ),
                    "data_used": {
                        "skill": skill.id,
                        "unavailable_tools": sorted(unavailable),
                        "ticker_count": len(tickers),
                    },
                }
        else:
            # ── Dynamic planner path (fallback) ──
            # Stage 1 — plan
            try:
                plan = await asyncio.wait_for(
                    _plan_tools(
                        client,
                        base_url=base_url,
                        model=model,
                        prompt=prompt,
                        tickers=tickers,
                        registry=registry,
                        context_addon=context_addon,
                    ),
                    timeout=_PLAN_TIMEOUT,
                )
            except asyncio.TimeoutError:
                log.error("Multi-ticker plan timed out after %.0fs", _PLAN_TIMEOUT)
                trace.event("plan", "timeout", timeout_s=_PLAN_TIMEOUT)
                return {
                    "triggered": False,
                    "summary": "Planner timed out before producing a plan.",
                    "data_used": {"error": "plan_timeout", "ticker_count": len(tickers)},
                }
            tool_plan = plan["tool_plan"]
            per_ticker_brief = plan["per_ticker_brief"]
            plan_rationale = plan["rationale"]
            trace.event("plan", "dynamic_done", tools=[e["name"] for e in tool_plan])
            if not tool_plan:
                log.warning(
                    "Multi-ticker plan: empty — falling back to default per-ticker tool set"
                )
                trace.event("plan", "fallback_default")
                plan = _default_fallback_plan(registry)
                tool_plan = plan["tool_plan"]
                per_ticker_brief = plan["per_ticker_brief"]
                plan_rationale = plan["rationale"]
                if not tool_plan:
                    # The registry didn't even have the basics — give up.
                    return {
                        "triggered": False,
                        "summary": "Planner returned no plan and registry has no fallback tools.",
                        "data_used": {
                            "plan": plan,
                            "verdicts": [],
                            "ticker_count": len(tickers),
                            "triggered_count": 0,
                        },
                    }
            # Stage 1.5 — trial run: probe every unique planned tool against the
            # first ticker to verify it's actually available under the current API
            # plan. Drop any that fail and, if the plan empties out, re-plan once
            # with the excluded list before falling back to "nothing to evaluate".
            probe_ticker = tickers[0]
            t_trial = time.monotonic()
            unavailable, trial_results = await _trial_run_plan(
                registry, tool_plan, probe_ticker
            )
            if unavailable:
                log.warning(
                    "Trial run: %d tool(s) unavailable on probe ticker %s — %s (%.1fs)",
                    len(unavailable),
                    probe_ticker,
                    sorted(unavailable),
                    time.monotonic() - t_trial,
                )
                trace.event("trial", "unavailable", tools=sorted(unavailable))
                _session_unavailable_tools.update(unavailable)
                survived = [e for e in tool_plan if e["name"] not in unavailable]
                if survived:
                    tool_plan = survived
                else:
                    log.info(
                        "Trial run dropped every planned tool — re-planning with "
                        "EXCLUDED hint"
                    )
                    try:
                        plan = await asyncio.wait_for(
                            _plan_tools(
                                client,
                                base_url=base_url,
                                model=model,
                                prompt=prompt,
                                tickers=tickers,
                                registry=registry,
                                context_addon=context_addon,
                                excluded_tools=unavailable,
                            ),
                            timeout=_PLAN_TIMEOUT,
                        )
                        tool_plan = [
                            e for e in plan["tool_plan"]
                            if e["name"] not in unavailable
                        ]
                        per_ticker_brief = plan["per_ticker_brief"]
                        plan_rationale = plan["rationale"]
                    except asyncio.TimeoutError:
                        log.error(
                            "Re-plan timed out — falling back to default plan"
                        )
                        plan = _default_fallback_plan(registry)
                        tool_plan = [
                            e for e in plan["tool_plan"]
                            if e["name"] not in unavailable
                        ]
                        per_ticker_brief = plan["per_ticker_brief"]
                        plan_rationale = plan["rationale"]

                    if tool_plan:
                        extra_unavail, extra_results = await _trial_run_plan(
                            registry, tool_plan, probe_ticker
                        )
                        if extra_unavail:
                            log.warning(
                                "Re-plan trial flagged %d more unavailable: %s",
                                len(extra_unavail),
                                sorted(extra_unavail),
                            )
                            _session_unavailable_tools.update(extra_unavail)
                            tool_plan = [
                                e for e in tool_plan
                                if e["name"] not in extra_unavail
                            ]
                            unavailable |= extra_unavail
                        trial_results.update(extra_results)

                    if not tool_plan:
                        trace.event("plan", "all_unavailable", tools=sorted(unavailable))
                        return {
                            "triggered": False,
                            "summary": (
                                "Trial run: every planned tool is unavailable "
                                "under the current data plan; nothing to evaluate."
                            ),
                            "data_used": {
                                "unavailable_tools": sorted(unavailable),
                                "ticker_count": len(tickers),
                                "rationale": plan_rationale,
                            },
                        }
            else:
                log.info(
                    "Trial run: all %d tool(s) available on probe ticker %s (%.1fs)",
                    len(trial_results),
                    probe_ticker,
                    time.monotonic() - t_trial,
                )

            # Always include the latest ticker articles in the per-ticker context,
            # even if the planner didn't pick get_ticker_news. News impact is the
            # core thesis of the screener — the per-ticker evaluator should never
            # have to guess from sentiment scores alone when the headlines are
            # one tool call away.
            tool_plan = _ensure_latest_news_in_plan(tool_plan, registry)

        per_ticker_plan, shared_plan = _split_plan(tool_plan)
        log.info(
            "Multi-ticker plan: skill=%s %d tool(s) (%d per-ticker, %d shared) — "
            "names=%s brief=%r rationale=%r batch_size=%d (%.1fs to resolve)",
            skill.id if skill else None,
            len(tool_plan),
            len(per_ticker_plan),
            len(shared_plan),
            [t["name"] for t in tool_plan],
            per_ticker_brief[:120],
            plan_rationale[:120],
            batch_size,
            time.monotonic() - t0,
        )
        trace.event(
            "plan", "resolved",
            per_ticker_tools=[t["name"] for t in per_ticker_plan],
            shared_tools=[t["name"] for t in shared_plan],
            batch_size=batch_size,
        )

        # Stage 2 — execute shared (market-wide) tools ONCE, then fan out per
        # ticker. Reuse any successful trial-run results to avoid re-executing
        # the same call we just made during validation.
        shared_data: dict[str, Any] = {}
        if shared_plan:
            cached_shared: dict[str, Any] = {}
            missing_shared: list[dict] = []
            for entry in shared_plan:
                name = entry["name"]
                cached = trial_results.get(name)
                if cached is not None and not _result_unavailable(cached):
                    cached_shared[name] = cached
                else:
                    missing_shared.append(entry)
            if missing_shared:
                t_shared = time.monotonic()
                executed = await _execute_plan(
                    registry, missing_shared, ticker="N/A"
                )
                log.info(
                    "Multi-ticker shared tools done: %s "
                    "(%d reused from trial, %d freshly executed, %.1fs)",
                    list(cached_shared.keys()) + list(executed.keys()),
                    len(cached_shared),
                    len(executed),
                    time.monotonic() - t_shared,
                )
                shared_data = {**cached_shared, **executed}
            else:
                shared_data = cached_shared
                log.info(
                    "Multi-ticker shared tools: %d reused from trial run",
                    len(cached_shared),
                )

        if shared_plan:
            shared_errors = [n for n, r in shared_data.items() if _result_unavailable(r)
                             or (isinstance(r, dict) and "error" in r)]
            trace.event("shared", "done", tools=list(shared_data.keys()),
                        errors=shared_errors)

        # Group tickers into mini-batches so each LLM eval call covers several
        # tickers — the key lever for large screenings (N calls → ceil(N/B)).
        # Tool fetches still run per ticker; only the evaluation is batched.
        batches = [
            tickers[i : i + batch_size]
            for i in range(0, len(tickers), batch_size)
        ]
        sem = asyncio.Semaphore(_TICKER_CONCURRENCY)
        # Track how the deterministic layer split the work, for observability.
        decided_total = 0
        escalated_total = 0

        async def _process_batch(batch: list[str]) -> list[dict]:
            nonlocal decided_total, escalated_total
            async with sem:
                started = time.monotonic()
                try:
                    # FETCH — every ticker's per-ticker tools, concurrently.
                    if per_ticker_plan:
                        datas = await asyncio.gather(
                            *(_execute_plan(registry, per_ticker_plan, t) for t in batch)
                        )
                        per_ticker_data_map = dict(zip(batch, datas))
                    else:
                        per_ticker_data_map = {t: {} for t in batch}

                    # Record any per-ticker tool fetch errors (incl. FMP
                    # access-denied), so a thin/empty evaluation is explainable.
                    for t in batch:
                        for name, res in (per_ticker_data_map.get(t) or {}).items():
                            if _result_unavailable(res) or (isinstance(res, dict) and "error" in res):
                                err = res.get("error") if isinstance(res, dict) else "unavailable"
                                trace.event("fetch", "tool_error", ticker=t, tool=name,
                                            error=str(err)[:200])

                    # COMPUTE — deterministic analytics (skill path only).
                    # Conclusive signals become verdicts with no LLM cost; only
                    # the ambiguous/qualitative ones are escalated to the model.
                    decided: list[dict] = []
                    escalate: list[str] = []
                    computed_map: dict[str, str] = {}
                    if skill is not None:
                        for t in batch:
                            try:
                                sig = skill.analytics(t, per_ticker_data_map.get(t) or {})
                            except Exception as exc:  # noqa: BLE001
                                log.warning("Skill %s analytics(%s) failed: %s", skill.id, t, exc)
                                trace.event("analytics", "error", ticker=t, error=str(exc)[:200])
                                sig = TickerSignal.escalate(t, facts=f"analytics error: {exc}")
                            computed_map[t] = _render_metrics(sig)
                            if sig.needs_llm:
                                escalate.append(t)
                                trace.event("analytics", "escalate", ticker=t, metrics=sig.metrics)
                            else:
                                decided.append(sig.to_verdict())
                                trace.event("analytics", "decided", ticker=t,
                                            verdict=sig.verdict, metrics=sig.metrics)
                    else:
                        escalate = list(batch)
                        trace.event("analytics", "skipped_no_skill", tickers=batch)
                    decided_total += len(decided)
                    escalated_total += len(escalate)

                    # JUDGE — one LLM eval call for the escalated subset only.
                    llm_verdicts: list[dict] = []
                    if escalate:
                        trace.event("eval", "start", tickers=escalate)
                        llm_verdicts = await asyncio.wait_for(
                            _evaluate_ticker_batch(
                                client,
                                base_url=base_url,
                                model=eff_model,
                                prompt=prompt,
                                tickers=escalate,
                                per_ticker_brief=per_ticker_brief,
                                per_ticker_data_map=per_ticker_data_map,
                                shared_data=shared_data,
                                context_addon=context_addon,
                                eval_focus=eval_focus,
                                computed_map=computed_map,
                                language=language,
                            ),
                            timeout=_BATCH_EVAL_TIMEOUT,
                        )
                        trace.event("eval", "done", tickers=escalate,
                                    triggered=sum(1 for v in llm_verdicts
                                                  if v["triggered_for_ticker"]))

                    # Merge decided + LLM verdicts, preserving batch order.
                    by_sym = {v["ticker"]: v for v in (decided + llm_verdicts)}
                    verdicts = [
                        by_sym.get(t.upper())
                        or _failed_verdict(t, "No verdict produced for this ticker.")
                        for t in batch
                    ]
                    trig = sum(1 for v in verdicts if v["triggered_for_ticker"])
                    log.info(
                        "Multi-ticker batch [%s]: %d/%d triggered "
                        "(%d decided deterministically, %d via LLM) in %.1fs",
                        ", ".join(batch), trig, len(batch),
                        len(decided), len(escalate),
                        time.monotonic() - started,
                    )
                    return verdicts
                except Exception as exc:  # noqa: BLE001
                    log.warning(
                        "Multi-ticker batch [%s]: evaluation failed: %s",
                        ", ".join(batch), exc,
                    )
                    trace.event("eval", "batch_failed", tickers=batch,
                                error=f"{type(exc).__name__}: {str(exc)[:200]}")
                    return [
                        _failed_verdict(t, f"Evaluation failed: {exc}")
                        for t in batch
                    ]

        t1 = time.monotonic()
        batch_results = await asyncio.gather(
            *(_process_batch(b) for b in batches)
        )
        verdicts = [v for batch in batch_results for v in batch]
        triggered_count = sum(1 for v in verdicts if v["triggered_for_ticker"])
        log.info(
            "Multi-ticker stage 2 done: %d/%d triggered across %d batch(es) "
            "of <=%d (%d decided deterministically, %d escalated to LLM, "
            "concurrency=%d, %.1fs)",
            triggered_count,
            len(verdicts),
            len(batches),
            batch_size,
            decided_total,
            escalated_total,
            _TICKER_CONCURRENCY,
            time.monotonic() - t1,
        )
        trace.event("stage2", "done", decided=decided_total,
                    escalated=escalated_total, triggered=triggered_count,
                    batches=len(batches))

        # Stage 3 — conclude (only sees compact verdicts, not raw tool data)
        t2 = time.monotonic()
        try:
            conclusion = await asyncio.wait_for(
                _conclude(
                    client,
                    base_url=base_url,
                    model=eff_model,
                    prompt=prompt,
                    trigger_condition=trigger_condition,
                    verdicts=verdicts,
                    context_addon=context_addon,
                    conclude_hint=conclude_hint,
                    language=language,
                ),
                timeout=_CONCLUDE_TIMEOUT,
            )
            trace.event("conclude", "done", triggered=conclusion["triggered"],
                        summary_len=len(conclusion.get("summary") or ""))
        except asyncio.TimeoutError:
            log.error(
                "Multi-ticker concluder timed out after %.0fs", _CONCLUDE_TIMEOUT
            )
            trace.event("conclude", "timeout", timeout_s=_CONCLUDE_TIMEOUT)
            conclusion = {"triggered": False, "summary": None}
        log.info(
            "Multi-ticker pipeline: done — triggered=%s summary_len=%d (%.1fs)",
            conclusion["triggered"],
            len((conclusion["summary"] or "")),
            time.monotonic() - t2,
        )

    return {
        "triggered": conclusion["triggered"],
        "summary": conclusion["summary"],
        "data_used": {
            "skill": skill.id if skill else None,
            "plan": {
                "tools": [t["name"] for t in tool_plan],
                "args_templates": [t["args"] for t in tool_plan],
                "per_ticker_tools": [t["name"] for t in per_ticker_plan],
                "shared_tools": [t["name"] for t in shared_plan],
                "per_ticker_brief": per_ticker_brief,
                "rationale": plan_rationale,
                "unavailable_tools": sorted(unavailable),
            },
            "verdicts": verdicts,
            "ticker_count": len(tickers),
            "triggered_count": triggered_count,
            "decided_count": decided_total,
            "escalated_count": escalated_total,
            "batch_size": batch_size,
            "batch_count": len(batches),
        },
    }
