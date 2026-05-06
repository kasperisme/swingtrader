"""Producer agent — top-down episode planner.

The producer runs a heavy scouting tool-loop to understand today's market
state, find the single narrative thread that ties the episode together,
and emit a per-scene brief. Downstream researchers and writers consume the
brief; the producer never writes script content directly.

Tool access is the full registry — base market RAG tools plus the podcast
dossier wrappers — because the producer's job is to find the *unexpected*
angle that makes today's episode distinct, not just collect framing
aggregates. Per-scene researchers will narrow the focus later.

Output schema (EpisodeBrief):

    {
      "episode_title": "string — compelling 5-9 word title",
      "episode_description": "string — 2-3 sentence show-notes summary",
      "narrative_arc": "string — one-sentence story arc",
      "scouting_notes": "string — 2-4 sentences of cross-section context",
      "scenes": [
        {
          "act": 1, "name": "COLD OPEN",
          "angle": "string — what this act teases",
          "hand_off_to_next": "string — tonal pivot into the next act",
          "tools_to_prioritize": ["string", ...]
        },
        ... (acts 2-6)
      ]
    }

`plan_episode` returns the validated brief alongside the producer's
captured tool_results dict. Downstream agents harvest the tool_results to
build a world-state baseline so per-scene researchers don't re-fetch the
framing aggregates.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import date
from typing import Any

import httpx

from services.agent_core import build_market_registry, run_tool_loop

from ..config import OLLAMA_BASE_URL, OLLAMA_PODCAST_SCRIPT_MODEL
from ..research_agent import _build_podcast_dossier_tools, _parse_dossier_json
from ..taxonomy_glossary import build_taxonomy_glossary

log = logging.getLogger(__name__)


PODCAST_PRODUCER_MAX_ROUNDS = int(
    os.environ.get("PODCAST_PRODUCER_MAX_ROUNDS", "12")
)
_RETRY_MAX_ATTEMPTS = max(
    1, int(os.environ.get("PODCAST_PRODUCER_OLLAMA_RETRIES", "3"))
)

# Tool-calling needs a model that supports Ollama's `tools` payload. Falls
# back through the existing chain so single-model setups don't need extra
# config.
OLLAMA_PODCAST_PRODUCER_MODEL = (
    os.environ.get("OLLAMA_PODCAST_PRODUCER_MODEL")
    or os.environ.get("OLLAMA_PODCAST_RESEARCH_MODEL")
    or os.environ.get("OLLAMA_TIKTOK_MODEL")
    or os.environ.get("OLLAMA_BLOG_MODEL")
    or OLLAMA_PODCAST_SCRIPT_MODEL
)


# Acts the LLM downstream produces (HOOK / WELCOME / SIGN_OFF are
# deterministic and the producer doesn't plan them).
_LLM_ACT_NAMES: list[tuple[int, str]] = [
    (1, "COLD OPEN"),
    (2, "EXECUTIVE SUMMARY"),
    (3, "MARKET REGIME BRIEFING"),
    (4, "TOP STORY DEEP DIVE"),
    (5, "WATCHLIST PULSE"),
    (6, "CLOSE + THESIS"),
]


def _system_prompt(today: str, max_rounds: int) -> str:
    glossary = build_taxonomy_glossary()
    return f"""You are the executive producer for NewsImpact Daily, the swing-trader podcast hosted by Hans (today: {today}).

Your job: scout today's market with the tools available, find the single narrative thread that ties the whole episode together, and plan all six LLM-written acts. You are NOT writing the script — per-scene researchers and writers do that downstream. Your output is the producer's brief.

# Iteration budget

You have at most {max_rounds} tool rounds. Plan with ambition — this is your scouting pass:
- Start with the framing aggregates: get_market_regime_and_breadth, get_top_news, get_watchlist_setups, get_news_24h_stats. These are the spine of every show.
- Then explore: what's the dominant THEME today? Use get_cluster_trends, get_dimension_trends, get_ticker_news, search_news, or fetch_url to find the cross-section colour that makes today's episode distinct. The TAXONOMY GLOSSARY at the bottom of this prompt defines every cluster and dimension by the same definitions the scoring system uses — consult it when you read those tool results so your scouting_notes describe the meaning ("rate-sensitive flow turning hot"), not the label ("Macro Sensitivity at +0.9"). Downstream writers will lean on your translations.
- Pull get_vix only if today's reading is genuinely notable. Pull get_earnings only if earnings season is active. Pull get_insider_activity if top news impact_score >= 8 or if a stage-2 watchlist name has no top-news coverage.
- Don't repeat tool calls — they're cached. If you're 2 rounds from the cap, stop fetching and emit the brief.

