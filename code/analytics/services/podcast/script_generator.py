from __future__ import annotations

import asyncio
import json
import logging
import os
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
from .taxonomy_glossary import build_taxonomy_glossary

log = logging.getLogger(__name__)

_HEARTBEAT_SECONDS = 5.0  # progress log interval during streaming
_RETRY_MAX_ATTEMPTS = max(1, int(os.environ.get("PODCAST_OLLAMA_RETRIES", "5")))
_RETRY_INITIAL_BACKOFF_S = 2.0


def _is_transient_ollama_error(exc: BaseException) -> bool:
    """True for errors a retry can plausibly recover from.

    Covers Ollama Cloud's flapping 502/503/504/429, "too many concurrent
    requests", "unexpected EOF", plus transport failures (drops, timeouts).
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
    msg = str(exc).lower()
    return any(
        s in msg
        for s in (
            "502",
            "503",
            "504",
            "429",
            "408",
            "unexpected eof",
            "too many concurrent",
        )
    )


def _ollama_retry_sleep_seconds(exc: BaseException, backoff: float) -> float:
    """Longer pause after rate limits so the next attempt is less likely to 429."""
    m = str(exc).lower()
    if "429" in m or "too many concurrent" in m:
        return max(backoff, 12.0)
    return backoff

_jinja_env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=False)


class PodcastScriptError(Exception):
    pass


def _hook_act(
    article_count: int | None = None,
    source_count: int | None = None,
) -> dict:
    """Pre-welcome attention grabber, played under a soft music bed.

    Marked with bg_music=True so the episode packager mixes a low-volume
    background track (ASSETS_DIR/hook_music.mp3) under the voice. Sits at
    act -1 so it plays before the act 0 welcome. The "I have read N
    articles from M sources" clause is dropped when article_count is
    missing or zero so the line never reads "I have read 0 articles". The
    "from M sources" sub-clause is dropped independently when source_count
    is missing or zero.
    """
    if article_count and article_count > 0:
        articles_phrase = (
            f"{article_count:,} article" + ("" if article_count == 1 else "s")
        )
        if source_count and source_count > 0:
            sources_phrase = (
                f"{source_count:,} source" + ("" if source_count == 1 else "s")
            )
            article_clause = (
                f" I have read {articles_phrase} from {sources_phrase} "
                "in the last 24 hours. <break time=\"0.5s\" />"
            )
        else:
            article_clause = (
                f" I have read {articles_phrase} in the last 24 hours. <break time=\"0.5s\" />"
            )
    else:
        article_clause = ""

    return {
        "act": -1,
        "name": "HOOK",
        "bg_music": True,
        "lines": [
            {
                "voice": "hook",
                "text": (
                    "This is Hans — the orchestrator behind News Impact Screener. "
                    "<break time=\"0.5s\" /> I don't sleep, I don't have a P and L, "
                    "and I read every 8-K filed between yesterday's close "
                    "and this morning's coffee. <break time=\"0.5s\" /> Three of them matter."
                    f"{article_clause} Let's go."
                ),
            },
        ],
    }


def _signoff_act() -> dict:
    """Deterministic show-close in the hook voice, bookending the cold-open hook.

    Sits at act 7 so it sorts after the LLM-generated CLOSE + THESIS (act 6)
    in the renderer's filename scheme. Uses voice="hook" so the same Hans
    orchestrator persona that opens the show also closes it.
    """
    return {
        "act": 7,
        "name": "SIGN_OFF",
        "lines": [
            {
                "voice": "hook",
                "text": (
                    "This was Hans. <break time=\"0.5s\" /> "
                    "Markets close — I don't. <break time=\"0.5s\" /> "
                    "I'll be back tomorrow with whatever moves overnight. "
                    "<break time=\"0.5s\" /> Trade well."
                ),
            },
        ],
    }


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
                    f"Welcome to The Impact Tape — your AI-powered market briefing, "
                    f"fresh every trading day. I'm {primary}, and as always —"
                ),
            },
            {
                "voice": "secondary",
                "text": (
                    f"— I'm {secondary}. Good to be back."
                ),
            },
            {
                "voice": "primary",
                "text": (
                    f"Got a lot to get through today. <break time=\"0.5s\" /> "
                    f"You ready?"
                ),
            },
            {
                "voice": "secondary",
                "text": (
                    f"Always. Let's get into what moved markets today."
                ),
            },
        ],
    }


async def _validate_data(client: httpx.AsyncClient, data: dict) -> dict:
    """Use extraction model to validate and clean input data.

    Streams from Ollama /api/generate so the connection stays alive past
    the cloud proxy's ~60s idle timeout (the same reason the script step
    streams). Best-effort: on any error or unparseable response, falls
    back to the unmodified input.
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
        "Validation: model=%s prompt=%d chars (streaming)",
        OLLAMA_PODCAST_EXTRACT_MODEL,
        len(prompt),
    )
    try:
        chunks: list[str] = []
        last_beat = started
        first_token_logged = False
        async with client.stream(
            "POST",
            f"{OLLAMA_BASE_URL}/api/generate",
            json={
                "model": OLLAMA_PODCAST_EXTRACT_MODEL,
                "prompt": prompt,
                "stream": True,
            },
            timeout=600,
        ) as r:
            if r.status_code >= 400:
                body = await r.aread()
                log.warning(
                    "Validation skipped after %.1fs — Ollama %s: %s",
                    time.monotonic() - started,
                    r.status_code,
                    body.decode(errors="replace")[:300],
                )
                return data
            async for line in r.aiter_lines():
                if not line.strip():
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if payload.get("error"):
                    log.warning(
                        "Validation skipped — Ollama stream error: %s",
                        payload["error"],
                    )
                    return data
                token = payload.get("response", "")
                if token:
                    chunks.append(token)
                    if not first_token_logged:
                        log.info(
                            "Validation: first token at %.1fs",
                            time.monotonic() - started,
                        )
                        first_token_logged = True
                now = time.monotonic()
                if now - last_beat >= _HEARTBEAT_SECONDS and not payload.get("done"):
                    log.info(
                        "Validation: streaming… %d chars (%.0fs elapsed)",
                        sum(len(c) for c in chunks),
                        now - started,
                    )
                    last_beat = now
                if payload.get("done"):
                    break

        elapsed = time.monotonic() - started
        raw = "".join(chunks)
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


