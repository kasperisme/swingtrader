"""
Async client for DigitalOcean GenAI Agent API (OpenAI-compatible chat completions).

Docs / OpenAPI: append ``/openapi.json`` to your agent base URL.

Configuration (env vars):
    DO_GENAI_AGENT_BASE_URL   e.g. https://xxxx.agents.do-ai.run (no trailing slash)
    DO_GENAI_AGENT_API_KEY    Bearer token (required)
    DO_GENAI_AGENT_TIMEOUT    seconds (default: 120)
    DO_GENAI_AGENT_MAX_TOKENS max completion tokens (default: 4096; Qwen/reasoning needs headroom)
    DO_GENAI_AGENT_MODEL      label stored in head rows only (default: do-agent)
    DO_GENAI_AGENT_RETRIEVAL  retrieval_method: none | rewrite | step_back | sub_queries (default: none)
    DO_GENAI_AGENT_LOG_FULL_RESPONSE  if 1/true/yes, print entire HTTP body to stderr each call
"""

import json
import logging
import os
import sys
import time
from typing import Any, Optional, Union

import httpx

logger = logging.getLogger(__name__)

_DEFAULT_BASE = "https://fx4mx4weeos7jvden4iqxrqc.agents.do-ai.run"
_DEFAULT_MODEL_LABEL = "do-agent"


class GenAIAgentError(Exception):
    """Raised when the GenAI Agent API returns an error or a malformed response."""


def _base_url() -> str:
    return os.environ.get("DO_GENAI_AGENT_BASE_URL", _DEFAULT_BASE).rstrip("/")


def _want_full_response_log() -> bool:
    v = (os.environ.get("DO_GENAI_AGENT_LOG_FULL_RESPONSE") or "").strip().lower()
    return v in ("1", "true", "yes", "on")


def _emit_full_response(r: httpx.Response) -> None:
    """Print raw HTTP body to stderr for debugging (see DO_GENAI_AGENT_LOG_FULL_RESPONSE)."""
    if not _want_full_response_log():
        return
    print("[do_agent] ----- full HTTP response body -----", file=sys.stderr)
    print(r.text, file=sys.stderr)
    print("[do_agent] ----- end full response -----", file=sys.stderr)


def _slice_outer_json_object(s: str) -> Optional[str]:
    """First balanced {...} in s (string-aware); None if unclosed."""
    start = s.find("{")
    if start < 0:
        return None
    depth = 0
    i = start
    in_string = False
    escape = False
    while i < len(s):
        c = s[i]
        if in_string:
            if escape:
                escape = False
            elif c == "\\":
                escape = True
            elif c == '"':
                in_string = False
            i += 1
            continue
        if c == '"':
            in_string = True
            i += 1
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return s[start : i + 1]
        i += 1
    return None


def _parseable_json_object_slice(s: str) -> Optional[str]:
    """Return first balanced JSON object substring if ``json.loads`` succeeds."""
    blob = _slice_outer_json_object(s.strip())
    if blob is None:
        return None
    try:
        json.loads(blob)
    except json.JSONDecodeError:
        return None
    return blob


def _assistant_text(message: dict[str, Any]) -> str:
    """
    Qwen3 / reasoning models may use ``content`` for JSON, ``reasoning_content`` for
    chain-of-thought, or truncate ``content`` mid-JSON when ``max_tokens`` is hit.

    Prefer the shortest field (or combination) that contains a **complete** JSON
    object; otherwise concatenate both so downstream regex/partial salvage can run.
    """
    raw_c = message.get("content")
    raw_r = message.get("reasoning_content")
    c = str(raw_c).strip() if raw_c is not None else ""
    r = str(raw_r).strip() if raw_r is not None else ""

    for part in (c, r):
        if part and _parseable_json_object_slice(part):
            return part

    if c and r:
        combined = f"{c}\n\n{r}"
        if _parseable_json_object_slice(combined):
            return combined
        return combined

    return c or r


async def chat(
    prompt: str,
    system: str,
    model: Optional[str] = None,
    timeout: float = 120.0,
) -> tuple[str, int]:
    """
    POST /api/v1/chat/completions with system + user messages (non-streaming).

    Returns (response_text, latency_ms). The remote agent chooses the model;
    ``model`` is only used for logging metadata when passed from the scorer.
    """
    api_key = (os.environ.get("DO_GENAI_AGENT_API_KEY") or "").strip()
    if not api_key:
        raise GenAIAgentError("DO_GENAI_AGENT_API_KEY environment variable is not set")

    base = _base_url()
    url = f"{base}/api/v1/chat/completions"
    max_tokens = int(os.environ.get("DO_GENAI_AGENT_MAX_TOKENS", "4096"))
    retrieval = (os.environ.get("DO_GENAI_AGENT_RETRIEVAL", "none") or "none").strip()
    if retrieval not in ("none", "rewrite", "step_back", "sub_queries"):
        retrieval = "none"

    payload: dict[str, Any] = {
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "max_tokens": max_tokens,
        "retrieval_method": retrieval,
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    t0 = time.monotonic()
    async with httpx.AsyncClient() as client:
        try:
            r = await client.post(url, json=payload, headers=headers, timeout=timeout)
        except httpx.TimeoutException as exc:
            raise GenAIAgentError(f"GenAI Agent request timed out after {timeout}s") from exc
        except httpx.RequestError as exc:
            raise GenAIAgentError(f"GenAI Agent connection error: {exc}") from exc

    latency_ms = int((time.monotonic() - t0) * 1000)

    _emit_full_response(r)

    if r.status_code != 200:
        raise GenAIAgentError(
            f"GenAI Agent returned HTTP {r.status_code}: {r.text[:500]}"
        )

    try:
        data = r.json()
        choices = data.get("choices") or []
        if not choices:
            raise KeyError("empty choices")
        msg = choices[0].get("message") or {}
        text = _assistant_text(msg)
        if not text:
            raise KeyError("missing or empty assistant text (content and reasoning_content)")

        usage = data.get("usage") or {}
        ct = usage.get("completion_tokens")
        if ct is not None and max_tokens > 0 and int(ct) >= max_tokens:
            logger.warning(
                "[do_agent] completion_tokens=%s reached max_tokens=%s — raise "
                "DO_GENAI_AGENT_MAX_TOKENS if responses truncate (common with Qwen3 reasoning).",
                ct,
                max_tokens,
            )
    except (KeyError, ValueError, TypeError) as exc:
        raise GenAIAgentError(
            f"Malformed GenAI Agent response: {exc} — {r.text[:400]}"
        ) from exc

    resolved = model or os.environ.get("DO_GENAI_AGENT_MODEL", "") or _DEFAULT_MODEL_LABEL
    logger.debug(
        "[do_agent] model_label=%s latency=%dms response_preview=%r",
        resolved,
        latency_ms,
        text[:80],
    )
    return text, latency_ms


if __name__ == "__main__":
    import asyncio
    import pathlib

    from dotenv import load_dotenv

    load_dotenv(pathlib.Path(__file__).parent.parent / ".env")

    async def _demo():
        text, ms = await chat(
            prompt="Reply with one word: OK",
            system="You are a helpful assistant.",
        )
        print(f"Response ({ms}ms): {text}")

    asyncio.run(_demo())