# Decisions you must make

After scouting, decide:

0. **Episode title** — compelling 5-9 word title. Concrete, not generic ("NVIDIA's Surge and the Bull's First Crack" beats "Markets Today: A Recap").
0a. **Episode description** — 2-3 sentence show-notes summary capturing what listeners will learn. This goes in podcast directories.

1. **Narrative arc** — ONE sentence that captures what the whole episode builds toward. The arc is what every act feeds. Examples:
   - "A clean bull tape is hiding cracks under the surface — three names show it most."
   - "Twelve sessions in and breadth still holds, but today's volatility move is the first crack."
   - "Earnings season is reshaping leadership: yesterday's leaders are this morning's laggards."

2. **Per-act angle** — for each of the six LLM acts, what does the act tease/reveal/imply?
   - act 1 COLD OPEN — the hook, no stats
   - act 2 EXECUTIVE SUMMARY — the listener's TL;DR, lead with the conclusion
   - act 3 MARKET REGIME BRIEFING — regime + breadth + VIX (if notable). The weekday is named here, only here.
   - act 4 TOP STORY DEEP DIVE — the highest-impact news, factor summary, implications
   - act 5 WATCHLIST PULSE — top setups nearing entry
   - act 6 CLOSE + THESIS — forward-looking only, the watch-tomorrow item

3. **Hand-off** — for each act except the last, the tonal pivot into the next act. Downstream writers use this so transitions don't read as hard cuts. Examples:
   - "Energy stays high — analyst voice carries the listener from the regime numbers into the marquee story."
   - "Anchor steps back, lets the analyst land the watchlist takeaway and then return to forward-looking close."

4. **Tools to prioritize** — for each act, which tools should the scene's researcher dig into? This is a hint, not enforcement. Use the dossier tool names (e.g. get_top_news, get_watchlist_setups) plus any RAG tools you found valuable during scouting (e.g. get_ticker_news, search_news).

# Output format

Emit ONLY a JSON object (no preamble, no markdown fences). Start with `{{` and end with `}}`.

{{
  "episode_title": "string — compelling 5-9 word title",
  "episode_description": "string — 2 to 3 sentence show-notes summary",
  "narrative_arc": "string — one-sentence story arc",
  "scouting_notes": "string — 2 to 4 sentences summarizing what your tool loop found that informs the arc",
  "scenes": [
    {{ "act": 1, "name": "COLD OPEN",              "angle": "...", "hand_off_to_next": "...", "tools_to_prioritize": ["..."] }},
    {{ "act": 2, "name": "EXECUTIVE SUMMARY",      "angle": "...", "hand_off_to_next": "...", "tools_to_prioritize": ["..."] }},
    {{ "act": 3, "name": "MARKET REGIME BRIEFING", "angle": "...", "hand_off_to_next": "...", "tools_to_prioritize": ["..."] }},
    {{ "act": 4, "name": "TOP STORY DEEP DIVE",    "angle": "...", "hand_off_to_next": "...", "tools_to_prioritize": ["..."] }},
    {{ "act": 5, "name": "WATCHLIST PULSE",        "angle": "...", "hand_off_to_next": "...", "tools_to_prioritize": ["..."] }},
    {{ "act": 6, "name": "CLOSE + THESIS",         "angle": "...", "hand_off_to_next": "",   "tools_to_prioritize": ["..."] }}
  ]
}}

The last act has an empty hand_off_to_next because the deterministic SIGN_OFF closes the show.

# Taxonomy glossary — what every cluster and dimension actually measures

These are INTERNAL labels. Listeners never hear them. Use this glossary to translate any cluster_trends / dimension_trends signal you see from a tool call into plain trader meaning before you write it into scouting_notes or per-act angles. Sign of the score = which way today's news skews (positive ≈ toward this theme, negative ≈ away). Magnitude = strength (under 0.3 leaning, 0.3–0.6 clearly, above 0.6 loudly).