async def _stream_chat_once(
    client: httpx.AsyncClient,
    messages: list[dict],
    attempt: int,
) -> str:
    """One streaming chat attempt. Returns joined response, or raises.

    Status-4xx and stream-level error payloads raise PodcastScriptError;
    network drops bubble up as httpx exceptions. The caller decides whether
    those are transient (retry) or permanent.
    """
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
                        "Script model: first token at %.1fs (attempt %d)",
                        time.monotonic() - started,
                        attempt,
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


async def _call_script_model(
    client: httpx.AsyncClient, messages: list[dict], retry_error: str | None = None
) -> str:
    """Call the script model via the streaming chat endpoint with retry.

    Streaming keeps the connection alive token-by-token, sidestepping the
    ~60s internal timeout on Ollama's local-daemon → cloud proxy. On top of
    that, retries up to _RETRY_MAX_ATTEMPTS on transient backend errors
    (502/503/504/429/EOF/network drops) with exponential backoff. Permanent
    errors (4xx auth, parse, etc.) raise on the first failure.
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

    backoff = _RETRY_INITIAL_BACKOFF_S
    last_exc: BaseException | None = None
    for attempt in range(1, _RETRY_MAX_ATTEMPTS + 1):
        try:
            return await _stream_chat_once(client, messages, attempt)
        except Exception as exc:
            last_exc = exc
            if not _is_transient_ollama_error(exc) or attempt == _RETRY_MAX_ATTEMPTS:
                raise
            log.warning(
                "Script model: attempt %d/%d failed (%s: %s) — retrying in %.0fs",
                attempt,
                _RETRY_MAX_ATTEMPTS,
                type(exc).__name__,
                str(exc)[:200],
                backoff,
            )
            delay = _ollama_retry_sleep_seconds(exc, backoff)
            await asyncio.sleep(delay)
            backoff *= 2

    assert last_exc is not None  # unreachable
    raise last_exc


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

        # Space out Ollama Cloud calls (validation /generate then script /chat)
        # to reduce 429 "too many concurrent requests" on the same account.
        gap_s = float(os.environ.get("PODCAST_OLLAMA_CHAT_GAP_S", "3"))
        if gap_s > 0:
            await asyncio.sleep(gap_s)

        template = _jinja_env.get_template("script_prompt.j2")
        user_prompt = template.render(
            data=clean_data,
            taxonomy_glossary=build_taxonomy_glossary(),
        )
        log.debug("Rendered user prompt: %d chars", len(user_prompt))

        system_msg = (
            "You are Hans, the AI host of The Impact Tape podcast. "
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

    # Preserve articles_24h / sources_24h across the validation step — the
    # cleaner model can silently drop fields it doesn't recognize.
    articles_24h = int(
        clean_data.get("articles_24h") or data.get("articles_24h") or 0
    )
    sources_24h = int(
        clean_data.get("sources_24h") or data.get("sources_24h") or 0
    )
    hook = _hook_act(article_count=articles_24h, source_count=sources_24h)
    existing = script.get("acts") or []
    if not (existing and existing[0].get("name") == "HOOK"):
        script["acts"] = [hook] + existing
        log.info(
            "Hook act prepended (bg_music enabled, articles_24h=%d, sources_24h=%d)",
            articles_24h,
            sources_24h,
        )

    existing = script.get("acts") or []
    if not any(a.get("name") == "SIGN_OFF" for a in existing):
        script["acts"] = existing + [_signoff_act()]
        log.info("Sign-off act appended (hook voice — bookends the cold-open hook)")

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
