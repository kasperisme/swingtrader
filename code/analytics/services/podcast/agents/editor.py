"""Editor agent — junction smoothing pass.

After all six scene writers run, the editor reads the full draft and
rewrites only the last 1–2 lines of each act and the first 1–2 lines of
the next. The middle of each act is left untouched. Five junctions:
1→2, 2→3, 3→4, 4→5, 5→6.

This is a smoother, not a rewriter. Its job:
- Make the hand-offs between consecutive acts land naturally (no hard cuts).
- Kill cross-act repetition (the writers ran sequentially with carry-forward,
  but the writer model can still mirror a stat from a prior scene's tail).
- Keep the narrative arc consistent across junctions.

The editor is best-effort: failures don't take down the episode. The
pipeline simply ships the unedited 6-scene draft when the editor errors.

Output schema:

    {
      "junctions": [
        {
          "after_act": 1,
          "prev_act_tail": [{"voice": "primary"|"secondary", "text": "..."}, ...],
          "next_act_head": [{"voice": "primary"|"secondary", "text": "..."}, ...]
        },
        ... (after_act in 1..5)
      ]
    }
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time

import httpx

from ..config import OLLAMA_BASE_URL, OLLAMA_PODCAST_SCRIPT_MODEL

log = logging.getLogger(__name__)


_HEARTBEAT_SECONDS = 5.0
_RETRY_MAX_ATTEMPTS = max(1, int(os.environ.get("PODCAST_EDITOR_RETRIES", "5")))
_RETRY_INITIAL_BACKOFF_S = 2.0

# How many lines per side the editor is asked to rewrite by default. The
# model may return fewer (e.g. one interjection) or more (capped at
# _MAX_LINES_PER_SIDE) to handle natural speech variations.
PODCAST_EDITOR_JUNCTION_LINES = int(
    os.environ.get("PODCAST_EDITOR_JUNCTION_LINES", "2")
)
_MAX_LINES_PER_SIDE = 4

OLLAMA_PODCAST_EDITOR_MODEL = (
    os.environ.get("OLLAMA_PODCAST_EDITOR_MODEL") or OLLAMA_PODCAST_SCRIPT_MODEL
)

# The five LLM-to-LLM junctions. The deterministic HOOK / WELCOME /
# SIGN_OFF acts bookend the show and are not edited.
_JUNCTIONS = [(1, 2), (2, 3), (3, 4), (4, 5), (5, 6)]


class EditorError(Exception):
    pass


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
    """Escape unescaped quotes inside `<break time="X.Xs" />` SSML tags.

    Same fix as scene_writer._repair_break_tag_quotes — duplicated rather
    than imported to keep the agent modules independent.
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


def _format_full_draft(scenes: list[dict]) -> str:
    out: list[str] = []
    for scene in scenes:
        out.append(f"ACT {scene['act']} {scene['name']}:")
        for i, ln in enumerate(scene.get("lines") or [], start=1):
            text = (ln.get("text") or "").replace("\n", " ").strip()
            voice = (ln.get("voice") or "primary").strip().lower()
            out.append(f"  L{i} [{voice}]: \"{text}\"")
        out.append("")
    return "\n".join(out).rstrip()


