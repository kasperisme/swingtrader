"""Podcast research agent.

Replaces fetch_live_data()'s parallel-fetch-everything strategy with an
agentic loop using the shared services.agent_core stack.

Tools available to the agent:
- The full base market registry (cluster trends, dimension trends, ticker
  sentiment, top articles, ticker relationships, company vectors, ticker
  news, semantic search, fetch_url).
- Podcast-specific aggregate fetchers (regime/breadth, VIX, top news of
  the day, watchlist setups, earnings, insider activity, 24h news stats).

Output schema matches data_fetcher.fetch_live_data() so the script-writer
template doesn't change. On total Ollama failure the gather falls back to
fetch_live_data() unless PODCAST_RESEARCH_FALLBACK_ON_FAILURE=false.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import date
from typing import Any

import httpx

from services.agent_core import (
    ToolRegistry,
    build_market_registry,
    run_tool_loop,
)

from .config import OLLAMA_BASE_URL, OLLAMA_PODCAST_SCRIPT_MODEL
from .data_fetcher import (
    _fetch_earnings,
    _fetch_insider,
    _fetch_news_24h_stats,
    _fetch_regime_and_breadth,
    _fetch_top_news,
    _fetch_vix,
    _fetch_watchlist,
    session_meta,
)

log = logging.getLogger(__name__)


PODCAST_RESEARCH_MAX_ROUNDS = int(os.environ.get("PODCAST_RESEARCH_MAX_ROUNDS", "12"))

# When the agent path fails (e.g. Ollama Cloud 502 after ~60s on tool calls),
# fall back to parallel fetch_live_data() so the episode can still render.
# Set to "false" to surface errors instead.
PODCAST_RESEARCH_FALLBACK_ON_FAILURE = (
    os.environ.get("PODCAST_RESEARCH_FALLBACK_ON_FAILURE", "true").lower() == "true"
)

_RETRY_MAX_ATTEMPTS = max(
    1, int(os.environ.get("PODCAST_RESEARCH_OLLAMA_RETRIES", "3"))
)

# Tool-calling needs a model that supports Ollama's `tools` payload; falls
# back to the script model so single-model setups don't need extra config.
OLLAMA_PODCAST_RESEARCH_MODEL = (
    os.environ.get("OLLAMA_PODCAST_RESEARCH_MODEL")
    or os.environ.get("OLLAMA_TIKTOK_MODEL")
    or os.environ.get("OLLAMA_BLOG_MODEL")
    or OLLAMA_PODCAST_SCRIPT_MODEL
)


# ── Podcast-specific dossier tools ──────────────────────────────────────────


def _wrap_regime_breadth() -> dict:
    regime, breadth = _fetch_regime_and_breadth()
    return {"regime": regime, "breadth": breadth}


def _wrap_news_24h_stats() -> dict:
    articles, sources = _fetch_news_24h_stats()
    return {"articles_24h": articles, "sources_24h": sources}


def _build_podcast_dossier_tools() -> ToolRegistry:
    """Daily-aggregate tools that anchor each podcast act.

    Distinct from the base market registry: these return TODAY's single
    highest-impact item per category (top news, top earnings surprise, top
    insider transaction), the framing aggregates (regime, breadth, VIX),
    and the cold-open hook stats (24h article/source counts).
    """
    r = ToolRegistry()
    r.add_function(
        "get_market_regime_and_breadth",
        _wrap_regime_breadth,
        description=(
            "Fetch current market regime (BULLISH/BEARISH/CAUTIOUS, days_in_regime) "
            "and breadth (% of stocks above 50/200-day MA). Foundation for the "
            "MARKET REGIME BRIEFING act — almost always worth calling."
        ),
    )
    r.add_function(
        "get_vix",
        _fetch_vix,
        description=(
            "Fetch current VIX level + day-over-day change. Skip unless today's "
            "reading is genuinely notable (extreme level or large move)."
        ),
    )

    r.add_function(
        "get_top_news",
        _fetch_top_news,
        description=(
            "Today's highest-impact news article (ticker, headline, impact_score 0–10, "
            "factor_summary). The TOP STORY DEEP DIVE act is built on this — call once."
        ),
    )
    r.add_function(
        "get_watchlist_setups",
        _fetch_watchlist,
        description=(
            "Current swing trade setups (RS rank, stage, % from pivot, setup_type). "
            "The WATCHLIST PULSE act is built on this — call once."
        ),
    )
    r.add_function(
        "get_earnings",
        _fetch_earnings,
        description=(
            "Today's largest earnings surprise (ticker, surprise_pct). Skip if "
            "earnings season is quiet — only worth pulling if the surprise is meaningful."
        ),
    )
    r.add_function(
        "get_insider_activity",
        _fetch_insider,
        description=(
            "Most notable insider transaction of the day (ticker, role, shares, $). "
            "Strong fit when get_top_news returns impact_score >= 8, or when the "
            "watchlist holds a stage-2 ticker that may have related insider activity."
        ),
    )
    r.add_function(
        "get_news_24h_stats",
        _wrap_news_24h_stats,
        description=(
            "Returns {articles_24h, sources_24h} — used by the cold-open hook for the "
            "'I have read N articles from M sources' clause. Always call this once."
        ),
    )
    return r


# ── System prompt ──────────────────────────────────────────────────────────


def _system_prompt(today: str, max_rounds: int) -> str:
    return f"""You are the research producer for The Impact Tape, the swing-trader podcast hosted by Hans (today: {today}).

