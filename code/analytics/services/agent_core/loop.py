"""Shared Ollama tool-calling loop with retry, streaming, and a registry.

Used by services/agent/engine.py and services/podcast/research_agent.py so
the streaming/retry plumbing isn't duplicated. Each agent supplies its own
system prompt, registry, and output parsing.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Callable

import httpx

log = logging.getLogger(__name__)

_HEARTBEAT_SECONDS = 5.0
_RETRY_INITIAL_BACKOFF_S = 2.0
_DEFAULT_RETRY_ATTEMPTS = 3


def is_transient_ollama_error(exc: BaseException) -> bool:
    """True for backend flakes a retry can plausibly recover from.

    Covers Ollama Cloud's 502/503/504/429, "too many concurrent requests",
    "unexpected EOF", plus transport-level failures.
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


def _retry_sleep_seconds(exc: BaseException, backoff: float) -> float:
    m = str(exc).lower()
    if "429" in m or "too many concurrent" in m:
        return max(backoff, 12.0)
    return backoff


# ── Tool registry ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Tool:
    """A callable + its Ollama function-call schema."""

    name: str
    schema: dict
    fn: Callable[..., Any]


class _DispatcherProxy:
    """Bind a (name, args) → result dispatcher to one tool name.

    Used when a single dispatcher (e.g. FMP MCP) backs many tools.
    """

    __slots__ = ("dispatcher", "name")

    def __init__(self, dispatcher: Callable[[str, dict], Any], name: str) -> None:
        self.dispatcher = dispatcher
        self.name = name

    def __call__(self, **args: Any) -> Any:
        return self.dispatcher(self.name, args)