def _system_prompt(
    episode_brief: dict,
    scenes: list[dict],
    junction_lines: int,
) -> str:
    return f"""You are the editor for NewsImpact Daily, the swing-trader podcast hosted by Hans.

Six writers have produced their acts in sequence. Your job is to smooth the JUNCTIONS between consecutive acts so the show flows as one continuous conversation, not six pasted segments.

# Episode-level context

EPISODE TITLE: {episode_brief.get('episode_title', '').strip()}
NARRATIVE ARC: {episode_brief.get('narrative_arc', '').strip()}

# The full draft

{_format_full_draft(scenes)}

# Your job

For each of the FIVE junctions (1→2, 2→3, 3→4, 4→5, 5→6), rewrite:
- prev_act_tail — the last {junction_lines} line(s) of act N
- next_act_head — the first {junction_lines} line(s) of act N+1

These rewritten lines REPLACE the original tail/head when applied. The middle of each act is untouched.

# Constraints (read twice)

1. **Surgical scope** — Edit ONLY the junction lines. Do NOT rewrite middle lines. Do NOT modify acts you weren't asked to.
2. **Don't change the substance** — Keep the same data, ticker, headline, conclusion. Smooth the rhythm of the hand-off, don't replace its content.
3. **Voice stability** — Each line's voice (primary or secondary) stays the same as the original line in that position. Don't reassign voices.
4. **Line count** — Default to returning {junction_lines} lines per side. You MAY return 1 (e.g. an interjection that absorbs two beats into one) or up to {_MAX_LINES_PER_SIDE} (e.g. splitting one long sentence into two short ones), but never more than {_MAX_LINES_PER_SIDE}.
5. **One-fact-one-act** — If a head line repeats a stat already stated earlier in the show, rewrite it to gesture at the fact indirectly ("after that volatility move we just talked about") rather than restating the number.
6. **Date/weekday rule** — The weekday is spoken aloud only in act 3. If you spot the weekday name in act 1, 2, 4, 5, or 6 in the lines you rewrite, replace it with a relative reference ("today", "yesterday", "tomorrow").
7. **Conversational hand-offs** — Use questions, interjections, co-completions to thread the junction. Avoid hard stops at the tail or fresh announcements at the head.

# Output format

Emit ONLY a JSON object (no preamble, no markdown fences, no explanation). Start with {{ and end with }}.

{{
  "junctions": [
    {{
      "after_act": 1,
      "prev_act_tail": [
        {{ "voice": "primary"|"secondary", "text": "string — TTS-ready" }},
        ...
      ],
      "next_act_head": [
        {{ "voice": "primary"|"secondary", "text": "string — TTS-ready" }},
        ...
      ]
    }},
    {{ "after_act": 2, ... }},
    {{ "after_act": 3, ... }},
    {{ "after_act": 4, ... }},
    {{ "after_act": 5, ... }}
  ]
}}"""


def _clean_lines(raw_lines, fallback_voice: str | None = None) -> list[dict]:
    """Coerce editor output lines into the writer's line shape.

    Drops empty/non-dict entries and clamps voice strings to
    primary/secondary. Returns at most _MAX_LINES_PER_SIDE.
    """
    if not isinstance(raw_lines, list):
        return []
    out: list[dict] = []
    for ln in raw_lines:
        if not isinstance(ln, dict):
            continue
        text = str(ln.get("text", "")).strip()
        if not text:
            continue
        voice = str(ln.get("voice", fallback_voice or "primary")).strip().lower()
        if voice not in ("primary", "secondary"):
            voice = fallback_voice or "primary"
        out.append({"voice": voice, "text": text})
        if len(out) >= _MAX_LINES_PER_SIDE:
            break
    return out


