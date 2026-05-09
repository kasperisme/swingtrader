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

import asyncio
import json
import logging
import os
import re
from datetime import date
from typing import Any

import httpx

from services.agent_core import build_market_registry, run_tool_loop

from ..config import OLLAMA_BASE_URL, OLLAMA_PODCAST_SCRIPT_MODEL
from ..research_agent import _build_podcast_dossier_tools, _parse_dossier_json
from ..taxonomy_glossary import build_taxonomy_glossary
from .scene_researcher import (
    PodcastAgentError,
    _is_transient_ollama_error,
    _strip_envelope,
    _summarize_tool_results,
)

log = logging.getLogger(__name__)


class ProducerError(PodcastAgentError):
    """Raised when the producer's brief is missing or unusable.

    Downstream researchers and writers depend on the brief's narrative_arc,
    title, and per-scene angles. A blank brief means the show has no plan —
    failing here is preferred over shipping a writer with placeholder
    angles and a generic title.
    """


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
    return f"""You are the executive producer for The Impact Tape, the swing-trader podcast hosted by Hans (today: {today}).

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
    """Validate the producer's brief or raise ProducerError.

    Every LLM-written act must have a non-empty angle, the brief must have
    a narrative arc, and a title. Anything missing means the producer
    didn't actually plan the show — refusing to continue beats shipping a
    writer with a placeholder angle.
    """
    scenes_in = brief.get("scenes") or []
    scenes_by_act = {int(s.get("act", -1)): s for s in scenes_in if isinstance(s, dict)}

    title = str(brief.get("episode_title") or "").strip()
    arc = str(brief.get("narrative_arc") or "").strip()
    missing: list[str] = []
    if not title:
        missing.append("episode_title")
    if not arc:
        missing.append("narrative_arc")

    repaired: list[dict] = []
    for act_num, name in _LLM_ACT_NAMES:
        s = scenes_by_act.get(act_num) or {}
        angle = str(s.get("angle") or "").strip()
        if not angle:
            missing.append(f"scene act{act_num} {name} angle")
        repaired.append(
            {
                "act": act_num,
                "name": name,
                "angle": angle,
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

    if missing:
        raise ProducerError(
            f"Producer brief is missing required fields: {', '.join(missing)}. "
            "Refusing to ship downstream agents with a blank plan."
        )

    return {
        "episode_title": title,
        "episode_description": str(brief.get("episode_description") or "").strip(),
        "narrative_arc": arc,
        "scouting_notes": str(brief.get("scouting_notes") or "").strip(),
        "scenes": repaired,
    }


_SYNTHESIS_RETRY_MAX_ATTEMPTS = max(
    1, int(os.environ.get("PODCAST_PRODUCER_SYNTHESIS_RETRIES", "3"))
)
_SYNTHESIS_RETRY_INITIAL_BACKOFF_S = 2.0


# Per-field regex salvage. Used when the model emits a partial brief
# (truncated mid-string, missing closing braces, etc.) and ``_parse_dossier_json``
# can't recover the dict. Each field is extracted independently so a
# truncation halfway through ``scouting_notes`` still gives us title + arc.
_TITLE_RE = re.compile(
    r'"episode_title"\s*:\s*"((?:[^"\\]|\\.)*)"', flags=re.DOTALL
)
_DESCRIPTION_RE = re.compile(
    r'"episode_description"\s*:\s*"((?:[^"\\]|\\.)*)"', flags=re.DOTALL
)
_ARC_RE = re.compile(r'"narrative_arc"\s*:\s*"((?:[^"\\]|\\.)*)"', flags=re.DOTALL)
_SCOUTING_RE = re.compile(
    r'"scouting_notes"\s*:\s*"((?:[^"\\]|\\.)*)"', flags=re.DOTALL
)
# Per-scene angle: capture by act number so we don't depend on order.
_SCENE_ANGLE_RE = re.compile(
    r'"act"\s*:\s*(\d+)\s*,[^}]*?"angle"\s*:\s*"((?:[^"\\]|\\.)*)"',
    flags=re.DOTALL,
)
_SCENE_HANDOFF_RE = re.compile(
    r'"act"\s*:\s*(\d+)\s*,[^}]*?"hand_off_to_next"\s*:\s*"((?:[^"\\]|\\.)*)"',
    flags=re.DOTALL,
)


def _unescape_json_string(s: str) -> str:
    return (
        s.replace('\\"', '"')
        .replace("\\\\", "\\")
        .replace("\\n", "\n")
        .replace("\\t", "\t")
    )


def _salvage_brief(raw: str) -> dict:
    """Best-effort regex extraction of brief fields from malformed text.

    Returns whatever fields could be recovered. Never raises, never
    returns None — an empty dict means nothing was extractable. The
    caller merges this onto whatever ``_parse_dossier_json`` produced so
    a partial parse + partial salvage can still satisfy the validator.
    """
    out: dict = {}
    for key, pattern in (
        ("episode_title", _TITLE_RE),
        ("episode_description", _DESCRIPTION_RE),
        ("narrative_arc", _ARC_RE),
        ("scouting_notes", _SCOUTING_RE),
    ):
        m = pattern.search(raw)
        if m:
            value = _unescape_json_string(m.group(1)).strip()
            if value:
                out[key] = value

    angle_by_act: dict[int, str] = {}
    for m in _SCENE_ANGLE_RE.finditer(raw):
        try:
            act_num = int(m.group(1))
        except ValueError:
            continue
        angle = _unescape_json_string(m.group(2)).strip()
        if angle and act_num not in angle_by_act:
            angle_by_act[act_num] = angle

    handoff_by_act: dict[int, str] = {}
    for m in _SCENE_HANDOFF_RE.finditer(raw):
        try:
            act_num = int(m.group(1))
        except ValueError:
            continue
        handoff = _unescape_json_string(m.group(2)).strip()
        if act_num not in handoff_by_act:
            handoff_by_act[act_num] = handoff

    if angle_by_act or handoff_by_act:
        scenes: list[dict] = []
        for act_num, name in _LLM_ACT_NAMES:
            scene_entry: dict = {"act": act_num, "name": name}
            if act_num in angle_by_act:
                scene_entry["angle"] = angle_by_act[act_num]
            if act_num in handoff_by_act:
                scene_entry["hand_off_to_next"] = handoff_by_act[act_num]
            scenes.append(scene_entry)
        out["scenes"] = scenes
    return out


def _missing_required_fields(brief: dict) -> list[str]:
    """Return the list of validator-required fields still empty.

    Cheap precheck so the call site can skip synthesis when salvage
    already produced a complete brief, and so retry can show the model
    which fields it still needs to fill.
    """
    missing: list[str] = []
    if not isinstance(brief, dict):
        return ["episode_title", "narrative_arc"] + [
            f"scene act{n} {name} angle" for n, name in _LLM_ACT_NAMES
        ]
    if not str(brief.get("episode_title") or "").strip():
        missing.append("episode_title")
    if not str(brief.get("narrative_arc") or "").strip():
        missing.append("narrative_arc")
    scenes_by_act = {
        int(s.get("act", -1)): s
        for s in (brief.get("scenes") or [])
        if isinstance(s, dict)
    }
    for act_num, name in _LLM_ACT_NAMES:
        scene = scenes_by_act.get(act_num) or {}
        if not str(scene.get("angle") or "").strip():
            missing.append(f"scene act{act_num} {name} angle")
    return missing


def _merge_briefs(*briefs: dict) -> dict:
    """Merge partial briefs left-to-right, preferring later non-empty values.

    For ``scenes``, merges per-act so a synthesized angle for act 3 wins
    over an empty angle for act 3 in an earlier brief, while a salvaged
    title still wins if synthesis didn't return one.
    """
    merged: dict = {}
    scenes_by_act: dict[int, dict] = {}
    for brief in briefs:
        if not isinstance(brief, dict):
            continue
        for key, value in brief.items():
            if key == "scenes":
                continue
            if value:  # non-empty
                merged[key] = value
        for scene in brief.get("scenes") or []:
            if not isinstance(scene, dict):
                continue
            try:
                act_num = int(scene.get("act", -1))
            except (TypeError, ValueError):
                continue
            existing = scenes_by_act.setdefault(act_num, {"act": act_num})
            for k, v in scene.items():
                if v:
                    existing[k] = v
    if scenes_by_act:
        merged["scenes"] = [scenes_by_act[k] for k in sorted(scenes_by_act)]
    return merged


async def _synthesize_brief_from_tools(
    tool_results: dict, today: str, partial: dict | None = None
) -> dict | None:
    """Last-resort recovery when the producer's final message is missing.

    Sometimes the model exits the tool loop with empty content or a
    response that doesn't parse. The tool_results are still in hand, so
    we call the model fresh with those results inlined and ask it to
    emit ONLY the EpisodeBrief JSON.

    When ``partial`` is provided (from a previous synthesis attempt or
    salvage), it's shown to the model along with which fields are still
    missing — the model only needs to produce the remaining values.
    Retried on transient errors.
    """
    if not tool_results:
        return None

    partial_block = ""
    if partial and any(partial.values()):
        missing = _missing_required_fields(partial)
        partial_block = (
            "\n\nPARTIAL BRIEF (from prior attempts — keep these values, "
            f"fill the missing fields):\n{json.dumps(partial, indent=2)}\n"
            f"STILL MISSING: {missing or '[]'}\n"
        )

    user_prompt = (
        f"Today is {today}. Below are the scouting tool results gathered for "
        "today's episode. Synthesize them into an EpisodeBrief JSON object "
        "with EXACTLY this schema:\n\n"
        "{\n"
        '  "episode_title": "5-9 word concrete title",\n'
        '  "episode_description": "2-3 sentence show-notes summary",\n'
        '  "narrative_arc": "one-sentence story arc",\n'
        '  "scouting_notes": "2-4 sentences of cross-section context",\n'
        '  "scenes": [\n'
        '    {"act": 1, "name": "COLD OPEN",              "angle": "what this act teases", "hand_off_to_next": "tonal pivot", "tools_to_prioritize": []},\n'
        '    {"act": 2, "name": "EXECUTIVE SUMMARY",      "angle": "...", "hand_off_to_next": "...", "tools_to_prioritize": []},\n'
        '    {"act": 3, "name": "MARKET REGIME BRIEFING", "angle": "...", "hand_off_to_next": "...", "tools_to_prioritize": []},\n'
        '    {"act": 4, "name": "TOP STORY DEEP DIVE",    "angle": "...", "hand_off_to_next": "...", "tools_to_prioritize": []},\n'
        '    {"act": 5, "name": "WATCHLIST PULSE",        "angle": "...", "hand_off_to_next": "...", "tools_to_prioritize": []},\n'
        '    {"act": 6, "name": "CLOSE + THESIS",         "angle": "...", "hand_off_to_next": "",    "tools_to_prioritize": []}\n'
        "  ]\n"
        "}\n\n"
        "Every angle must be a non-empty concrete sentence. Output ONLY the "
        "JSON object — no preamble, no markdown fences. Start with { and end with }."
        f"{partial_block}\n"
        f"TOOL RESULTS:\n\n{_summarize_tool_results(tool_results)}"
    )
    messages = [
        {
            "role": "system",
            "content": (
                "You are an episode-brief synthesizer. Read the user's tool "
                "results and emit a single valid EpisodeBrief JSON object. "
                "No preamble, no markdown fences. Start with { and end with }."
            ),
        },
        {"role": "user", "content": user_prompt},
    ]
    backoff = _SYNTHESIS_RETRY_INITIAL_BACKOFF_S
    last_exc: BaseException | None = None
    for attempt in range(1, _SYNTHESIS_RETRY_MAX_ATTEMPTS + 1):
        try:
            async with httpx.AsyncClient() as client:
                r = await client.post(
                    f"{OLLAMA_BASE_URL}/api/chat",
                    json={
                        "model": OLLAMA_PODCAST_PRODUCER_MODEL,
                        "messages": messages,
                        "stream": False,
                        "options": {"temperature": 0.2},
                    },
                    timeout=240,
                )
                r.raise_for_status()
                payload = r.json()
            content = (payload.get("message", {}).get("content") or "").strip()
            log.info(
                "Producer: synthesis call returned %d chars (attempt %d)",
                len(content),
                attempt,
            )
            return _parse_dossier_json(_strip_envelope(content))
        except Exception as exc:
            last_exc = exc
            if (
                not _is_transient_ollama_error(exc)
                or attempt == _SYNTHESIS_RETRY_MAX_ATTEMPTS
            ):
                raise
            log.warning(
                "Producer: synthesis attempt %d/%d failed (%s: %s) — retrying in %.0fs",
                attempt,
                _SYNTHESIS_RETRY_MAX_ATTEMPTS,
                type(exc).__name__,
                str(exc)[:200],
                backoff,
            )
            await asyncio.sleep(backoff)
            backoff *= 2
    assert last_exc is not None
    raise last_exc


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
            label="Producer",
        )

    raw = (final_message.get("content") or "").strip()
    raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    parsed = _parse_dossier_json(raw) if raw else None

    # Always run regex salvage on the raw text — costs nothing and lets a
    # truncated brief still contribute its title / arc / partial scenes.
    salvaged = _salvage_brief(raw) if raw else {}
    if salvaged:
        log.info(
            "Producer: regex salvage recovered keys=%s, scenes=%d",
            sorted(k for k in salvaged if k != "scenes"),
            len(salvaged.get("scenes") or []),
        )

    candidate = _merge_briefs(parsed if isinstance(parsed, dict) else {}, salvaged)

    # Validation pre-check: if salvage + parse already yields a complete
    # brief, skip the synthesis call entirely.
    needs_synthesis = _missing_required_fields(candidate)

    if needs_synthesis:
        log.warning(
            "Producer: parse + salvage incomplete (missing=%s) — "
            "falling back to tool-results synthesis (%d tools called, raw=%d chars)",
            needs_synthesis[:5],
            len(tool_results),
            len(raw),
        )
        if not tool_results:
            raise ProducerError(
                "Producer brief unrecoverable — final message was unusable "
                f"(raw={len(raw)} chars, head={raw[:200]!r}) AND the tool "
                "loop produced zero tool_results, so synthesis has no "
                "market data to build a brief from. The producer never "
                "actually scouted the market."
            )

        # Retry synthesis with feedback when it returns a brief that still
        # fails validation. Each attempt sees the partial brief from the
        # last try so the model knows which fields to fill.
        for attempt in range(1, _SYNTHESIS_RETRY_MAX_ATTEMPTS + 1):
            try:
                synthesized = await _synthesize_brief_from_tools(
                    tool_results,
                    today,
                    partial=candidate if any(candidate.values()) else None,
                )
            except Exception as exc:
                log.warning(
                    "Producer: synthesis attempt %d/%d call failed: %s",
                    attempt,
                    _SYNTHESIS_RETRY_MAX_ATTEMPTS,
                    exc,
                )
                synthesized = None

            if isinstance(synthesized, dict):
                candidate = _merge_briefs(candidate, synthesized)
                missing_after = _missing_required_fields(candidate)
                log.info(
                    "Producer: synthesis attempt %d merged — missing now=%s",
                    attempt,
                    missing_after[:5] or "[]",
                )
                if not missing_after:
                    break

    if not isinstance(candidate, dict):
        candidate = {}

    brief = _validate_brief(candidate)

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
