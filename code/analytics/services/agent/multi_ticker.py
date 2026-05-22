"""
multi_ticker.py — fan-out screening pipeline.

When a screening has >= 2 tickers in scope, route here instead of the single
agentic loop. Three isolated LLM contexts:

  Stage 1 (plan):       one call sees the full tool catalog and decides which
                        tools to invoke per ticker, with the literal "{TICKER}"
                        as a placeholder.
  Stage 2 (per-ticker): for each ticker, execute the planned tools (parallel
                        within a ticker), then a focused single-shot LLM call
                        reads {prompt, ticker, tool data} and emits a verdict.
                        Bounded concurrency at the ticker level. Each ticker
                        gets a fresh context — tool output from ticker A never
                        enters ticker B's prompt.
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
from typing import Any

import httpx

from services.agent_core import ToolRegistry, simple_chat

from .fmp_tools import looks_like_access_denied

log = logging.getLogger(__name__)

_OLLAMA_URL_ENV = "OLLAMA_BASE_URL"
_OLLAMA_MODEL_ENV = "OLLAMA_TIKTOK_MODEL"

_TICKER_CONCURRENCY = int(os.environ.get("AGENT_MULTI_TICKER_CONCURRENCY", "3"))
_PER_TICKER_TIMEOUT = float(os.environ.get("AGENT_PER_TICKER_TIMEOUT", "60"))
_PLAN_TIMEOUT = float(os.environ.get("AGENT_PLAN_TIMEOUT", "90"))
_CONCLUDE_TIMEOUT = float(os.environ.get("AGENT_CONCLUDE_TIMEOUT", "60"))

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


def _substitute_ticker(value: Any, ticker: str) -> Any:
    if isinstance(value, str):
        return value.replace(_TICKER_PLACEHOLDER, ticker)
    if isinstance(value, list):
        return [_substitute_ticker(v, ticker) for v in value]
    if isinstance(value, dict):
        return {k: _substitute_ticker(v, ticker) for k, v in value.items()}
    return value


async def _execute_plan(
    registry: ToolRegistry, plan: list[dict], ticker: str
) -> dict[str, Any]:
    """Execute every planned tool call for one ticker, in parallel.

    Tool errors are captured as ``{"error": ...}`` results rather than raised,
    so one bad tool doesn't take out the per-ticker verdict.
    """

    async def _one(idx: int, entry: dict) -> tuple[str, Any]:
        name = entry["name"]
        args = _substitute_ticker(entry.get("args") or {}, ticker)
        if not registry.has(name):
            return name, {"error": f"unknown tool {name!r}"}
        try:
            return name, await registry.call(name, args)
        except Exception as exc:  # noqa: BLE001 — keep one bad tool from killing the ticker
            return name, {"error": str(exc)}

    pairs = await asyncio.gather(*(_one(i, e) for i, e in enumerate(plan)))
    results: dict[str, Any] = {}
    for name, result in pairs:
        # If the planner picked the same tool twice (rare), the later wins.
        results[name] = result
    return results


_PER_TICKER_SYSTEM = """You are evaluating ONE ticker against a screening prompt.

You receive:
  - The screening prompt
  - The ticker
  - A planner brief on what to check
  - Pre-fetched tool data for this ticker (and optional market-wide data)

Your job: decide whether THIS TICKER satisfies the screening prompt and write \
a short evidence-based verdict.

Respond with ONLY this JSON (no markdown, no commentary):
{
  "ticker": "<symbol>",
  "triggered_for_ticker": true | false,
  "key_findings": "<1-3 sentences citing concrete data points (scores, headlines, prices)>",
  "confidence": "high" | "medium" | "low"
}

