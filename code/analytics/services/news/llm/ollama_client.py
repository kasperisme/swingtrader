"""
Async Ollama client for local LLM inference.

Calls http://localhost:11434/api/chat (non-streaming).
Model defaults to env var OLLAMA_IMPACT_MODEL, fallback "devstral".
"""

import logging
import os
import time
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "devstral"
_DEFAULT_BASE  = "http://localhost:11434"


class OllamaError(Exception):
    """Raised when the Ollama API returns an error or a malformed response."""


async def chat(
    prompt: str,
    system: str,
    model: Optional[str] = None,
    timeout: float = 60.0,
    num_predict: Optional[int] = None,
) -> tuple[str, int]:
    """
    Send a chat request to the local Ollama instance.

    Parameters
    ----------
    prompt  : user message content
    system  : system message content
    model   : model name; defaults to OLLAMA_IMPACT_MODEL env var → "devstral"
    timeout : seconds before httpx raises TimeoutException

    Returns
    -------
    (response_text, latency_ms)

    Raises
    ------
    OllamaError  if status != 200 or response is malformed
    """
    resolved_model = (
        model
        or os.environ.get("OLLAMA_IMPACT_MODEL", "")
        or _DEFAULT_MODEL
    )
    base_url = os.environ.get("OLLAMA_BASE_URL", _DEFAULT_BASE).rstrip("/")
    url      = f"{base_url}/api/chat"

    num_predict = num_predict if num_predict is not None else int(os.environ.get("OLLAMA_NUM_PREDICT", "1024"))

    payload = {
        "model": resolved_model,
        "stream": False,
        "think": False,   # disable thinking/reasoning mode by default
        "options": {
            "num_predict": num_predict,  # max tokens; raise via OLLAMA_NUM_PREDICT
        },
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": prompt},
        ],
    }

    t0 = time.monotonic()
    async with httpx.AsyncClient() as client:
        try:
            r = await client.post(url, json=payload, timeout=timeout)
        except httpx.TimeoutException as exc:
            raise OllamaError(f"Ollama request timed out after {timeout}s") from exc
        except httpx.RequestError as exc:
            raise OllamaError(f"Ollama connection error: {exc}") from exc

    latency_ms = int((time.monotonic() - t0) * 1000)

    if r.status_code != 200:
        raise OllamaError(
            f"Ollama returned HTTP {r.status_code}: {r.text[:200]}"
        )

    try:
        data = r.json()
        text = data["message"]["content"]
    except (KeyError, ValueError) as exc:
        raise OllamaError(f"Malformed Ollama response: {exc} — {r.text[:300]}") from exc

    logger.debug(
        "[ollama] model=%s latency=%dms response_preview=%r",
        resolved_model, latency_ms, text[:80],
    )
    return text, latency_ms


if __name__ == "__main__":
    import asyncio
    from dotenv import load_dotenv
    import pathlib

    load_dotenv(pathlib.Path(__file__).parent.parent / ".env")

    async def _demo():
        text, ms = await chat(
            prompt="What is 2 + 2?",
            system="You are a helpful assistant.",
        )
        print(f"Response ({ms}ms): {text}")

    asyncio.run(_demo())
