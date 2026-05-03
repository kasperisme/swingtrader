from __future__ import annotations

import json
import logging
import re
import time
from datetime import date
from pathlib import Path

import httpx
from jinja2 import Environment, FileSystemLoader

from .config import (
    ELEVENLABS_PRIMARY_VOICE_NAME,
    ELEVENLABS_SECONDARY_VOICE_NAME,
    OLLAMA_PODCAST_EXTRACT_MODEL,
    OLLAMA_PODCAST_SCRIPT_MODEL,
    OLLAMA_BASE_URL,
    SCRIPTS_DIR,
    TEMPLATES_DIR,
)

log = logging.getLogger(__name__)

_HEARTBEAT_SECONDS = 5.0  # progress log interval during streaming

_jinja_env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=False)


class PodcastScriptError(Exception):
    pass


def _welcome_act() -> dict | None:
    """Deterministic intro scene where each voice greets by name.

    Returns an act dict ({"act": 0, "name": "WELCOME", "lines": [...]}) when
    both voice names are configured, otherwise None (caller skips injection).
    Act 0 sorts before the LLM-generated acts 1–5 in the renderer's filename
    scheme, so the welcome plays first without any pipeline changes.
    """
    primary = (ELEVENLABS_PRIMARY_VOICE_NAME or "").strip()
    secondary = (ELEVENLABS_SECONDARY_VOICE_NAME or "").strip()
    if not primary or not secondary:
        return None
    return {
        "act": 0,
        "name": "WELCOME",
        "lines": [
            {
                "voice": "primary",
                "text": (
                    f"Welcome to News Impact Daily — your AI-powered market briefing, "
                    f"fresh every trading day. I'm {primary}."
                ),
            },
            {
                "voice": "secondary",
                "text": (
                    f"And I'm {secondary}. [PAUSE] Here's what moved markets today."
                ),
            },
        ],
    }


async def _validate_data(client: httpx.AsyncClient, data: dict) -> dict:
    """Use extraction model to validate and clean input data.

    Local models can take 30-90s on a cold load, so the timeout matches the
    script-generation step. On any error (timeout, 404, malformed response)
    fall back to the unmodified input — validation is best-effort.
    """
    prompt = (
        "Validate and clean this market data dict. "
        "Remove null values, fill missing numeric fields with sensible defaults. "
        "Ensure impact_score is between 0 and 10. "
        "Return ONLY valid JSON, no explanation.\n\n"
        f"{json.dumps(data)}"
    )
    started = time.monotonic()
    log.info(
        "Validation: model=%s prompt=%d chars",
        OLLAMA_PODCAST_EXTRACT_MODEL,
        len(prompt),
    )
    try:
        r = await client.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json={
                "model": OLLAMA_PODCAST_EXTRACT_MODEL,
                "prompt": prompt,
                "stream": False,
            },
            timeout=300,
        )
        elapsed = time.monotonic() - started
        if r.status_code >= 400:
            log.warning(
                "Validation skipped after %.1fs — Ollama %s: %s",
                elapsed,
                r.status_code,
                r.text[:300],
            )
            return data
        raw = r.json().get("response", "")
        cleaned = _parse_json(raw)
        if cleaned is None:
            log.warning(
                "Validation: model returned unparseable JSON after %.1fs (%d chars), using raw input",
                elapsed,
                len(raw),
            )
            return data
        log.info(
            "Validation done in %.1fs — response=%d chars, %d keys retained",
            elapsed,
            len(raw),
            len(cleaned),
        )
        return cleaned
    except (httpx.TimeoutException, httpx.HTTPError) as exc:
        elapsed = time.monotonic() - started
        log.warning(
            "Validation skipped after %.1fs — %s: %s", elapsed, type(exc).__name__, exc
        )
        return data