{glossary}
"""


def _validate_brief(brief: dict) -> dict:
    """Backfill missing fields so downstream agents always see all six scenes.

    The model occasionally drops a scene or skips a field. Rather than fail
    the pipeline, fill the gap with a placeholder string so the editor and
    writers degrade gracefully.
    """
    scenes_in = brief.get("scenes") or []
    scenes_by_act = {int(s.get("act", -1)): s for s in scenes_in if isinstance(s, dict)}

    repaired: list[dict] = []
    for act_num, name in _LLM_ACT_NAMES:
        s = scenes_by_act.get(act_num) or {}
        repaired.append(
            {
                "act": act_num,
                "name": name,
                "angle": str(s.get("angle") or "").strip()
                or f"(producer left {name} angle blank — writer falls back to template)",
                "hand_off_to_next": (
                    str(s.get("hand_off_to_next") or "").strip()
                    if act_num < 6
                    else ""
                ),
                "tools_to_prioritize": [
                    str(t) for t in (s.get("tools_to_prioritize") or [])
                ],
            }
        )

    return {
        "episode_title": str(brief.get("episode_title") or "").strip()
        or "NewsImpact Daily",
        "episode_description": str(brief.get("episode_description") or "").strip(),
        "narrative_arc": str(brief.get("narrative_arc") or "").strip()
        or "(producer left narrative arc blank)",
        "scouting_notes": str(brief.get("scouting_notes") or "").strip(),
        "scenes": repaired,
    }


async def plan_episode(
    today: str | None = None,
) -> tuple[dict, dict[str, object]]:
    """Run the producer agent and return ``(EpisodeBrief, tool_results)``.

    The tool_results dict carries everything the producer fetched during
    scouting. Downstream agents build a world-state baseline from it so
    per-scene researchers don't redundantly re-fetch the framing
    aggregates.

    Raises on total Ollama failure — the multi-agent pipeline catches and
    decides whether to fall back. Keeping the raise here means
    `plan_episode` is composable: callers that want the brief can decide
    independently how to handle failure.
    """
    today = today or str(date.today())
    log.info(
        "Producer: starting (model=%s, max_rounds=%d)",
        OLLAMA_PODCAST_PRODUCER_MODEL,
        PODCAST_PRODUCER_MAX_ROUNDS,
    )

    registry = build_market_registry()
    registry.extend(_build_podcast_dossier_tools())

    user_prompt = (
        f"Plan today's episode for {today}. Scout broadly, find the day's "
        "narrative thread, then emit the EpisodeBrief JSON when you're done."
    )

    async with httpx.AsyncClient() as client:
        final_message, tool_results, rounds_used = await run_tool_loop(
            client,
            base_url=OLLAMA_BASE_URL,
            model=OLLAMA_PODCAST_PRODUCER_MODEL,
            system=_system_prompt(today, PODCAST_PRODUCER_MAX_ROUNDS),
            user=user_prompt,
            registry=registry,
            max_rounds=PODCAST_PRODUCER_MAX_ROUNDS,
            max_attempts=_RETRY_MAX_ATTEMPTS,
            options={"num_predict": 2048},
            label="Producer",
        )

    raw = (final_message.get("content") or "").strip()
    raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    parsed = _parse_dossier_json(raw)
    if not isinstance(parsed, dict):
        log.warning(
            "Producer: final message was not valid JSON (head=%r) — using empty brief",
            raw[:200],
        )
        parsed = {}

    brief = _validate_brief(parsed)

    log.info(
        "Producer: brief ready — rounds=%d/%d, tools_called=%d, arc=%r",
        rounds_used,
        PODCAST_PRODUCER_MAX_ROUNDS,
        len(tool_results),
        brief["narrative_arc"][:120],
    )
    for scene in brief["scenes"]:
        log.info(
            "Producer scene %d %s: angle=%r, tools=%s",
            scene["act"],
            scene["name"],
            scene["angle"][:80],
            scene["tools_to_prioritize"] or "[]",
        )

    return brief, tool_results
