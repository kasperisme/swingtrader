"""Per-scene researcher agent.

Each LLM-written act gets its own focused researcher. Researchers run
sequentially: scene N sees the carry-forward strings from scenes 1..N-1
so the storyline can chain across acts (e.g. "act 4 should pick up the
volatility thread the regime briefing surfaced").

The world-state baseline assembled by the multi-agent pipeline (regime,
breadth, top news, watchlist, news_24h_stats — whatever the producer
already fetched) is rendered into the system prompt as "what's already
known". Researchers are told NOT to re-fetch those aggregates and to
spend their tool budget on scene-specific colour instead.

Tool access is the full registry — base RAG tools plus dossier wrappers —
because some scenes (cold open, deep dive) benefit from semantic search
or article-body fetches that producers won't always anticipate.

Output (SceneDossier):

    {
      "act": int, "name": "string",
      "data": {tool_name: result, ...},   # this scene's tool_results
      "narrative_notes": "string — 2-4 sentences of context for the writer",
      "carry_forward": "string — 1-2 sentences for the next researcher"
    }
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import Any

import httpx

from services.agent_core import build_market_registry, run_tool_loop

from ..config import OLLAMA_BASE_URL, OLLAMA_PODCAST_SCRIPT_MODEL
from ..research_agent import _build_podcast_dossier_tools, _parse_dossier_json
from ..taxonomy_glossary import build_taxonomy_glossary

log = logging.getLogger(__name__)


class PodcastAgentError(RuntimeError):
    """Base class for any LLM-agent-level failure in the multi-agent pipeline.

    The multi-agent pipeline never falls back to single-agent on these —
    the producer's plan is locked in, and shipping a different show with
    different research silently is worse than failing loudly.
    """


class SceneResearchError(PodcastAgentError):
    """Raised when a scene's dossier can't be recovered.

    Failing fast here is preferred over shipping empty narrative_notes — a
    writer with no research produces filler that pretends to know the
    market.
    """


PODCAST_SCENE_RESEARCH_MAX_ROUNDS = int(
    os.environ.get("PODCAST_SCENE_RESEARCH_MAX_ROUNDS", "6")
)
_RETRY_MAX_ATTEMPTS = max(
    1, int(os.environ.get("PODCAST_SCENE_RESEARCH_OLLAMA_RETRIES", "3"))
)

# Falls back through the existing chain so single-model setups don't need
# extra config.
OLLAMA_PODCAST_SCENE_RESEARCH_MODEL = (
    os.environ.get("OLLAMA_PODCAST_SCENE_RESEARCH_MODEL")
    or os.environ.get("OLLAMA_PODCAST_RESEARCH_MODEL")
    or os.environ.get("OLLAMA_TIKTOK_MODEL")
    or os.environ.get("OLLAMA_BLOG_MODEL")
    or OLLAMA_PODCAST_SCRIPT_MODEL
)


_THINK_RE = re.compile(r"<think>.*?</think>", flags=re.DOTALL)
_FENCED_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", flags=re.DOTALL)
_NARRATIVE_NOTES_RE = re.compile(
    r'"narrative_notes"\s*:\s*"((?:[^"\\]|\\.)*)"',
    flags=re.DOTALL,
)
_CARRY_FORWARD_RE = re.compile(
    r'"carry_forward"\s*:\s*"((?:[^"\\]|\\.)*)"',
    flags=re.DOTALL,
)
# Truncation fallbacks — used when the model cuts off mid-string and the
# strict regex above can't find a closing quote. Captures from the opening
# quote until either the next field key or end-of-input.
_NARRATIVE_NOTES_TRUNCATED_RE = re.compile(
    r'"narrative_notes"\s*:\s*"((?:[^"\\]|\\.)*)$',
    flags=re.DOTALL,
)
_CARRY_FORWARD_TRUNCATED_RE = re.compile(
    r'"carry_forward"\s*:\s*"((?:[^"\\]|\\.)*)$',
    flags=re.DOTALL,
)
_REPAIR_RETRY_INITIAL_BACKOFF_S = 2.0


def _is_transient_ollama_error(exc: BaseException) -> bool:
    """True for errors a retry can plausibly recover from.

    Mirrors script_generator's classifier: covers Ollama Cloud's flapping
    502/503/504/429, "too many concurrent requests", "unexpected EOF",
    plus transport failures (drops, timeouts).
    """
    if isinstance(
        exc,
        (
            httpx.RemoteProtocolError,
            httpx.ReadTimeout,
            httpx.ConnectTimeout,
            httpx.ConnectError,
            httpx.NetworkError,
            httpx.PoolTimeout,
        ),
    ):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        if 500 <= exc.response.status_code < 600 or exc.response.status_code in (
            408,
            429,
        ):
            return True
    msg = str(exc).lower()
    return any(
        s in msg
        for s in ("502", "503", "504", "429", "408", "unexpected eof", "too many concurrent")
    )


def _salvage_partial_dossier(raw: str) -> dict | None:
    """Extract narrative_notes / carry_forward from unclosed JSON via regex.

    The model occasionally truncates mid-object so ``_parse_dossier_json``'s
    brace-matcher gives up. Most of the value (the narrative notes the
    writer needs) is usually present before the cut. Best-effort: returns
    a dict only if at least one field was recovered.
    """
    notes_match = _NARRATIVE_NOTES_RE.search(raw)
    carry_match = _CARRY_FORWARD_RE.search(raw)
    notes = notes_match.group(1) if notes_match else ""
    carry = carry_match.group(1) if carry_match else ""
    # Truncation fallback: model cut off mid-string with no closing quote.
    # Read to end-of-input but stop at the next field key so we don't bleed
    # one field into another.
    if not notes:
        m = _NARRATIVE_NOTES_TRUNCATED_RE.search(raw)
        if m:
            notes = m.group(1).split('"carry_forward"', 1)[0].rstrip(", \n\t")
    if not carry:
        m = _CARRY_FORWARD_TRUNCATED_RE.search(raw)
        if m:
            carry = m.group(1).split('"narrative_notes"', 1)[0].rstrip(", \n\t")
    if not (notes or carry):
        return None
    # Unescape minimal JSON string escapes so the salvaged text reads cleanly.
    def _unescape(s: str) -> str:
        return (
            s.replace('\\"', '"')
            .replace("\\\\", "\\")
            .replace("\\n", "\n")
            .replace("\\t", "\t")
        )

    return {
        "narrative_notes": _unescape(notes).strip(),
        "carry_forward": _unescape(carry).strip(),
    }


def _summarize_tool_results(tool_results: dict, max_chars: int = 6000) -> str:
    """Render tool_results as a compact JSON blob for synthesis prompts.

    Truncates each entry's serialized form to keep the total under
    ``max_chars`` so we don't blow the context budget when a researcher's
    tool loop pulled long article bodies.
    """
    if not tool_results:
        return "(no tools were called)"
    parts: list[str] = []
    budget = max_chars
    for name, value in tool_results.items():
        body = json.dumps(value, default=str)
        if len(body) > 1500:
            body = body[:1500] + "…(truncated)"
        entry = f"## {name}\n{body}"
        if budget - len(entry) <= 0:
            parts.append(f"## {name}\n(omitted — context budget exhausted)")
            break
        parts.append(entry)
        budget -= len(entry)
    return "\n\n".join(parts)


async def _synthesize_dossier_from_tools(
    tool_results: dict,
    scene: dict,
    label: str,
) -> dict | None:
    """Last-resort recovery when the researcher's final message was empty.

    Sometimes the model exits the tool loop without emitting any text
    (returns a content-empty message). The tool_results are still in hand,
    so we call the model fresh with those results inlined and ask it to
    emit ONLY the dossier JSON. Retried on transient errors.
    """
    if not tool_results:
        return None
    user_prompt = (
        f"Scene: act {scene.get('act')} {scene.get('name')}.\n"
        f"Angle: {scene.get('angle', '').strip()}\n\n"
        "Below are the tool results gathered for this scene. Synthesize them "
        "into a dossier JSON object with exactly two fields:\n"
        '  - "narrative_notes": 2-4 sentences of context for the writer\n'
        '  - "carry_forward": 1-2 sentences for the next scene\'s researcher\n\n'
        "Output ONLY the JSON object. Start with { and end with }.\n\n"
        f"TOOL RESULTS:\n\n{_summarize_tool_results(tool_results)}"
    )
    messages = [
        {
            "role": "system",
            "content": (
                "You are a research synthesizer. Read the user's tool results "
                "and emit a single valid JSON object: "
                '{"narrative_notes": "string", "carry_forward": "string"}. '
                "No preamble, no markdown fences. Start with { and end with }."
            ),
        },
        {"role": "user", "content": user_prompt},
    ]
    backoff = _REPAIR_RETRY_INITIAL_BACKOFF_S
    last_exc: BaseException | None = None
    for attempt in range(1, _RETRY_MAX_ATTEMPTS + 1):
        try:
            async with httpx.AsyncClient() as client:
                r = await client.post(
                    f"{OLLAMA_BASE_URL}/api/chat",
                    json={
                        "model": OLLAMA_PODCAST_SCENE_RESEARCH_MODEL,
                        "messages": messages,
                        "stream": False,
                        "options": {"num_predict": 1024, "temperature": 0.2},
                    },
                    timeout=180,
                )
                r.raise_for_status()
                payload = r.json()
            content = (payload.get("message", {}).get("content") or "").strip()
            log.info(
                "%s: synthesis call returned %d chars (attempt %d)",
                label,
                len(content),
                attempt,
            )
            return _parse_dossier_json(_strip_envelope(content))
        except Exception as exc:
            last_exc = exc
            if not _is_transient_ollama_error(exc) or attempt == _RETRY_MAX_ATTEMPTS:
                raise
            log.warning(
                "%s: synthesis attempt %d/%d failed (%s: %s) — retrying in %.0fs",
                label,
                attempt,
                _RETRY_MAX_ATTEMPTS,
                type(exc).__name__,
                str(exc)[:200],
                backoff,
            )
            await asyncio.sleep(backoff)
            backoff *= 2
    assert last_exc is not None
    raise last_exc


def _strip_envelope(raw: str) -> str:
    """Strip reasoning tokens and markdown fences regardless of where they sit.

    Some models prepend a chain-of-thought preamble or wrap their JSON in
    a fenced block despite the prompt's "no markdown" instruction. We pull
    the fenced body out when one is present, otherwise we leave the raw
    text alone for ``_parse_dossier_json`` to slice from the first ``{``.
    """
    cleaned = _THINK_RE.sub("", raw).strip()
    fenced = _FENCED_BLOCK_RE.search(cleaned)
    if fenced:
        return fenced.group(1).strip()
    # Trim a leading bare fence if the closing one is missing.
    return (
        cleaned.removeprefix("```json")
        .removeprefix("```")
        .removesuffix("```")
        .strip()
    )


async def _repair_json_once(raw: str, label: str) -> dict | None:
    """One-shot non-tool call to coerce a malformed final message into JSON.

    Used when the researcher's final message fails to parse — the model
    almost always has the substance right but added prose, fences, or
    invalid escapes around the JSON. We hand the raw text back and ask
    for ONLY the dossier JSON.
    """
    messages = [
        {
            "role": "system",
            "content": (
                "You are a JSON repair tool. Read the user's input and emit a "
                "single valid JSON object matching this schema exactly: "
                '{"narrative_notes": "string", "carry_forward": "string"}. '
                "Output ONLY the JSON object — no preamble, no markdown fences, "
                "no commentary. Start with { and end with }."
            ),
        },
        {"role": "user", "content": raw},
    ]
    backoff = _REPAIR_RETRY_INITIAL_BACKOFF_S
    last_exc: BaseException | None = None
    for attempt in range(1, _RETRY_MAX_ATTEMPTS + 1):
        try:
            async with httpx.AsyncClient() as client:
                r = await client.post(
                    f"{OLLAMA_BASE_URL}/api/chat",
                    json={
                        "model": OLLAMA_PODCAST_SCENE_RESEARCH_MODEL,
                        "messages": messages,
                        "stream": False,
                        "options": {"num_predict": 1024, "temperature": 0.1},
                    },
                    timeout=120,
                )
                r.raise_for_status()
                payload = r.json()
            content = (payload.get("message", {}).get("content") or "").strip()
            log.info(
                "%s: repair call returned %d chars (attempt %d)",
                label,
                len(content),
                attempt,
            )
            return _parse_dossier_json(_strip_envelope(content))
        except Exception as exc:
            last_exc = exc
            if not _is_transient_ollama_error(exc) or attempt == _RETRY_MAX_ATTEMPTS:
                raise
            log.warning(
                "%s: repair attempt %d/%d failed (%s: %s) — retrying in %.0fs",
                label,
                attempt,
                _RETRY_MAX_ATTEMPTS,
                type(exc).__name__,
                str(exc)[:200],
                backoff,
            )
            await asyncio.sleep(backoff)
            backoff *= 2

    assert last_exc is not None  # unreachable
    raise last_exc


def _format_world_state(world: dict) -> str:
    """Render the producer's harvested aggregates as a 'known' block."""
    lines: list[str] = []
    if world.get("regime"):
        lines.append(f"REGIME: {json.dumps(world['regime'], default=str)}")
    if world.get("breadth"):
        lines.append(f"BREADTH: {json.dumps(world['breadth'], default=str)}")
    if world.get("vix"):
        lines.append(f"VIX: {json.dumps(world['vix'], default=str)}")
    if world.get("top_news"):
        lines.append(f"TOP_NEWS: {json.dumps(world['top_news'], default=str)}")
    if world.get("watchlist"):
        lines.append(
            f"WATCHLIST ({len(world['watchlist'])} setups): "
            f"{json.dumps(world['watchlist'], default=str)[:600]}"
        )
    if "articles_24h" in world or "sources_24h" in world:
        lines.append(
            f"NEWS_24H_STATS: articles={world.get('articles_24h')} "
            f"sources={world.get('sources_24h')}"
        )
    if world.get("earnings"):
        lines.append(f"EARNINGS: {json.dumps(world['earnings'], default=str)}")
    if world.get("insider"):
        lines.append(f"INSIDER: {json.dumps(world['insider'], default=str)}")
    return "\n".join(lines) if lines else "(world state empty — fetch what you need)"


def _format_carry_forward(chain: list[dict]) -> str:
    if not chain:
        return "(this is the first scene — no prior carry-forward)"
    return "\n".join(
        f"- Act {entry['act']} {entry['name']}: {entry['carry_forward']}"
        for entry in chain
        if entry.get("carry_forward", "").strip()
    ) or "(prior researchers had no carry-forward to add)"


def _system_prompt(
    today: str,
    weekday: str,
    scene: dict,
    episode_brief: dict,
    world_state: dict,
    carry_forward_chain: list[dict],
    max_rounds: int,
) -> str:
    glossary = build_taxonomy_glossary()
    return f"""You are the scene researcher for act {scene['act']} {scene['name']} of The Impact Tape, the swing-trader podcast hosted by Hans (today: {today}, {weekday}).

# Episode-level context (from the producer)

NARRATIVE ARC: {episode_brief.get('narrative_arc', '').strip()}
SCOUTING NOTES: {episode_brief.get('scouting_notes', '').strip()}

# Your scene's brief

ANGLE: {scene.get('angle', '').strip()}
TOOLS THE PRODUCER SUGGESTED: {scene.get('tools_to_prioritize') or '[]'}
HAND-OFF TO NEXT ACT: {scene.get('hand_off_to_next', '').strip() or '(this is the last LLM act — sign-off is deterministic)'}

# Carry-forward from prior scene researchers

{_format_carry_forward(carry_forward_chain)}

# What's already known (world state harvested from the producer's scouting)

{_format_world_state(world_state)}

# Your job

Research act {scene['act']} {scene['name']}. The producer's angle is "{scene.get('angle', '').strip()}".

You have at most {max_rounds} tool rounds. Use them WISELY:
- DO NOT re-fetch the aggregates listed under "What's already known" — they're cached and will be passed to your writer alongside your findings.
- DO use search_news, get_ticker_news, get_top_articles, fetch_url, get_cluster_trends, get_dimension_trends, get_ticker_relationships, get_company_vectors to add scene-specific colour. When cluster_trends or dimension_trends come back, consult the TAXONOMY GLOSSARY at the bottom of this prompt for the exact definition the scoring system uses, and write your narrative_notes / carry_forward in plain trader meaning ("rate-sensitive flow turning hot, debt-heavy names catching the bid"), never as label + decimal ("Macro Sensitivity +0.9").
- The producer's tool_to_prioritize list is a hint, not enforcement. If you find a more compelling angle, follow it.
- If the world state is missing a field your scene requires (e.g. you're researching the deep dive but no top_news), call the dossier tool to fill the gap.

Per-scene focus rules:
- act 1 COLD OPEN: find the ONE most arresting fact for a hook. No stats — what makes today *distinct*.
- act 2 EXECUTIVE SUMMARY: synthesize the listener's takeaway. Don't gather new data — distill from what's known.
- act 3 MARKET REGIME BRIEFING: regime + breadth + (notable) VIX. The weekday is named in this act.
- act 4 TOP STORY DEEP DIVE: catalyst, mechanism, factor summary. Pull article body via fetch_url if needed.
- act 5 WATCHLIST PULSE: setup details for the named tickers — RS, stage, distance to pivot, setup type.
- act 6 CLOSE + THESIS: forward-looking. What's the watch-tomorrow item? What's the open question?

# Output format

When done, emit ONLY a JSON object (no preamble, no markdown fences):

{{
  "narrative_notes": "string — 2 to 4 sentences your scene's writer should know to set the tone correctly. Include the specific angle, key facts, any cross-act references the writer should weave in.",
  "carry_forward": "string — 1 to 2 sentences telling the next scene's researcher what was discovered here so they can build the storyline (NOT raw data — the next researcher gets your tool_results too)"
}}

# Taxonomy glossary — what every cluster and dimension actually measures

These are INTERNAL labels. Listeners never hear them. Use this glossary to translate any cluster_trends / dimension_trends signal you see from a tool call into plain trader meaning before you write narrative_notes or carry_forward. Sign of the score = which way today's news skews (positive ≈ toward this theme, negative ≈ away). Magnitude = strength (under 0.3 leaning, 0.3–0.6 clearly, above 0.6 loudly).

{glossary}
"""


async def research_scene(
    today: str,
    weekday: str,
    scene: dict,
    episode_brief: dict,
    world_state: dict,
    carry_forward_chain: list[dict],
) -> dict:
    """Run a tool loop for one scene; return its SceneDossier.

    Raises on total Ollama failure — the orchestrator catches and decides
    whether to fall back at the episode level. Keeping the raise here lets
    callers compose researchers (e.g. for a single-scene re-render).
    """
    label = f"Researcher act {scene['act']} {scene['name']}"
    log.info(
        "%s: starting (model=%s, max_rounds=%d)",
        label,
        OLLAMA_PODCAST_SCENE_RESEARCH_MODEL,
        PODCAST_SCENE_RESEARCH_MAX_ROUNDS,
    )

    registry = build_market_registry()
    registry.extend(_build_podcast_dossier_tools())

    user_prompt = (
        f"Research act {scene['act']} {scene['name']} for today's episode. "
        "Begin tool calls now if you need scene-specific data; otherwise emit "
        "the SceneDossier JSON immediately."
    )

    async with httpx.AsyncClient() as client:
        final_message, tool_results, rounds_used = await run_tool_loop(
            client,
            base_url=OLLAMA_BASE_URL,
            model=OLLAMA_PODCAST_SCENE_RESEARCH_MODEL,
            system=_system_prompt(
                today,
                weekday,
                scene,
                episode_brief,
                world_state,
                carry_forward_chain,
                PODCAST_SCENE_RESEARCH_MAX_ROUNDS,
            ),
            user=user_prompt,
            registry=registry,
            max_rounds=PODCAST_SCENE_RESEARCH_MAX_ROUNDS,
            max_attempts=_RETRY_MAX_ATTEMPTS,
            options={"num_predict": 1024},
            label=label,
        )

    raw = (final_message.get("content") or "").strip()
    cleaned = _strip_envelope(raw)
    parsed = _parse_dossier_json(cleaned) if cleaned else None

    if not isinstance(parsed, dict):
        if cleaned:
            log.warning(
                "%s: first parse failed (raw=%d chars, head=%r) — attempting salvage",
                label,
                len(raw),
                raw[:300],
            )
            # Cheap regex salvage first — recovers narrative_notes from
            # truncated/unclosed JSON without spending another Ollama call.
            salvaged = _salvage_partial_dossier(cleaned)
            if salvaged is not None:
                parsed = salvaged
                log.info(
                    "%s: regex salvage recovered notes=%d chars, carry=%d chars (skipping LLM repair)",
                    label,
                    len(salvaged.get("narrative_notes", "")),
                    len(salvaged.get("carry_forward", "")),
                )
            else:
                try:
                    parsed = await _repair_json_once(cleaned, label)
                except Exception as exc:
                    log.warning("%s: repair call failed: %s", label, exc)
                    parsed = None
                if isinstance(parsed, dict):
                    log.info("%s: repair succeeded — recovered valid JSON", label)
        else:
            log.warning(
                "%s: final message was empty (0 chars) — falling back to "
                "tool-results synthesis (%d tools called)",
                label,
                len(tool_results),
            )

        # Synthesis fallback: if salvage/repair didn't recover the dossier
        # (or the final message was empty to begin with), ask the model to
        # build it directly from the tool_results we already have.
        if not isinstance(parsed, dict) and tool_results:
            try:
                parsed = await _synthesize_dossier_from_tools(
                    tool_results, scene, label
                )
                if isinstance(parsed, dict):
                    log.info(
                        "%s: synthesis succeeded — dossier built from %d tool results",
                        label,
                        len(tool_results),
                    )
            except Exception as exc:
                log.warning("%s: synthesis call failed: %s", label, exc)
                parsed = None

    narrative_notes = ""
    carry_forward = ""
    if isinstance(parsed, dict):
        narrative_notes = str(parsed.get("narrative_notes", "")).strip()
        carry_forward = str(parsed.get("carry_forward", "")).strip()

    if not narrative_notes:
        raise SceneResearchError(
            f"{label}: dossier unrecoverable — narrative_notes empty after parse + "
            f"salvage + repair + synthesis "
            f"(raw={len(raw)} chars, tools_called={len(tool_results)}, "
            f"head={raw[:300]!r}). Refusing to ship a writer with no research."
        )

    log.info(
        "%s: dossier ready — rounds=%d/%d, scene_tools_called=%d, notes=%d chars, carry=%d chars",
        label,
        rounds_used,
        PODCAST_SCENE_RESEARCH_MAX_ROUNDS,
        len(tool_results),
        len(narrative_notes),
        len(carry_forward),
    )

    return {
        "act": scene["act"],
        "name": scene["name"],
        "data": tool_results,
        "narrative_notes": narrative_notes,
        "carry_forward": carry_forward,
    }