Your job: decide which data tools to call, gather just what the script needs, then return a JSON dossier. You are NOT writing the script — a separate writer takes your dossier and produces the audio script.

# Iteration budget

You have at most {max_rounds} tool-calling rounds total before you MUST emit the final dossier JSON. Plan accordingly:
- Front-load the must-haves (regime/breadth, top news, watchlist, news_24h_stats).
- Make conditional calls only when they add real value.
- Don't call the same tool twice — repeated calls are cached anyway.
- If you're 2 rounds from the cap, stop fetching and emit the dossier.

# Section-by-section research brief

1. COLD OPEN + EXECUTIVE SUMMARY — needs the headline + the hook stats.
   • Always fetch: get_news_24h_stats, get_top_news, get_market_regime_and_breadth.

2. MARKET REGIME BRIEFING — regime + breadth are the foundation.
   • Already covered by get_market_regime_and_breadth.
   • Conditionally fetch get_vix ONLY if you have reason to suspect today's reading is notable. Default: SKIP.

3. TOP STORY DEEP DIVE — the highest-impact news.
   • Already covered by get_top_news.
   • If the top news has impact_score >= 8, ALSO call get_insider_activity — insider color often relates to the same ticker on high-impact days.

4. WATCHLIST PULSE — best setups nearing entry.
   • Always fetch: get_watchlist_setups.
   • If you spot a stage-2 ticker with RS rank >= 90 in the watchlist that has NO top-news coverage yet, get_insider_activity is worth a try (only if you haven't already called it).

5. CLOSE + THESIS — needs to know what's coming next.
   • If today is during an active earnings week, call get_earnings. Otherwise skip — earnings noise hurts more than it helps.

# Optional cross-section context tools

You also have access to the broader RAG market tools — use them ONLY when they would add real cross-section colour the writer can weave in (e.g. "the dominant theme today is rate-cut sensitivity"). Do not call these for routine dossier gathering. Available:
- search_news(query, lookback_hours, tickers, limit) — semantic search over the news index
- get_cluster_trends(hours), get_dimension_trends(hours) — themes pulsing in the news
- get_ticker_sentiment(tickers, hours), get_ticker_news(tickers, hours, per_ticker_limit)
- get_top_articles(tickers, hours, limit) — articles with full impact vectors
- get_ticker_relationships(ticker, hops), get_company_vectors(tickers)
- fetch_url(url) — read article body when the title isn't enough

# Output format

When you're done fetching, respond with ONLY a JSON object (no preamble, no markdown) matching this schema:

{{
  "research_notes": "string — 1–3 sentences of cross-section context the writer should know (e.g. 'Top news ticker NVDA also has insider buying — strengthens the deep-dive thesis.'). Empty string if no extra context."
}}

The script writer combines your tool results with this notes field automatically — you don't need to repeat raw tool data in the JSON. Just decide what to fetch, then return the notes JSON."""


# ── Public API ──────────────────────────────────────────────────────────────


def _parse_dossier_json(raw: str) -> dict | None:
    """Extract a JSON object from the agent's final message.

    The system prompt asks for "ONLY a JSON object", but Ollama models
    routinely prepend a preamble ("I now have all the data I need...") before
    the JSON. Tries strict parse first, then falls back to slicing from the
    first `{` to its matching `}` (string-aware so braces inside string
    literals don't fool the bracket counter).
    """
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass

    start = raw.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(raw)):
        ch = raw[i]
        if escape:
            escape = False
            continue
        if ch == "\\" and in_string:
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    parsed = json.loads(raw[start : i + 1])
                except json.JSONDecodeError:
                    return None
                return parsed if isinstance(parsed, dict) else None
    return None