class ToolRegistry:
    """Mutable bag of Tools. Each agent builds one and extends it."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def add(self, tool: Tool) -> "ToolRegistry":
        self._tools[tool.name] = tool
        return self

    def add_function(
        self,
        name: str,
        fn: Callable[..., Any],
        *,
        description: str,
        parameters: dict | None = None,
    ) -> "ToolRegistry":
        """Convenience: register a tool with an inline schema."""
        schema = {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": parameters
                or {"type": "object", "properties": {}, "required": []},
            },
        }
        self._tools[name] = Tool(name=name, schema=schema, fn=fn)
        return self

    def add_schemas(
        self,
        schemas: list[dict],
        dispatcher: Callable[[str, dict], Any],
    ) -> "ToolRegistry":
        """Bulk-register tools that share one dispatcher (e.g. FMP MCP).

        Each schema must follow Ollama's function-call format
        ``{"type": "function", "function": {"name", "description", "parameters"}}``.
        """
        for s in schemas:
            name = s["function"]["name"]
            self._tools[name] = Tool(
                name=name, schema=s, fn=_DispatcherProxy(dispatcher, name)
            )
        return self

    def extend(self, other: "ToolRegistry") -> "ToolRegistry":
        self._tools.update(other._tools)
        return self

    def schemas(self) -> list[dict]:
        return [t.schema for t in self._tools.values()]

    def names(self) -> list[str]:
        return list(self._tools.keys())

    def has(self, name: str) -> bool:
        return name in self._tools

    async def call(self, name: str, args: dict) -> Any:
        """Invoke a tool. Sync fns run in a thread (so nested asyncio.run —
        e.g. FMP MCP — works); async fns are awaited directly."""
        tool = self._tools.get(name)
        if tool is None:
            return {"error": f"Unknown tool: {name}"}
        try:
            result = await asyncio.to_thread(tool.fn, **(args or {}))
            if asyncio.iscoroutine(result):
                result = await result
            return result
        except Exception as exc:  # noqa: BLE001 — tools must not crash the loop
            log.warning("Tool %s failed: %s", name, exc)
            return {"error": str(exc)}


# ── Streaming chat ────────────────────────────────────────────────────────


async def _stream_chat_once(
    client: httpx.AsyncClient,
    *,
    base_url: str,
    model: str,
    messages: list[dict],
    tools: list[dict] | None,
    options: dict | None,
    request_format: str | None,
    think: bool | None,
    label: str,
    attempt: int,
) -> dict:
    """One streaming /api/chat round; concatenates content + last tool_calls wins.

    Streaming keeps the connection alive token-by-token, sidestepping the
    ~60s idle timeout on Ollama Cloud's local-daemon → cloud proxy.
    """
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": True,
    }
    if options:
        payload["options"] = options
    if tools:
        payload["tools"] = tools
    if request_format:
        payload["format"] = request_format
    if think is not None:
        payload["think"] = think

    started = time.monotonic()
    last_beat = started
    msg_acc: dict[str, Any] = {"role": "assistant", "content": ""}
    tool_calls: list[dict[str, Any]] | None = None

    async with client.stream(
        "POST",
        f"{base_url.rstrip('/')}/api/chat",
        json=payload,
        timeout=httpx.Timeout(600.0, connect=30.0),
    ) as r:
        if r.status_code >= 400:
            body = await r.aread()
            raise RuntimeError(
                f"Ollama returned {r.status_code} (model={model}): "
                f"{body.decode(errors='replace')[:500]}"
            )
        async for line in r.aiter_lines():
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                log.warning(
                    "%s: skipping non-JSON line (attempt %d): %r",
                    label,
                    attempt,
                    line[:200],
                )
                continue
            if obj.get("error"):
                raise RuntimeError(f"Ollama stream error: {obj['error']}")
            m = obj.get("message") or {}
            if m.get("role"):
                msg_acc["role"] = m["role"]
            c = m.get("content")
            if c:
                msg_acc["content"] = (msg_acc.get("content") or "") + c
            if m.get("tool_calls"):
                tool_calls = m["tool_calls"]
            now = time.monotonic()
            if now - last_beat >= _HEARTBEAT_SECONDS and not obj.get("done"):
                log.info(
                    "%s: streaming… %.0fs elapsed (attempt %d)",
                    label,
                    now - started,
                    attempt,
                )
                last_beat = now
            if obj.get("done"):
                break

    if tool_calls is not None:
        msg_acc["tool_calls"] = tool_calls
    return msg_acc


async def _chat_with_retry(
    client: httpx.AsyncClient,
    *,
    base_url: str,
    model: str,
    messages: list[dict],
    tools: list[dict] | None,
    options: dict | None,
    request_format: str | None,
    think: bool | None,
    label: str,
    max_attempts: int,
) -> dict:
    backoff = _RETRY_INITIAL_BACKOFF_S
    last_exc: BaseException | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return await _stream_chat_once(
                client,
                base_url=base_url,
                model=model,
                messages=messages,
                tools=tools,
                options=options,
                request_format=request_format,
                think=think,
                label=label,
                attempt=attempt,
            )
        except Exception as exc:
            last_exc = exc
            if not is_transient_ollama_error(exc) or attempt == max_attempts:
                raise
            log.warning(
                "%s: attempt %d/%d failed (%s: %s) — retrying in %.0fs",
                label,
                attempt,
                max_attempts,
                type(exc).__name__,
                str(exc)[:200],
                backoff,
            )
            await asyncio.sleep(_retry_sleep_seconds(exc, backoff))
            backoff *= 2
    assert last_exc is not None
    raise last_exc


# ── Public loop ───────────────────────────────────────────────────────────


async def run_tool_loop(
    client: httpx.AsyncClient,
    *,
    base_url: str,
    model: str,
    system: str,
    user: str,
    registry: ToolRegistry,
    max_rounds: int = 10,
    max_attempts: int = _DEFAULT_RETRY_ATTEMPTS,
    options: dict | None = None,
    request_format: str | None = None,
    think: bool | None = None,
    label: str = "Agent",
    cache_results: bool = True,
) -> tuple[dict, dict[str, Any], int]:
    """Run an Ollama tool-calling loop until the model emits a non-tool
    message or ``max_rounds`` is exhausted.

    On budget exhaustion, the model is told to stop calling tools and emit
    its final answer with the data already gathered.

    Returns:
        (final_assistant_message, tool_results_by_name, rounds_used)
    """
    messages: list[dict] = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    schemas = registry.schemas()
    tool_results: dict[str, Any] = {}
    final_message: dict = {}
    rounds_used = 0

    for round_idx in range(1, max_rounds + 1):
        rounds_used = round_idx
        resp = await _chat_with_retry(
            client,
            base_url=base_url,
            model=model,
            messages=messages,
            tools=schemas,
            options=options,
            request_format=request_format,
            think=think,
            label=label,
            max_attempts=max_attempts,
        )
        tool_calls = resp.get("tool_calls") or []

        if not tool_calls:
            final_message = resp
            break

        messages.append(resp)
        for tc in tool_calls:
            fn_name = tc["function"]["name"]
            fn_args = tc["function"].get("arguments", {}) or {}
            if cache_results and fn_name in tool_results:
                result: Any = tool_results[fn_name]
                log.info("%s: cached %s (round %d)", label, fn_name, round_idx)
            else:
                result = await registry.call(fn_name, fn_args)
                tool_results[fn_name] = result
                log.info(
                    "%s: called %s (round %d) → %s",
                    label,
                    fn_name,
                    round_idx,
                    "ok"
                    if not (isinstance(result, dict) and result.get("error"))
                    else "err",
                )
            messages.append(
                {
                    "role": "tool",
                    "name": fn_name,
                    "content": json.dumps(result, default=str)[:8000],
                }
            )
    else:
        log.warning(
            "%s: hit max_rounds=%d without final message — forcing emit",
            label,
            max_rounds,
        )
        messages.append(
            {
                "role": "user",
                "content": (
                    "You've reached the iteration budget. Stop calling tools and "
                    "produce your final response now using only the data you've gathered."
                ),
            }
        )
        final_message = await _chat_with_retry(
            client,
            base_url=base_url,
            model=model,
            messages=messages,
            tools=None,
            options=options,
            request_format=request_format,
            think=think,
            label=label,
            max_attempts=max_attempts,
        )

    return final_message, tool_results, rounds_used


async def simple_chat(
    client: httpx.AsyncClient,
    *,
    base_url: str,
    model: str,
    system: str,
    user: str,
    options: dict | None = None,
    request_format: str | None = None,
    think: bool | None = None,
    label: str = "Chat",
    max_attempts: int = _DEFAULT_RETRY_ATTEMPTS,
) -> str:
    """One-shot streaming Ollama chat call — no tools, no loop.

    Use this for prompt → text generation (blog posts, summaries, captions).
    For multi-turn or tool-calling, use ``run_tool_loop`` instead.

    Streaming sidesteps the ~60s idle timeout that kills non-streaming
    requests against Ollama Cloud (`:cloud` models proxy through it). Retries
    the same transient backend errors as the tool loop.
    """
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    msg = await _chat_with_retry(
        client,
        base_url=base_url,
        model=model,
        messages=messages,
        tools=None,
        options=options,
        request_format=request_format,
        think=think,
        label=label,
        max_attempts=max_attempts,
    )
    return (msg.get("content") or "").strip()
