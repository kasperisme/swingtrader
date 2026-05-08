"""Per-scene writer agent.

One LLM call per scene, no tools — just write. Each writer sees:
- The full episode brief (so it knows the arc and where its scene sits).
- This scene's brief (angle, hand-off to next).
- This scene's dossier (researcher's tool_results + narrative_notes).
- The prior writer's last lines (the "tail") so the hand-off lands naturally.

Streaming /api/chat with retry on transient backend errors, mirroring the
single-agent script_generator.py. JSON parsing is permissive: strips
<think>...</think> reasoning tokens and markdown fences, then attempts a
slice from the first `{` to its matching `}`.

Returns a SceneScript matching the existing acts[] item shape so writers'
outputs concatenate directly into the script JSON.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from typing import Any

import httpx
from jinja2 import Environment, FileSystemLoader

from ..config import (
    OLLAMA_BASE_URL,
    OLLAMA_PODCAST_SCRIPT_MODEL,
    TEMPLATES_DIR,
)
from ..taxonomy_glossary import build_taxonomy_glossary
from .scene_researcher import PodcastAgentError, _is_transient_ollama_error

log = logging.getLogger(__name__)


class SceneWriterError(PodcastAgentError):
    """Raised when a writer produces no usable lines for an act.

    A scene with placeholder lines breaks the show's narrative — better to
    abort than ship an act that says "(placeholder — writer produced no
    usable lines)" through TTS.
    """


_HEARTBEAT_SECONDS = 5.0
_RETRY_MAX_ATTEMPTS = max(1, int(os.environ.get("PODCAST_SCENE_WRITER_RETRIES", "5")))
_RETRY_INITIAL_BACKOFF_S = 2.0

# Falls back through the existing model chain so a single-model setup
# Just Works without extra config.
OLLAMA_PODCAST_SCENE_WRITER_MODEL = (
    os.environ.get("OLLAMA_PODCAST_SCENE_WRITER_MODEL")
    or OLLAMA_PODCAST_SCRIPT_MODEL
)

_jinja_env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=False)


def _is_transient_ollama_error(exc: BaseException) -> bool:
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
    msg = str(exc).lower()
    return any(
        s in msg
        for s in ("502", "503", "504", "429", "408", "unexpected eof", "too many concurrent")
    )


def _retry_sleep(exc: BaseException, backoff: float) -> float:
    m = str(exc).lower()
    if "429" in m or "too many concurrent" in m:
        return max(backoff, 12.0)
    return backoff


_BREAK_TAG_RE = re.compile(r'<break time="([\d.]+s)"\s*/>')


def _repair_break_tag_quotes(raw: str) -> str:
    """Escape unescaped quotes inside `<break time="X.Xs" />` tags.

    The writer prompt instructs the model to emit `<break time="0.5s" />`
    for TTS pauses (the eleven_multilingual_v2 SSML form). When the model
    drops that verbatim into a JSON string value, the inner double quotes
    terminate the string early and break json.loads. This repair finds
    only well-formed break-time tags (digits/dots + 's' suffix) and
    rewrites the inner quotes as `\\"` so the surrounding JSON parses.
    The TTS-bound text is byte-identical after the parse-time unescape.
    """
    return _BREAK_TAG_RE.sub(r'<break time=\\"\1\\" />', raw)


def _parse_json(raw: str) -> dict | None:
    cleaned = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL)
    idx = cleaned.find("{")
    if idx == -1:
        return None
    cleaned = cleaned[idx:]
    cleaned = re.sub(r"```[a-z]*\s*$", "", cleaned.strip()).strip()
    cleaned = _repair_break_tag_quotes(cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Slice to matching brace (string-aware) for models that emit trailing
    # commentary after the JSON object.
    depth = 0
    in_string = False
    escape = False
    for i, ch in enumerate(cleaned):
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
                    return json.loads(cleaned[: i + 1])
                except json.JSONDecodeError:
                    return None
    return None


def _format_prior_tail(prior_lines: list[dict]) -> str:
    if not prior_lines:
        return ""
    return "\n".join(
        f"- {ln.get('voice', '?')}: \"{ln.get('text', '').strip()}\""
        for ln in prior_lines
    )


async def _stream_once(
    client: httpx.AsyncClient,
    messages: list[dict],
    attempt: int,
    label: str,
) -> str:
    started = time.monotonic()
    last_beat = started
    chunk_count = 0
    chunks: list[str] = []
    first_token_logged = False

    async with client.stream(
        "POST",
        f"{OLLAMA_BASE_URL}/api/chat",
        json={
            "model": OLLAMA_PODCAST_SCENE_WRITER_MODEL,
            "messages": messages,
            "stream": True,
            "options": {"temperature": 0.75, "num_predict": 2048},
        },
        timeout=600,
    ) as r:
        if r.status_code >= 400:
            body = await r.aread()
            raise SceneWriterError(
                f"Ollama {r.status_code} on /api/chat "
                f"(model={OLLAMA_PODCAST_SCENE_WRITER_MODEL}): "
                f"{body.decode(errors='replace')[:500]}"
            )
        async for line in r.aiter_lines():
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                log.warning("%s: skipping non-JSON stream line: %r", label, line[:200])
                continue
            if payload.get("error"):
                raise SceneWriterError(
                    f"Ollama stream error (model={OLLAMA_PODCAST_SCENE_WRITER_MODEL}): "
                    f"{payload['error']}"
                )
            content = payload.get("message", {}).get("content", "")
            if content:
                chunks.append(content)
                chunk_count += 1
                if not first_token_logged:
                    log.info(
                        "%s: first token at %.1fs (attempt %d)",
                        label,
                        time.monotonic() - started,
                        attempt,
                    )
                    first_token_logged = True

            now = time.monotonic()
            if now - last_beat >= _HEARTBEAT_SECONDS and not payload.get("done"):
                log.info(
                    "%s: streaming… %d chunks, %d chars (%.0fs elapsed)",
                    label,
                    chunk_count,
                    sum(len(c) for c in chunks),
                    now - started,
                )
                last_beat = now

            if payload.get("done"):
                total_chars = sum(len(c) for c in chunks)
                log.info(
                    "%s: done in %.1fs — %d chunks, %d chars",
                    label,
                    now - started,
                    chunk_count,
                    total_chars,
                )
                break
    return "".join(chunks)


async def _call_writer(
    client: httpx.AsyncClient,
    messages: list[dict],
    label: str,
    retry_error: str | None = None,
    prior_response: str | None = None,
) -> str:
    if retry_error:
        messages = messages + [
            {"role": "assistant", "content": prior_response or ""},
            {
                "role": "user",
                "content": (
                    f"That response could not be parsed: {retry_error}. "
                    "Reply again with ONLY the JSON object — no preamble, no "
                    "markdown fences, no trailing commentary. Start with { "
                    "and end with }."
                ),
            },
        ]

    backoff = _RETRY_INITIAL_BACKOFF_S
    last_exc: BaseException | None = None
    for attempt in range(1, _RETRY_MAX_ATTEMPTS + 1):
        try:
            return await _stream_once(client, messages, attempt, label)
        except Exception as exc:
            last_exc = exc
            if not _is_transient_ollama_error(exc) or attempt == _RETRY_MAX_ATTEMPTS:
                raise
            log.warning(
                "%s: attempt %d/%d failed (%s: %s) — retrying in %.0fs",
                label,
                attempt,
                _RETRY_MAX_ATTEMPTS,
                type(exc).__name__,
                str(exc)[:200],
                backoff,
            )
            await asyncio.sleep(_retry_sleep(exc, backoff))
            backoff *= 2

    assert last_exc is not None  # unreachable
    raise last_exc


# Per-line object pattern. Tolerant of:
#   - whitespace anywhere
#   - voice/text key order swapped
#   - missing trailing comma
#   - text containing escaped quotes (\")
# Captures voice and text independently so we can pair them after the fact.
_LINE_OBJECT_RE = re.compile(
    r'\{\s*'
    r'(?:"voice"\s*:\s*"(?P<voice1>[^"]+)"\s*,\s*"text"\s*:\s*"(?P<text1>(?:[^"\\]|\\.)*)"'
    r'|"text"\s*:\s*"(?P<text2>(?:[^"\\]|\\.)*)"\s*,\s*"voice"\s*:\s*"(?P<voice2>[^"]+)")'
    r'\s*\}',
    flags=re.DOTALL,
)
_SYNTHESIS_RETRY_MAX_ATTEMPTS = max(
    1, int(os.environ.get("PODCAST_SCENE_WRITER_SYNTHESIS_RETRIES", "3"))
)
_SYNTHESIS_RETRY_INITIAL_BACKOFF_S = 2.0


def _salvage_lines(raw: str) -> list[dict]:
    """Regex-extract line objects from malformed/truncated JSON.

    Useful when the model emits a partial response: closes ``{}`` early,
    drops the ``lines`` array key, or appends commentary that breaks the
    parser. Each match is converted to ``{voice, text}``. Voices outside
    primary/secondary are coerced to primary so the renderer doesn't fail
    on an unknown voice id.
    """
    out: list[dict] = []
    for m in _LINE_OBJECT_RE.finditer(raw):
        voice = (m.group("voice1") or m.group("voice2") or "primary").strip().lower()
        if voice not in ("primary", "secondary"):
            voice = "primary"
        text_raw = m.group("text1") or m.group("text2") or ""
        text = (
            text_raw.replace('\\"', '"')
            .replace("\\\\", "\\")
            .replace("\\n", "\n")
            .replace("\\t", "\t")
            .strip()
        )
        if text:
            out.append({"voice": voice, "text": text})
    return out


async def _synthesize_scene_from_inputs(
    scene: dict,
    episode_brief: dict,
    scene_dossier: dict,
    label: str,
) -> dict | None:
    """Last-resort writer fallback when the main call won't produce JSON.

    A fresh, non-tool LLM call with a stripped-down prompt: just the
    scene's act/name/angle plus the researcher's narrative_notes. We ask
    only for the ``lines`` array — no taxonomy glossary, no episode
    brief, no prior tail. Smaller surface area = higher chance the model
    actually emits the schema.
    """
    angle = (scene.get("angle") or "").strip()
    notes = (scene_dossier.get("narrative_notes") or "").strip()
    arc = (episode_brief.get("narrative_arc") or "").strip()

    user_prompt = (
        f"Write the dialogue lines for act {scene['act']} {scene['name']} of "
        "The Impact Tape, a swing-trader podcast.\n\n"
        f"Episode arc: {arc}\n"
        f"This act's angle: {angle}\n"
        f"Research notes: {notes}\n\n"
        "Write 8-14 short interleaved lines between two voices (primary, secondary). "
        "Each line MUST be its own JSON object: "
        '{"voice": "primary"|"secondary", "text": "..."}. '
        "Output ONLY this JSON object:\n"
        f'{{"act": {scene["act"]}, "name": "{scene["name"]}", "lines": [...]}}\n\n'
        "Start with { and end with }. No preamble, no markdown fences."
    )
    messages = [
        {
            "role": "system",
            "content": (
                "You are a dialogue writer. Emit exactly one JSON object: "
                '{"act": int, "name": string, "lines": [{"voice": "primary"|"secondary", "text": string}, ...]}. '
                "No preamble, no markdown."
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
                        "model": OLLAMA_PODCAST_SCENE_WRITER_MODEL,
                        "messages": messages,
                        "stream": False,
                        "options": {"num_predict": 2048, "temperature": 0.5},
                    },
                    timeout=240,
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
            return _parse_json(content)
        except Exception as exc:
            last_exc = exc
            if (
                not _is_transient_ollama_error(exc)
                or attempt == _SYNTHESIS_RETRY_MAX_ATTEMPTS
            ):
                raise
            log.warning(
                "%s: synthesis attempt %d/%d failed (%s: %s) — retrying in %.0fs",
                label,
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


def _validate_scene_script(scene: dict, raw_script: dict | None) -> dict:
    """Coerce the writer's output into a SceneScript or raise SceneWriterError.

    Empty / malformed responses raise instead of inserting a placeholder
    line — a writer that produced no usable text means the act has no
    content, and shipping the show with a missing act is a worse outcome
    than aborting.
    """
    if not isinstance(raw_script, dict):
        raw_script = {}
    lines = raw_script.get("lines") or []
    if not isinstance(lines, list) or not lines:
        raise SceneWriterError(
            f"Writer act {scene['act']} {scene['name']}: response had no "
            f"'lines' array (raw_keys={list(raw_script.keys())}). "
            "Refusing to ship the act."
        )
    cleaned: list[dict] = []
    for ln in lines:
        if not isinstance(ln, dict):
            continue
        voice = str(ln.get("voice", "primary")).strip().lower()
        if voice not in ("primary", "secondary"):
            voice = "primary"
        text = str(ln.get("text", "")).strip()
        if not text:
            continue
        cleaned.append({"voice": voice, "text": text})
    if not cleaned:
        raise SceneWriterError(
            f"Writer act {scene['act']} {scene['name']}: produced "
            f"{len(lines)} lines but none had usable text after cleaning. "
            "Refusing to ship the act."
        )
    return {"act": scene["act"], "name": scene["name"], "lines": cleaned}


async def write_scene(
    *,
    scene: dict,
    episode_brief: dict,
    world_state: dict,
    scene_dossier: dict,
    prior_tail_lines: list[dict],
) -> dict:
    """Render the prompt and call the writer model for ONE act.

    Returns a SceneScript: ``{"act": N, "name": "...", "lines": [...]}``.
    """
    label = f"Writer act {scene['act']} {scene['name']}"
    log.info(
        "%s: starting (model=%s)",
        label,
        OLLAMA_PODCAST_SCENE_WRITER_MODEL,
    )

    template = _jinja_env.get_template("scene_writer_prompt.j2")
    user_prompt = template.render(
        date=world_state.get("date", ""),
        weekday=world_state.get("weekday", ""),
        session_context=world_state.get("session_context", ""),
        scene=scene,
        episode_brief=episode_brief,
        scene_dossier=scene_dossier,
        scene_dossier_data_json=json.dumps(
            scene_dossier.get("data", {}), default=str, indent=2
        )[:6000],
        prior_tail=_format_prior_tail(prior_tail_lines),
        taxonomy_glossary=build_taxonomy_glossary(),
    )

    system_msg = (
        "You are Hans's voice writer. You write ONE act of The Impact Tape as "
        "TTS-ready dialogue between two hosts (primary + secondary). Always "
        "return ONLY valid JSON matching the requested schema. No preamble, no "
        "markdown, no explanation — start with { and end with }."
    )

    messages = [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": user_prompt},
    ]

    raw = ""
    raw2 = ""
    async with httpx.AsyncClient() as client:
        raw = await _call_writer(client, messages, label)
        parsed = _parse_json(raw)
        if parsed is None:
            log.warning(
                "%s: first parse failed (raw=%d chars, head=%r) — retrying once",
                label,
                len(raw),
                raw[:120],
            )
            raw2 = await _call_writer(
                client,
                messages,
                label,
                retry_error="Could not locate valid JSON in response",
                prior_response=raw,
            )
            parsed = _parse_json(raw2)
            if parsed is not None:
                log.info("%s: retry succeeded — recovered valid JSON", label)

    # Salvage path — when parse succeeded but the dict is empty / has no
    # lines, regex-extract line objects from whichever raw response had
    # content. Common when the model emits `{}` or wraps lines in stray
    # commentary that the brace-matcher couldn't pin.
    needs_salvage = (
        not isinstance(parsed, dict)
        or not parsed.get("lines")
        or not isinstance(parsed.get("lines"), list)
    )
    if needs_salvage:
        for source_label, source_raw in (("retry", raw2), ("first", raw)):
            if not source_raw:
                continue
            salvaged_lines = _salvage_lines(source_raw)
            if salvaged_lines:
                log.info(
                    "%s: regex salvage recovered %d lines from %s response",
                    label,
                    len(salvaged_lines),
                    source_label,
                )
                parsed = {
                    "act": scene["act"],
                    "name": scene["name"],
                    "lines": salvaged_lines,
                }
                break

    # Synthesis path — when both attempts failed and salvage couldn't pull
    # any line objects either, do a final stripped-down LLM call from the
    # scene's research notes + angle. Smaller prompt surface = higher
    # chance the model emits valid JSON.
    needs_synthesis = (
        not isinstance(parsed, dict)
        or not parsed.get("lines")
        or not isinstance(parsed.get("lines"), list)
    )
    if needs_synthesis:
        log.warning(
            "%s: parse + retry + salvage all failed — falling back to "
            "synthesis from dossier + angle",
            label,
        )
        try:
            synthesized = await _synthesize_scene_from_inputs(
                scene=scene,
                episode_brief=episode_brief,
                scene_dossier=scene_dossier,
                label=label,
            )
            if isinstance(synthesized, dict) and synthesized.get("lines"):
                parsed = synthesized
                log.info(
                    "%s: synthesis succeeded — %d lines",
                    label,
                    len(synthesized.get("lines") or []),
                )
        except Exception as exc:
            log.warning("%s: synthesis call failed: %s", label, exc)

    script = _validate_scene_script(scene, parsed)
    log.info(
        "%s: scene ready — %d lines (%d chars)",
        label,
        len(script["lines"]),
        sum(len(ln["text"]) for ln in script["lines"]),
    )
    return script
