"""
fmp_tools.py — FMP MCP client for the screening agent.

Connects to FMP's hosted MCP server via fastmcp. Tools are discovered
dynamically — no manual REST wrappers needed.

Enabled when FMP_API_KEY env var is set.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

log = logging.getLogger(__name__)

_FMP_MCP_BASE = "https://financialmodelingprep.com/mcp"
_cached_schemas: list[dict] | None = None

# ── Access-denied detection ──────────────────────────────────────────────────
# Some FMP MCP tools require a higher plan than the configured FMP_API_KEY can
# access. Calls to those tools either raise with "ACCESS DENIED" / "requires a
# higher plan" or return a body containing the same markers. The multi-ticker
# pipeline's trial-run validator imports ``looks_like_access_denied`` to spot
# these so the planner can drop the offending tool and re-plan once before the
# per-ticker fan-out wastes time re-failing the same call.

_ACCESS_DENIED_MARKERS = ("ACCESS DENIED", "requires a higher plan", "Premium Endpoint")


def looks_like_access_denied(msg: str) -> bool:
    """Heuristic: does ``msg`` look like a subscription-tier rejection?"""
    upper = msg.upper()
    return any(marker.upper() in upper for marker in _ACCESS_DENIED_MARKERS)


def _mcp_url() -> str:
    api_key = os.environ.get("FMP_API_KEY", "")
    if not api_key:
        raise RuntimeError("FMP_API_KEY not set")
    return f"{_FMP_MCP_BASE}?apikey={api_key}"


async def _alist_tools() -> list:
    from fastmcp import Client
    async with Client(_mcp_url()) as client:
        return await client.list_tools()


async def _acall_tool(name: str, args: dict) -> Any:
    from fastmcp import Client
    async with Client(_mcp_url()) as client:
        result = await client.call_tool(name, args)
    if hasattr(result, "structured_content") and result.structured_content is not None:
        return result.structured_content
    if hasattr(result, "content"):
        texts = [item.text for item in result.content if hasattr(item, "text")]
        return "\n".join(texts) if texts else str(result)
    return str(result)


def get_fmp_tool_schemas() -> list[dict]:
    """Lazily fetch tool list from FMP MCP and return as Ollama-compatible schemas."""
    global _cached_schemas
    if _cached_schemas is not None:
        return _cached_schemas

    if not os.environ.get("FMP_API_KEY"):
        log.error("FMP_API_KEY is not set — FMP tools unavailable")
        return []

    try:
        mcp_tools = asyncio.run(_alist_tools())
    except RuntimeError as exc:
        if "already running" in str(exc):
            log.error("FMP MCP: asyncio event loop conflict — call from async context not supported: %s", exc)
        else:
            log.error("FMP MCP: failed to fetch tool list: %s", exc)
        return []
    except Exception as exc:
        log.error("FMP MCP: failed to fetch tool list: %s", exc)
        return []

    if not mcp_tools:
        log.error("FMP MCP: connected but returned 0 tools — check API key validity")
        return []

    _cached_schemas = [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description or "",
                "parameters": t.inputSchema or {"type": "object", "properties": {}},
            },
        }
        for t in mcp_tools
    ]
    log.info("FMP MCP: %d tools loaded", len(_cached_schemas))
    return _cached_schemas


def call_fmp_tool(name: str, args: dict) -> Any:
    """Synchronous wrapper — dispatches a single tool call to the FMP MCP server.

    Errors (including subscription-tier rejections) are returned as
    ``{"error": <msg>}`` so the caller can decide what to do. The multi-ticker
    pipeline's trial-run validator inspects the error text via
    ``looks_like_access_denied`` and drops unavailable tools from the plan.
    """
    try:
        return asyncio.run(_acall_tool(name, args))
    except Exception as exc:
        msg = str(exc)
        if not looks_like_access_denied(msg):
            log.error("FMP tool %s failed: %s", name, exc)
        return {"error": msg}


def test_fmp_connection() -> None:
    """Print FMP MCP connectivity status. Run via: python -m services.agent.cli fmp-test"""
    api_key = os.environ.get("FMP_API_KEY", "")
    if not api_key:
        print("FAIL  FMP_API_KEY is not set in environment")
        return

    print(f"  API key: ...{api_key[-4:]}")
    print(f"  MCP URL: {_FMP_MCP_BASE}?apikey=****")
    print("  Connecting to FMP MCP server…")
    try:
        tools = asyncio.run(_alist_tools())
        print(f"  OK  {len(tools)} tools available")
        print("  Sample tools:", ", ".join(t.name for t in tools[:8]))
    except Exception as exc:
        print(f"  FAIL  {exc}")


_FMP_SYSTEM_ADDON = """\

### FMP MCP tools (live market data & fundamentals)
You have access to Financial Modeling Prep market data tools via MCP.
Use them to enrich screenings with live prices, technical indicators,
financials, analyst ratings, insider activity, earnings surprises, and more.
Useful tools include: quote, company-profile, key-metrics, financial-ratios,
income-statement, rsi, sma, historical-price, analyst-grades, insider-trading,
earnings-surprises, sector-performance, biggest-gainers, biggest-losers.
Call tools by their FMP MCP name (e.g. "quote" not "fmp_quote").
"""
