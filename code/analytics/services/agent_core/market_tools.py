"""Base tool registries shared by every agent.

``build_market_registry()`` returns the default set of market-wide RAG
tools (cluster/dimension trends, ticker sentiment, top articles,
relationships, company vectors, semantic news search, ticker news, plus a
generic ``fetch_url`` helper). Every agent in the codebase starts here and
extends with task-specific tools.

``build_user_registry(user_id)`` returns a registry of user-scoped RAG
tools (positions, alerts, screening notes) with the user_id pre-bound so
the agent loop doesn't need to thread user context through dispatch.
"""

from __future__ import annotations

from typing import Any, Callable

import httpx

from services.rag import TOOL_SCHEMAS, get_market_tools, get_user_tools

from .loop import Tool, ToolRegistry

_SCHEMAS_BY_NAME: dict[str, dict] = {s["function"]["name"]: s for s in TOOL_SCHEMAS}


def fetch_url(url: str) -> dict[str, Any]:
    """Fetch a URL and return its text content (truncated to 8000 chars)."""
    try:
        r = httpx.get(
            url,
            timeout=15.0,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        return {"url": url, "status": r.status_code, "content": r.text[:8000]}
    except Exception as exc:
        return {"error": str(exc)}


def build_market_registry() -> ToolRegistry:
    """Registry of market-wide RAG tools + fetch_url, available to every agent."""
    registry = ToolRegistry()
    for name, fn in get_market_tools().items():
        schema = _SCHEMAS_BY_NAME.get(name)
        if schema is None:
            continue
        registry.add(Tool(name=name, schema=schema, fn=fn))

    fetch_url_schema = _SCHEMAS_BY_NAME.get("fetch_url") or {
        "type": "function",
        "function": {
            "name": "fetch_url",
            "description": "Fetch the full text content of a URL.",
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
            },
        },
    }
    registry.add(Tool(name="fetch_url", schema=fetch_url_schema, fn=fetch_url))
    return registry


class _BindUserId:
    """Pre-bind user_id as the first positional arg of a per-user tool fn."""

    __slots__ = ("fn", "user_id")

    def __init__(self, fn: Callable[..., Any], user_id: str) -> None:
        self.fn = fn
        self.user_id = user_id

    def __call__(self, **kwargs: Any) -> Any:
        return self.fn(self.user_id, **kwargs)


def build_user_registry(user_id: str) -> ToolRegistry:
    """Registry of user-scoped RAG tools bound to ``user_id``.

    Wraps each tool fn so the agent loop can dispatch by name without
    threading user context through every call site.
    """
    registry = ToolRegistry()
    for name, fn in get_user_tools().items():
        schema = _SCHEMAS_BY_NAME.get(name)
        if schema is None:
            continue
        registry.add(Tool(name=name, schema=schema, fn=_BindUserId(fn, user_id)))
    return registry