async def gather_dossier(today: str | None = None) -> dict:
    """Run the research agent, or fall back to parallel fetch on total failure.

    Output schema matches data_fetcher.fetch_live_data() for script_prompt.j2.
    Ollama Cloud often returns 502 / unexpected EOF before the first stream
    chunk on long tool-calling requests; when that happens (after retries),
    we optionally fall back to ``fetch_live_data()`` so the pipeline completes.
    """
    today = today or str(date.today())
    try:
        return await _gather_dossier_via_agent(today)
    except Exception as exc:
        if not PODCAST_RESEARCH_FALLBACK_ON_FAILURE:
            raise
        log.error(
            "Research agent: failed (%s: %s). Falling back to fetch_live_data() "
            "so the episode can continue. Options: use local Ollama "
            "(OLLAMA_BASE_URL=http://127.0.0.1:11434), set PODCAST_AGENTIC=false "
            "to skip the agent, or PODCAST_RESEARCH_FALLBACK_ON_FAILURE=false to "
            "fail hard.",
            type(exc).__name__,
            exc,
        )
        from .data_fetcher import fetch_live_data

        data = await fetch_live_data()
        data["date"] = today
        data.update(session_meta(today))
        return data


async def _gather_dossier_via_agent(today: str) -> dict:
    log.info(
        "Research agent: starting (model=%s, max_rounds=%d)",
        OLLAMA_PODCAST_RESEARCH_MODEL,
        PODCAST_RESEARCH_MAX_ROUNDS,
    )

    registry = build_market_registry()
    registry.extend(_build_podcast_dossier_tools())

    user_prompt = (
        f"Research today's episode for {today}. Begin tool calls now, then emit "
        "the dossier JSON when you're done."
    )

    async with httpx.AsyncClient() as client:
        final_message, tool_results, rounds_used = await run_tool_loop(
            client,
            base_url=OLLAMA_BASE_URL,
            model=OLLAMA_PODCAST_RESEARCH_MODEL,
            system=_system_prompt(today, PODCAST_RESEARCH_MAX_ROUNDS),
            user=user_prompt,
            registry=registry,
            max_rounds=PODCAST_RESEARCH_MAX_ROUNDS,
            max_attempts=_RETRY_MAX_ATTEMPTS,
            options={"num_predict": 2048},
            label="Research agent",
        )

    raw = (final_message.get("content") or "").strip()
    raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    research_notes = ""
    parsed = _parse_dossier_json(raw)
    if isinstance(parsed, dict):
        research_notes = str(parsed.get("research_notes", "")).strip()
    elif raw:
        log.warning(
            "Research agent: final message was not valid JSON (head=%r) — "
            "proceeding with tool data only",
            raw[:200],
        )

    rb = tool_results.get("get_market_regime_and_breadth") or {}
    if isinstance(rb, dict) and "regime" in rb and "breadth" in rb:
        regime = rb["regime"]
        breadth = rb["breadth"]
    else:
        log.warning("Research agent: regime/breadth not fetched — falling back")
        regime, breadth = await asyncio.to_thread(_fetch_regime_and_breadth)

    news_stats = tool_results.get("get_news_24h_stats") or {}
    articles_24h = int(news_stats.get("articles_24h") or 0)
    sources_24h = int(news_stats.get("sources_24h") or 0)

    vix = tool_results.get("get_vix") or {
        "current": 0,
        "change_pct": 0,
        "direction": "flat",
    }

    data: dict[str, Any] = {
        "date": today,
        **session_meta(today),
        "regime": regime,
        "breadth": breadth,
        "vix": vix,
        "watchlist": tool_results.get("get_watchlist_setups") or [],
        "articles_24h": articles_24h,
        "sources_24h": sources_24h,
    }
    top_news = tool_results.get("get_top_news")
    if top_news:
        data["top_news"] = top_news
    earnings = tool_results.get("get_earnings")
    if earnings:
        data["earnings"] = earnings
    insider = tool_results.get("get_insider_activity")
    if insider:
        data["insider"] = insider
    if research_notes:
        data["research_notes"] = research_notes

    log.info(
        "Research agent: dossier ready — rounds=%d/%d, tools_called=%d, notes=%d chars, "
        "fetched=[%s]",
        rounds_used,
        PODCAST_RESEARCH_MAX_ROUNDS,
        len(tool_results),
        len(research_notes),
        ",".join(sorted(tool_results.keys())),
    )
    return data