async def _call_script_model(
    client: httpx.AsyncClient, messages: list[dict], retry_error: str | None = None
) -> str:
    """Call the script model via the streaming chat endpoint.

    Streaming keeps the connection alive token-by-token, sidestepping the
    ~60s internal timeout on Ollama's local-daemon → cloud proxy when long
    generations would otherwise stall waiting for a single buffered response.
    Emits a heartbeat log every few seconds so long generations don't look hung.
    """
    if retry_error:
        messages = messages + [
            {"role": "assistant", "content": messages[-1].get("content", "")},
            {
                "role": "user",
                "content": f"JSON parse error: {retry_error}\nReturn only valid JSON, no other text.",
            },
        ]

    prompt_chars = sum(len(m.get("content", "")) for m in messages)
    log.info(
        "Script model: %s — streaming chat (prompt=%d chars across %d msgs)%s",
        OLLAMA_PODCAST_SCRIPT_MODEL,
        prompt_chars,
        len(messages),
        " [retry]" if retry_error else "",
    )
    started = time.monotonic()
    last_beat = started
    chunk_count = 0
    chunks: list[str] = []
    first_token_logged = False

    async with client.stream(
        "POST",
        f"{OLLAMA_BASE_URL}/api/chat",
        json={
            "model": OLLAMA_PODCAST_SCRIPT_MODEL,
            "messages": messages,
            "stream": True,
            "options": {"temperature": 0.75, "num_predict": 4096},
        },
        timeout=600,
    ) as r:
        if r.status_code >= 400:
            body = await r.aread()
            raise PodcastScriptError(
                f"Ollama {r.status_code} on /api/chat "
                f"(model={OLLAMA_PODCAST_SCRIPT_MODEL}): {body.decode(errors='replace')[:500]}"
            )
        async for line in r.aiter_lines():
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                log.warning("Skipping non-JSON stream line: %r", line[:200])
                continue
            if payload.get("error"):
                raise PodcastScriptError(
                    f"Ollama stream error (model={OLLAMA_PODCAST_SCRIPT_MODEL}): {payload['error']}"
                )
            content = payload.get("message", {}).get("content", "")
            if content:
                chunks.append(content)
                chunk_count += 1
                if not first_token_logged:
                    log.info(
                        "Script model: first token at %.1fs", time.monotonic() - started
                    )
                    first_token_logged = True

            now = time.monotonic()
            if now - last_beat >= _HEARTBEAT_SECONDS and not payload.get("done"):
                log.info(
                    "Script model: streaming… %d chunks, %d chars (%.0fs elapsed)",
                    chunk_count,
                    sum(len(c) for c in chunks),
                    now - started,
                )
                last_beat = now

            if payload.get("done"):
                total_chars = sum(len(c) for c in chunks)
                log.info(
                    "Script model: done in %.1fs — %d chunks, %d chars (%.0f tokens/s est.)",
                    now - started,
                    chunk_count,
                    total_chars,
                    (total_chars / 4.0)
                    / max(now - started, 0.001),  # ~4 chars/token rough est
                )
                break
    return "".join(chunks)


def _parse_json(raw: str) -> dict | None:
    """Strip think blocks and markdown fences, attempt JSON parse."""
    # Strip <think>...</think> reasoning tokens
    cleaned = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL)
    # Everything before the first {
    idx = cleaned.find("{")
    if idx == -1:
        return None
    cleaned = cleaned[idx:]
    # Strip trailing markdown fences
    cleaned = re.sub(r"```[a-z]*\s*$", "", cleaned.strip()).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return None


async def generate_script(data: dict) -> dict:
    today = data.get("date", str(date.today()))
    SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    pipeline_start = time.monotonic()
    log.info("Pipeline start: date=%s, input=%d top-level keys", today, len(data))

    async with httpx.AsyncClient() as client:
        clean_data = await _validate_data(client, data)

        template = _jinja_env.get_template("script_prompt.j2")
        user_prompt = template.render(data=clean_data)
        log.debug("Rendered user prompt: %d chars", len(user_prompt))

        system_msg = (
            "You are Hans, the AI host of NewsImpact Daily podcast. "
            "You write engaging, information-dense market intelligence scripts. "
            "Always return ONLY valid JSON matching the specified structure. "
            "No preamble, no markdown, no explanation — start with { and end with }."
        )

        messages = [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_prompt},
        ]

        raw = await _call_script_model(client, messages)
        script = _parse_json(raw)

        if script is None:
            log.warning(
                "First parse failed (raw=%d chars, head=%r) — retrying once",
                len(raw),
                raw[:120],
            )
            raw2 = await _call_script_model(
                client, messages, retry_error="Could not locate valid JSON in response"
            )
            script = _parse_json(raw2)
            if script is not None:
                log.info("Retry succeeded — recovered valid JSON")

        if script is None:
            raise PodcastScriptError(
                f"Script model returned unparseable JSON after retry. Raw: {raw[:500]}"
            )

    welcome = _welcome_act()
    if welcome is not None:
        existing = script.get("acts") or []
        # Don't double-inject if a previous run already prepended a welcome act.
        if not (existing and existing[0].get("act") == 0):
            script["acts"] = [welcome] + existing
            log.info(
                "Welcome act prepended — primary=%r, secondary=%r",
                ELEVENLABS_PRIMARY_VOICE_NAME,
                ELEVENLABS_SECONDARY_VOICE_NAME,
            )
    else:
        log.info(
            "Welcome act skipped — set ELEVENLABS_PRIMARY_VOICE_NAME and "
            "ELEVENLABS_SECONDARY_VOICE_NAME to enable"
        )

    out_path = SCRIPTS_DIR / f"{today}.json"
    serialized = json.dumps(script, indent=2)
    out_path.write_text(serialized)
    log.info(
        "Pipeline done in %.1fs — script saved (%d bytes, %d top-level keys) → %s",
        time.monotonic() - pipeline_start,
        len(serialized),
        len(script),
        out_path,
    )
    return script
