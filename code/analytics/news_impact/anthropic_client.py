"""
Async Anthropic API client for cloud LLM inference.

Drop-in replacement for ollama_client.chat — same signature, same return type.

Configuration (env vars):
    ANTHROPIC_API_KEY         required
    ANTHROPIC_IMPACT_MODEL    model ID  (default: claude-haiku-4-5-20251001)
"""

import logging
import os
import time
from typing import Optional

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "claude-haiku-4-5-20251001"


class AnthropicError(Exception):
    """Raised when the Anthropic API returns an error or a malformed response."""


async def chat(
    prompt: str,
    system: str,
    model: Optional[str] = None,
    timeout: float = 60.0,
) -> tuple[str, int]:
    """
    Send a chat request to the Anthropic API.

    Parameters
    ----------
    prompt  : user message content
    system  : system message content
    model   : model ID; defaults to ANTHROPIC_IMPACT_MODEL env var → claude-haiku-4-5-20251001
    timeout : seconds before the request times out

    Returns
    -------
    (response_text, latency_ms)

    Raises
    ------
    AnthropicError  if the API call fails or the response is malformed
    """
    try:
        import anthropic
    except ImportError as exc:
        raise AnthropicError(
            "anthropic package is not installed — run: pip install anthropic"
        ) from exc

    resolved_model = (
        model
        or os.environ.get("ANTHROPIC_IMPACT_MODEL", "")
        or _DEFAULT_MODEL
    )

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise AnthropicError("ANTHROPIC_API_KEY environment variable is not set")

    client = anthropic.AsyncAnthropic(api_key=api_key, timeout=timeout)

    t0 = time.monotonic()
    try:
        message = await client.messages.create(
            model=resolved_model,
            max_tokens=1024,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
    except anthropic.APIStatusError as exc:
        raise AnthropicError(f"Anthropic API error {exc.status_code}: {exc.message}") from exc
    except anthropic.APIConnectionError as exc:
        raise AnthropicError(f"Anthropic connection error: {exc}") from exc
    except anthropic.APITimeoutError as exc:
        raise AnthropicError(f"Anthropic request timed out after {timeout}s") from exc

    latency_ms = int((time.monotonic() - t0) * 1000)

    try:
        text = message.content[0].text
    except (IndexError, AttributeError) as exc:
        raise AnthropicError(f"Malformed Anthropic response: {exc}") from exc

    logger.debug(
        "[anthropic] model=%s latency=%dms response_preview=%r",
        resolved_model, latency_ms, text[:80],
    )
    return text, latency_ms


if __name__ == "__main__":
    import asyncio
    import pathlib
    from dotenv import load_dotenv

    load_dotenv(pathlib.Path(__file__).parent.parent / ".env")

    async def _demo():
        text, ms = await chat(
            prompt="What is 2 + 2?",
            system="You are a helpful assistant.",
        )
        print(f"Response ({ms}ms): {text}")

    asyncio.run(_demo())
