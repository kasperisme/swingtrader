"""
Unified async LLM client. Dispatches to Ollama, Anthropic, or DO GenAI Agent
based on the NEWS_IMPACT_BACKEND env var (default: "ollama").

All backends share the same signature:
    chat(prompt, system, model, timeout) -> (response_text, latency_ms)
"""

from __future__ import annotations

import os
from typing import Optional


class LLMError(Exception):
    """Raised when any backend returns an error or malformed response."""


def _backend() -> str:
    return os.environ.get("NEWS_IMPACT_BACKEND", "ollama").lower().strip()


async def chat(
    prompt: str,
    system: str,
    model: Optional[str] = None,
    timeout: float = 60.0,
    backend: Optional[str] = None,
    num_predict: Optional[int] = None,
) -> tuple[str, int]:
    """
    Send a chat request to the configured LLM backend.

    Parameters
    ----------
    prompt      : user message
    system      : system message
    model       : model ID override (backend-specific default used if None)
    timeout     : seconds before timeout
    backend     : "ollama" | "anthropic" | "do_agent" — defaults to NEWS_IMPACT_BACKEND env var
    num_predict : max tokens (Ollama only; ignored by Anthropic / DO Agent)

    Returns
    -------
    (response_text, latency_ms)

    Raises
    ------
    LLMError on any backend failure
    """
    resolved = (backend or _backend()).lower()

    try:
        if resolved == "anthropic":
            from services.news.llm.anthropic_client import chat as _chat, AnthropicError
            try:
                return await _chat(prompt, system, model=model, timeout=timeout)
            except AnthropicError as exc:
                raise LLMError(str(exc)) from exc

        elif resolved == "do_agent":
            from services.news.llm.do_agent_client import chat as _chat, GenAIAgentError
            try:
                return await _chat(prompt, system, model=model, timeout=timeout)
            except GenAIAgentError as exc:
                raise LLMError(str(exc)) from exc

        else:  # default: ollama
            from services.news.llm.ollama_client import chat as _chat, OllamaError
            try:
                kwargs: dict = {}
                if num_predict is not None:
                    kwargs["num_predict"] = num_predict
                return await _chat(prompt, system, model=model, timeout=timeout, **kwargs)
            except OllamaError as exc:
                raise LLMError(str(exc)) from exc

    except ImportError as exc:
        raise LLMError(f"LLM backend '{resolved}' not available: {exc}") from exc
