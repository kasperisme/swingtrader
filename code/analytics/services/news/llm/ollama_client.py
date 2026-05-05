"""
Async Ollama client for local + cloud LLM inference.

Thin compatibility wrapper around services.agent_core.simple_chat. Streams
the response, retries transient backend errors (502/503/504/429/EOF), and
keeps the pre-existing public surface (``chat()`` signature, ``OllamaError``
exception, ``(text, latency_ms)`` return tuple) so existing call sites need
no changes.

Streaming is mandatory for ``:cloud`` models: the Ollama Cloud proxy closes
idle connections after ~60s, which kills any non-streaming POST that takes
longer than that to generate. See services/agent_core/README.md for the
shared LLM pipeline architecture.
"""

import logging
import os
import time
from typing import Optional

import httpx

from services.agent_core import simple_chat
from services.agent_core.loop import is_transient_ollama_error

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "devstral"
_DEFAULT_BASE = "http://localhost:11434"


class OllamaError(Exception):
    """Raised when the Ollama API returns an error or a malformed response."""


async def chat(
    prompt: str,
    system: str,
    model: Optional[str] = None,
    timeout: float = 60.0,  # noqa: ARG001 — kept for source compat; streaming makes it irrelevant
    num_predict: Optional[int] = None,
) -> tuple[str, int]:
    """
    Send a chat request to Ollama (local daemon or cloud-backed model).

    Parameters
    ----------
    prompt
        User message content.
    system
        System message content.
    model
        Model name. Defaults to ``OLLAMA_IMPACT_MODEL`` env var → ``"devstral"``.
    timeout
        Accepted for source compatibility but no longer used — the
        underlying call streams, so the cloud proxy's idle timeout never
        fires regardless of total generation duration.
    num_predict
        Max tokens. Defaults to ``OLLAMA_NUM_PREDICT`` env var → 1024.

    Returns
    -------
    (response_text, latency_ms)

    Raises
    ------
    OllamaError
        On HTTP error, malformed response, or any transport failure.
    """
    resolved_model = (
        model
        or os.environ.get("OLLAMA_IMPACT_MODEL", "")
        or _DEFAULT_MODEL
    )
    base_url = os.environ.get("OLLAMA_BASE_URL", _DEFAULT_BASE).rstrip("/")
    resolved_num_predict = (
        num_predict
        if num_predict is not None
        else int(os.environ.get("OLLAMA_NUM_PREDICT", "1024"))
    )

    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient() as client:
            text = await simple_chat(
                client,
                base_url=base_url,
                model=resolved_model,
                system=system,
                user=prompt,
                options={"num_predict": resolved_num_predict},
                think=False,
                label="LLM chat",
            )
    except Exception as exc:
        # Normalise every failure (transport, transient backend, malformed
        # stream) into OllamaError so existing callers' `except OllamaError`
        # blocks still catch what they used to.
        kind = "transient" if is_transient_ollama_error(exc) else "fatal"
        raise OllamaError(f"Ollama {kind} error ({type(exc).__name__}): {exc}") from exc

    latency_ms = int((time.monotonic() - t0) * 1000)
    logger.debug(
        "[ollama] model=%s latency=%dms response_preview=%r",
        resolved_model,
        latency_ms,
        text[:80],
    )
    return text, latency_ms


if __name__ == "__main__":
    import asyncio
    import pathlib

    from dotenv import load_dotenv

    load_dotenv(pathlib.Path(__file__).parent.parent / ".env")

    async def _demo() -> None:
        text, ms = await chat(
            prompt="What is 2 + 2?",
            system="You are a helpful assistant.",
        )
        print(f"Response ({ms}ms): {text}")

    asyncio.run(_demo())