def _apply_junction_edits(
    scenes: list[dict], parsed: dict, junction_lines: int
) -> tuple[list[dict], int]:
    """Apply editor edits surgically; return (new_scenes, applied_count).

    Tolerant of partial output: silently skips junctions the editor didn't
    return, malformed entries, and edits that target non-existent acts.
    """
    by_act = {s["act"]: s for s in scenes}
    junctions = parsed.get("junctions") or []
    applied = 0

    for j in junctions:
        if not isinstance(j, dict):
            continue
        after = j.get("after_act")
        try:
            after = int(after)
        except (TypeError, ValueError):
            continue
        if after < 1 or after > 5:
            continue
        prev = by_act.get(after)
        nxt = by_act.get(after + 1)
        if not prev or not nxt:
            continue

        prev_lines = list(prev.get("lines") or [])
        nxt_lines = list(nxt.get("lines") or [])
        if not prev_lines or not nxt_lines:
            continue

        # Use the original tail/head voices as fallbacks so a missing
        # voice field doesn't silently flip the speaker.
        orig_tail_voice = (
            prev_lines[-1].get("voice") if prev_lines else None
        )
        orig_head_voice = nxt_lines[0].get("voice") if nxt_lines else None

        clean_tail = _clean_lines(j.get("prev_act_tail"), orig_tail_voice)
        clean_head = _clean_lines(j.get("next_act_head"), orig_head_voice)

        if clean_tail:
            replace_count = min(len(prev_lines), max(junction_lines, len(clean_tail)))
            # Replace the last `replace_count` lines with the clean tail. If
            # the editor returned fewer lines than the slice, the act
            # naturally shrinks at the junction by that delta.
            if len(clean_tail) <= replace_count:
                prev["lines"] = prev_lines[:-replace_count] + clean_tail
            else:
                prev["lines"] = prev_lines[:-replace_count] + clean_tail[
                    -replace_count:
                ]

        if clean_head:
            replace_count = min(len(nxt_lines), max(junction_lines, len(clean_head)))
            if len(clean_head) <= replace_count:
                nxt["lines"] = clean_head + nxt_lines[replace_count:]
            else:
                nxt["lines"] = clean_head[:replace_count] + nxt_lines[replace_count:]

        if clean_tail or clean_head:
            applied += 1
            log.info(
                "Editor: applied junction %d→%d (tail=%d→%d, head=%d→%d)",
                after,
                after + 1,
                len(prev_lines),
                len(prev["lines"]),
                len(nxt_lines),
                len(nxt["lines"]),
            )

    return scenes, applied


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
            "model": OLLAMA_PODCAST_EDITOR_MODEL,
            "messages": messages,
            "stream": True,
            "options": {"temperature": 0.6, "num_predict": 3072},
        },
        timeout=600,
    ) as r:
        if r.status_code >= 400:
            body = await r.aread()
            raise EditorError(
                f"Ollama {r.status_code} on /api/chat "
                f"(model={OLLAMA_PODCAST_EDITOR_MODEL}): "
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
                raise EditorError(
                    f"Ollama stream error (model={OLLAMA_PODCAST_EDITOR_MODEL}): "
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


async def _call_editor(
    client: httpx.AsyncClient, messages: list[dict], label: str
) -> str:
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

    assert last_exc is not None
    raise last_exc


async def edit_junctions(scenes: list[dict], episode_brief: dict) -> list[dict]:
    """Smooth the five LLM-to-LLM junctions; return the edited scenes.

    Does not raise on editor failure — logs and returns the input scenes
    unchanged so the pipeline ships the un-smoothed draft rather than no
    episode at all.
    """
    if len(scenes) < 2:
        log.info("Editor: fewer than 2 scenes — nothing to smooth")
        return scenes

    label = "Editor"
    log.info(
        "%s: starting (model=%s, %d scenes, junction_lines=%d)",
        label,
        OLLAMA_PODCAST_EDITOR_MODEL,
        len(scenes),
        PODCAST_EDITOR_JUNCTION_LINES,
    )

    system_msg = (
        "You are Hans's voice editor. You smooth the junctions between "
        "consecutive acts of NewsImpact Daily. Always return ONLY valid JSON "
        "matching the requested schema. No preamble, no markdown — start "
        "with { and end with }."
    )
    user_prompt = _system_prompt(
        episode_brief, scenes, PODCAST_EDITOR_JUNCTION_LINES
    )

    messages = [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": user_prompt},
    ]

    try:
        async with httpx.AsyncClient() as client:
            raw = await _call_editor(client, messages, label)
    except Exception as exc:
        log.error(
            "%s: failed (%s: %s) — shipping unedited draft",
            label,
            type(exc).__name__,
            exc,
        )
        return scenes

    parsed = _parse_json(raw)
    if not isinstance(parsed, dict):
        log.warning(
            "%s: response was not parseable JSON (head=%r) — shipping unedited draft",
            label,
            raw[:200],
        )
        return scenes

    edited, applied = _apply_junction_edits(
        scenes, parsed, PODCAST_EDITOR_JUNCTION_LINES
    )
    log.info(
        "%s: %d/%d junctions applied",
        label,
        applied,
        len(_JUNCTIONS),
    )
    return edited