Rules:
- Be CONSERVATIVE: triggered_for_ticker=true only when the data clearly supports it.
- Cite concrete evidence (numbers, headlines, scores). Never speculate.
- If the pre-fetched data is empty or inconclusive, triggered_for_ticker=false \
and say so in key_findings.
- Cap key_findings at ~400 characters.
"""


def _format_tool_data(data: dict[str, Any], *, header: str | None = None) -> str:
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
        if len(payload) > _MAX_TOOL_RESULT_CHARS:
            payload = payload[: _MAX_TOOL_RESULT_CHARS - 1] + "..."
        lines.append(f"=== {name} ===\n{payload}")
    return "\n\n".join(lines)


async def _evaluate_ticker(
    client: httpx.AsyncClient,
    *,
    base_url: str,
    model: str,
    prompt: str,
    ticker: str,
    per_ticker_brief: str,
    per_ticker_data: dict[str, Any],
    shared_data: dict[str, Any],
    context_addon: str,
) -> dict:
    user_parts = [
        f"SCREENING PROMPT:\n{prompt}",
        f"TICKER: {ticker}",
        f"PLANNER BRIEF:\n{per_ticker_brief or '(none)'}",
    ]
    per_ticker_block = _format_tool_data(per_ticker_data)
    if per_ticker_block:
        user_parts.append(f"PER-TICKER DATA:\n{per_ticker_block}")
    shared_block = _format_tool_data(shared_data)
    if shared_block:
        user_parts.append(f"MARKET-WIDE DATA (shared across all tickers):\n{shared_block}")
    if context_addon:
        user_parts.append(f"CONTEXT:\n{context_addon}")
    user_parts.append("Return the JSON verdict for this ticker now.")
    raw = await simple_chat(
        client,
        base_url=base_url,
        model=model,
        system=_PER_TICKER_SYSTEM,
        user="\n\n".join(user_parts),
        request_format="json",
        label=f"Per-ticker {ticker}",
    )
    return _parse_verdict(raw, ticker)


def _parse_verdict(raw: str, ticker: str) -> dict:
    raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        log.warning("Per-ticker %s: non-JSON verdict, head=%r", ticker, raw[:200])
        return {
            "ticker": ticker,
            "triggered_for_ticker": False,
            "key_findings": "Evaluation failed to parse a verdict.",
            "confidence": "low",
        }
    return {
        "ticker": str(data.get("ticker") or ticker).upper(),
        "triggered_for_ticker": bool(data.get("triggered_for_ticker")),
        "key_findings": str(data.get("key_findings") or "").strip()[:600],
        "confidence": str(data.get("confidence") or "low").strip().lower(),
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
) -> dict:
    verdict_lines = [
        f"- {v['ticker']}: triggered={v['triggered_for_ticker']} "
        f"confidence={v['confidence']} — {v['key_findings']}"
        for v in verdicts
    ]
    user_parts = [
        f"SCREENING PROMPT:\n{prompt}",
        f"PER-TICKER VERDICTS ({len(verdicts)}):\n" + "\n".join(verdict_lines),
    ]
    if trigger_condition:
        user_parts.append(f"TRIGGER CONDITION (the only gate):\n{trigger_condition}")
    if context_addon:
        user_parts.append(f"CONTEXT:\n{context_addon}")
    user_parts.append("Return the JSON conclusion now.")
    raw = await simple_chat(
        client,
        base_url=base_url,
        model=model,
        system=_CONCLUDE_SYSTEM,
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


# ── Public entry point ─────────────────────────────────────────────────────


async def run_multi_ticker_async(
    *,
    prompt: str,
    tickers: list[str],
    registry: ToolRegistry,
    trigger_condition: str | None = None,
    context_addon: str = "",
) -> dict:
    """Plan → fan-out per-ticker → conclude.

    Returns {triggered, summary, data_used} compatible with run_agent.
    """
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

    async with httpx.AsyncClient() as client:
        # Stage 1 — plan
        t0 = time.monotonic()
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
            return {
                "triggered": False,
                "summary": "Planner timed out before producing a plan.",
                "data_used": {"error": "plan_timeout", "ticker_count": len(tickers)},
            }
        tool_plan = plan["tool_plan"]
        per_ticker_brief = plan["per_ticker_brief"]
        if not tool_plan:
            log.warning(
                "Multi-ticker plan: empty — falling back to default per-ticker tool set"
            )
            plan = _default_fallback_plan(registry)
            tool_plan = plan["tool_plan"]
            per_ticker_brief = plan["per_ticker_brief"]
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
                    return {
                        "triggered": False,
                        "summary": (
                            "Trial run: every planned tool is unavailable "
                            "under the current data plan; nothing to evaluate."
                        ),
                        "data_used": {
                            "unavailable_tools": sorted(unavailable),
                            "ticker_count": len(tickers),
                            "rationale": plan["rationale"],
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
            "Multi-ticker plan: %d tool(s) (%d per-ticker, %d shared) — names=%s brief=%r rationale=%r (%.1fs total to plan+trial)",
            len(tool_plan),
            len(per_ticker_plan),
            len(shared_plan),
            [t["name"] for t in tool_plan],
            per_ticker_brief[:120],
            plan["rationale"][:120],
            time.monotonic() - t0,
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

        sem = asyncio.Semaphore(_TICKER_CONCURRENCY)

        async def _process_ticker(ticker: str) -> dict:
            async with sem:
                started = time.monotonic()
                try:
                    per_ticker_data = (
                        await _execute_plan(registry, per_ticker_plan, ticker)
                        if per_ticker_plan
                        else {}
                    )
                    verdict = await asyncio.wait_for(
                        _evaluate_ticker(
                            client,
                            base_url=base_url,
                            model=model,
                            prompt=prompt,
                            ticker=ticker,
                            per_ticker_brief=per_ticker_brief,
                            per_ticker_data=per_ticker_data,
                            shared_data=shared_data,
                            context_addon=context_addon,
                        ),
                        timeout=_PER_TICKER_TIMEOUT,
                    )
                    log.info(
                        "Multi-ticker %s: triggered=%s conf=%s in %.1fs",
                        ticker,
                        verdict["triggered_for_ticker"],
                        verdict["confidence"],
                        time.monotonic() - started,
                    )
                    return verdict
                except Exception as exc:  # noqa: BLE001
                    log.warning(
                        "Multi-ticker %s: evaluation failed: %s", ticker, exc
                    )
                    return {
                        "ticker": ticker,
                        "triggered_for_ticker": False,
                        "key_findings": f"Evaluation failed: {exc}",
                        "confidence": "low",
                    }

        t1 = time.monotonic()
        verdicts = await asyncio.gather(*(_process_ticker(t) for t in tickers))
        triggered_count = sum(1 for v in verdicts if v["triggered_for_ticker"])
        log.info(
            "Multi-ticker stage 2 done: %d/%d triggered per-ticker (%.1fs)",
            triggered_count,
            len(verdicts),
            time.monotonic() - t1,
        )

        # Stage 3 — conclude (only sees compact verdicts, not raw tool data)
        t2 = time.monotonic()
        try:
            conclusion = await asyncio.wait_for(
                _conclude(
                    client,
                    base_url=base_url,
                    model=model,
                    prompt=prompt,
                    trigger_condition=trigger_condition,
                    verdicts=verdicts,
                    context_addon=context_addon,
                ),
                timeout=_CONCLUDE_TIMEOUT,
            )
        except asyncio.TimeoutError:
            log.error(
                "Multi-ticker concluder timed out after %.0fs", _CONCLUDE_TIMEOUT
            )
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
            "plan": {
                "tools": [t["name"] for t in tool_plan],
                "args_templates": [t["args"] for t in tool_plan],
                "per_ticker_tools": [t["name"] for t in per_ticker_plan],
                "shared_tools": [t["name"] for t in shared_plan],
                "per_ticker_brief": per_ticker_brief,
                "rationale": plan["rationale"],
                "unavailable_tools": sorted(unavailable),
            },
            "verdicts": verdicts,
            "ticker_count": len(tickers),
            "triggered_count": triggered_count,
        },
    }
