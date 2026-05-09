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

The editor must succeed: any failure (transport error, malformed JSON,
zero junctions applied) raises ``EditorError`` and aborts the episode,
matching the pipeline-wide rule that any agent failure stops the show.

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
from .scene_researcher import PodcastAgentError

log = logging.getLogger(__name__)


class EditorError(PodcastAgentError):
    """Raised when the editor can't smooth the junctions.

    Failure modes: transport errors after retries, malformed JSON, or zero
    junctions successfully applied. The pipeline-wide rule is that any
    agent failure stops the show — the editor is no exception.
    """


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
    return f"""You are the editor for The Impact Tape, the swing-trader podcast hosted by Hans.

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
8. **Burstiness at the junction** — Don't rewrite a junction into two equal-length sentences. The hand-off should land on a length contrast: one anchor line (15–25 words) paired with a short reaction (3–6 words), not two 12-word lines from different voices.
9. **Banned formulaic transitions** — Never use "Let's dive in", "Let's dive into", "Let's unpack", "Moving on", "Now let's talk about", "Now over to", "It's worth noting", "It's important to note", "In other news", "On another note", "Speaking of which" (as a hard pivot), "Buckle up", "Strap in", "At the end of the day", "All things considered". These are LLM tells. If a writer used one in a tail/head you're rewriting, replace it with a topic-bridge that finishes the prior thought and starts the next on a reaction or question.
10. **Hedge balance** — If the junction's secondary-voice line reads as purely reactive, fold in ONE hedge or personal-stance marker ("honestly,", "I'd push back —", "I'm less sure on that", "look —", "my take —", "if you ask me,") so the analyst voice keeps an opinion, not just an echo.

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
            # think=false disables the reasoning block on glm-5.1 / qwen-think
            # / similar models. Without this, the model can spend its entire
            # output budget on `<think>...</think>` and emit zero real content
            # tokens — exactly the silent-empty pattern this editor has been
            # hitting.
            "think": False,
            "options": {"temperature": 0.6},
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


# Per-junction object pattern. Brace-aware scan because each junction
# contains nested arrays of line objects. Captures the full junction body
# starting at "after_act" so we can re-parse each one independently.
_AFTER_ACT_RE = re.compile(r'"after_act"\s*:\s*(\d+)')
# Inline line pattern (voice + text in either order, tolerates escapes).
_INLINE_LINE_RE = re.compile(
    r'\{\s*'
    r'(?:"voice"\s*:\s*"(?P<voice1>[^"]+)"\s*,\s*"text"\s*:\s*"(?P<text1>(?:[^"\\]|\\.)*)"'
    r'|"text"\s*:\s*"(?P<text2>(?:[^"\\]|\\.)*)"\s*,\s*"voice"\s*:\s*"(?P<voice2>[^"]+)")'
    r'\s*\}',
    flags=re.DOTALL,
)
_PREV_TAIL_KEY_RE = re.compile(r'"prev_act_tail"\s*:\s*\[')
_NEXT_HEAD_KEY_RE = re.compile(r'"next_act_head"\s*:\s*\[')


def _extract_lines_inside(raw: str, after_pos: int, end_pos: int) -> list[dict]:
    """Pull `{voice, text}` line objects out of a raw text window."""
    out: list[dict] = []
    for m in _INLINE_LINE_RE.finditer(raw, after_pos, end_pos):
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


def _salvage_junctions(raw: str) -> dict | None:
    """Extract `{junctions: [...]}` from malformed/partial editor output.

    Walks the raw text finding each ``"after_act": N`` marker, then for
    each marker locates the ``prev_act_tail`` / ``next_act_head`` arrays
    that follow and pulls line objects out of those windows via regex.

    Returns a dict matching the editor's expected schema, or None when
    no junctions could be recovered. Caller treats None as "synthesis
    truly failed" — anything else is good enough to apply.
    """
    if not raw:
        return None
    matches = list(_AFTER_ACT_RE.finditer(raw))
    if not matches:
        return None

    junctions: list[dict] = []
    for i, m in enumerate(matches):
        try:
            after_act = int(m.group(1))
        except ValueError:
            continue
        # Window ends at the next "after_act" or end of string.
        next_start = matches[i + 1].start() if i + 1 < len(matches) else len(raw)
        window_start = m.start()

        # Locate the two array keys inside this window.
        prev_match = _PREV_TAIL_KEY_RE.search(raw, window_start, next_start)
        next_match = _NEXT_HEAD_KEY_RE.search(raw, window_start, next_start)

        prev_lines: list[dict] = []
        next_lines: list[dict] = []
        if prev_match:
            # prev_act_tail spans from after the [ until either next_match
            # start or the window's end.
            prev_end = next_match.start() if next_match else next_start
            prev_lines = _extract_lines_inside(raw, prev_match.end(), prev_end)
        if next_match:
            next_lines = _extract_lines_inside(raw, next_match.end(), next_start)

        if not prev_lines and not next_lines:
            continue
        junctions.append(
            {
                "after_act": after_act,
                "prev_act_tail": prev_lines,
                "next_act_head": next_lines,
            }
        )

    if not junctions:
        return None
    return {"junctions": junctions}


def _format_junctions_compact(
    scenes: list[dict], junction_lines: int
) -> str:
    """Render only the lines the editor needs to rewrite.

    Each junction shows the last ``junction_lines`` lines of act N and the
    first ``junction_lines`` of act N+1, plus the act names so the model
    can ground itself. Used by the synthesis fallback so the prompt fits
    the model's attention budget when the full-draft render didn't.
    """
    by_act = {int(s.get("act", -1)): s for s in scenes if isinstance(s, dict)}
    out: list[str] = []
    for prev_act, next_act in _JUNCTIONS:
        prev = by_act.get(prev_act)
        nxt = by_act.get(next_act)
        if not prev or not nxt:
            continue
        out.append(f"--- Junction {prev_act}→{next_act} ---")
        out.append(f"END OF ACT {prev_act} {prev.get('name','')}:")
        prev_lines = (prev.get("lines") or [])[-junction_lines:]
        for ln in prev_lines:
            voice = (ln.get("voice") or "primary").strip().lower()
            text = (ln.get("text") or "").replace("\n", " ").strip()
            out.append(f"  [{voice}]: \"{text}\"")
        out.append(f"START OF ACT {next_act} {nxt.get('name','')}:")
        next_lines = (nxt.get("lines") or [])[:junction_lines]
        for ln in next_lines:
            voice = (ln.get("voice") or "primary").strip().lower()
            text = (ln.get("text") or "").replace("\n", " ").strip()
            out.append(f"  [{voice}]: \"{text}\"")
        out.append("")
    return "\n".join(out).rstrip()


async def _synthesize_junctions_compact(
    scenes: list[dict],
    episode_brief: dict,
    junction_lines: int,
    label: str,
) -> tuple[dict | None, str]:
    """Last-resort fallback when the streaming editor call returned empty.

    Uses a stripped-down prompt (only the junction context, no full draft,
    no taxonomy glossary) and a non-streaming /api/chat call so we get the
    full body in one shot. Some models silently emit zero stream tokens
    when the prompt sits at the edge of their context budget — switching
    to non-streaming and trimming the prompt usually dislodges that.
    """
    junction_block = _format_junctions_compact(scenes, junction_lines)
    user_prompt = (
        "Smooth the FIVE junctions below so consecutive acts flow as one "
        "conversation. Rewrite ONLY the tail of each prev act and the head "
        "of each next act — never the middle. Keep substance, smooth rhythm.\n\n"
        f"NARRATIVE ARC: {episode_brief.get('narrative_arc','').strip()}\n\n"
        f"JUNCTIONS:\n\n{junction_block}\n\n"
        "Output ONLY this JSON object — no preamble, no markdown:\n"
        "{\n"
        '  "junctions": [\n'
        '    {"after_act": 1, "prev_act_tail": [{"voice":"primary"|"secondary","text":"..."}, ...], "next_act_head": [{"voice":"primary"|"secondary","text":"..."}, ...]},\n'
        '    {"after_act": 2, ...},\n'
        '    {"after_act": 3, ...},\n'
        '    {"after_act": 4, ...},\n'
        '    {"after_act": 5, ...}\n'
        "  ]\n"
        "}\n\n"
        f"Each tail/head must contain {junction_lines} line object(s). "
        "Voices must stay primary or secondary. Start with { and end with }."
    )
    messages = [
        {
            "role": "system",
            "content": (
                "You are a junction smoother. Emit ONLY the JSON object "
                'matching {"junctions": [...]}. No preamble, no markdown.'
            ),
        },
        {"role": "user", "content": user_prompt},
    ]
    backoff = _RETRY_INITIAL_BACKOFF_S
    last_exc: BaseException | None = None
    last_content = ""
    for attempt in range(1, _RETRY_MAX_ATTEMPTS + 1):
        try:
            async with httpx.AsyncClient() as client:
                r = await client.post(
                    f"{OLLAMA_BASE_URL}/api/chat",
                    json={
                        "model": OLLAMA_PODCAST_EDITOR_MODEL,
                        "messages": messages,
                        "stream": False,
                        # See _stream_once: disables the model's reasoning
                        # block so the output budget isn't consumed by <think>.
                        "think": False,
                        "options": {"temperature": 0.3},
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
            if content:
                last_content = content
            if not content:
                # Treat empty content as transient — the model didn't
                # actually fail, it just didn't produce text. Retry.
                raise RuntimeError("synthesis returned empty content")

            parsed = _parse_json(content)
            if isinstance(parsed, dict):
                return parsed, content
            # Content arrived but didn't parse — try regex salvage before
            # spending another attempt. Salvage on a 330-char-with-content
            # response is much more likely to recover something useful
            # than retrying for another empty response.
            salvaged = _salvage_junctions(content)
            if salvaged is not None:
                log.info(
                    "%s: synthesis attempt %d returned unparseable JSON, "
                    "but regex salvage recovered %d junctions",
                    label,
                    attempt,
                    len(salvaged.get("junctions", [])),
                )
                return salvaged, content
            log.warning(
                "%s: synthesis attempt %d returned %d chars but neither "
                "parse nor salvage could extract junctions — head=%r",
                label,
                attempt,
                len(content),
                content[:200],
            )
            # Treat parse-failure with content as transient too — the model
            # produced output, just not in the right shape. Retry.
            raise RuntimeError("synthesis returned unparseable content")
        except Exception as exc:
            last_exc = exc
            transient = (
                _is_transient_ollama_error(exc)
                or "synthesis returned empty content" in str(exc)
                or "synthesis returned unparseable content" in str(exc)
            )
            if not transient or attempt == _RETRY_MAX_ATTEMPTS:
                # Last attempt or hard failure: surface what we have so the
                # caller can include it in the error message.
                if isinstance(exc, RuntimeError) and last_content:
                    return None, last_content
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
            await asyncio.sleep(_retry_sleep(exc, backoff))
            backoff *= 2
    assert last_exc is not None
    raise last_exc


async def edit_junctions(scenes: list[dict], episode_brief: dict) -> list[dict]:
    """Smooth the five LLM-to-LLM junctions; return the edited scenes.

    The editor is a polish pass — it rewrites only ~10 lines out of the
    full show. When it fails, ship the unedited 6-scene draft rather than
    aborting the entire episode. This is intentionally different from
    the producer/researcher/writer rule: those generate content, this
    one smooths existing content. A pipeline that won't ship without
    polish is too brittle.

    Set ``PODCAST_EDITOR_ENABLED=false`` in env to skip the editor
    entirely, or ``PODCAST_EDITOR_FAIL_HARD=true`` to revert to the
    strict-fail rule.
    """
    if len(scenes) < 2:
        log.info("Editor: fewer than 2 scenes — nothing to smooth")
        return scenes

    fail_hard = os.environ.get("PODCAST_EDITOR_FAIL_HARD", "false").lower() == "true"

    label = "Editor"
    log.info(
        "%s: starting (model=%s, %d scenes, junction_lines=%d, fail_hard=%s)",
        label,
        OLLAMA_PODCAST_EDITOR_MODEL,
        len(scenes),
        PODCAST_EDITOR_JUNCTION_LINES,
        fail_hard,
    )

    system_msg = (
        "You are Hans's voice editor. You smooth the junctions between "
        "consecutive acts of The Impact Tape. Always return ONLY valid JSON "
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

    def _give_up(reason: str) -> list[dict]:
        if fail_hard:
            raise EditorError(reason)
        log.warning(
            "%s: %s — shipping unedited 6-scene draft (PODCAST_EDITOR_FAIL_HARD=true to abort instead)",
            label,
            reason,
        )
        return scenes

    raw = ""
    primary_call_failed = False
    try:
        async with httpx.AsyncClient() as client:
            raw = await _call_editor(client, messages, label)
    except Exception as exc:
        log.warning(
            "%s: streaming call failed (%s: %s) — will try compact synthesis",
            label,
            type(exc).__name__,
            exc,
        )
        primary_call_failed = True

    parsed = _parse_json(raw) if raw else None
    if not isinstance(parsed, dict) and raw:
        # Streaming returned content that didn't parse — try salvage
        # before falling through to synthesis.
        salvaged = _salvage_junctions(raw)
        if salvaged is not None:
            log.info(
                "%s: streaming response unparseable, but regex salvage "
                "recovered %d junctions",
                label,
                len(salvaged.get("junctions", [])),
            )
            parsed = salvaged

    # Synthesis fallback when the streaming call returned empty / unparseable
    # or raised. Uses a stripped-down prompt + non-streaming chat — both
    # changes meaningfully reduce the chance of a content-empty response.
    synthesis_raw = ""
    if not isinstance(parsed, dict):
        log.warning(
            "%s: streaming response unusable (raw=%d chars, head=%r) — "
            "falling back to compact synthesis",
            label,
            len(raw),
            raw[:200],
        )
        try:
            parsed, synthesis_raw = await _synthesize_junctions_compact(
                scenes,
                episode_brief,
                PODCAST_EDITOR_JUNCTION_LINES,
                label,
            )
            if isinstance(parsed, dict):
                log.info(
                    "%s: synthesis recovered junctions JSON (%d chars raw)",
                    label,
                    len(synthesis_raw),
                )
        except Exception as exc:
            return _give_up(
                f"streaming + synthesis both failed "
                f"(streaming_raw={len(raw)} chars, primary_call_failed={primary_call_failed}, "
                f"synthesis_error={type(exc).__name__}: {exc})"
            )

    if not isinstance(parsed, dict):
        return _give_up(
            f"response was not parseable JSON after synthesis "
            f"(streaming_raw={len(raw)} chars, "
            f"synthesis_raw={len(synthesis_raw)} chars, "
            f"streaming_head={raw[:200]!r}, "
            f"synthesis_head={synthesis_raw[:400]!r})"
        )

    edited, applied = _apply_junction_edits(
        scenes, parsed, PODCAST_EDITOR_JUNCTION_LINES
    )
    if applied == 0:
        return _give_up(
            f"zero junctions applied out of {len(_JUNCTIONS)} "
            f"(parsed_keys={list(parsed.keys())})"
        )
    log.info(
        "%s: %d/%d junctions applied",
        label,
        applied,
        len(_JUNCTIONS),
    )
    return edited
