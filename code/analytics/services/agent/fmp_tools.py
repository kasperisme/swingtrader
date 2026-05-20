"""
fmp_tools.py — FMP MCP client for the screening agent.

Connects to FMP's hosted MCP server via fastmcp. Tools are discovered
dynamically — no manual REST wrappers needed.

Enabled when FMP_API_KEY env var is set.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

log = logging.getLogger(__name__)

_FMP_MCP_BASE = "https://financialmodelingprep.com/mcp"
_cached_schemas: list[dict] | None = None

# ── Subscription-tier denylist ───────────────────────────────────────────────
# Some FMP MCP tools require a higher plan than the configured FMP_API_KEY can
# access. Calls to those tools fail with "ACCESS DENIED" / "requires a higher
# plan". To stop the planner from picking them again (and to short-circuit the
# per-ticker fan-out before it wastes time re-failing the same call N times),
# we maintain a persistent denylist that grows automatically as we observe the
# errors.

_DENIED_TOOLS_PATH = os.environ.get(
    "FMP_DENIED_TOOLS_FILE",
    os.path.join(
        os.path.expanduser("~"), ".cache", "swingtrader", "fmp_denied_tools.json"
    ),
)
_ACCESS_DENIED_MARKERS = ("ACCESS DENIED", "requires a higher plan", "Premium Endpoint")
_denied_tools: set[str] | None = None


def _load_denied_tools() -> set[str]:
    """Lazy-load the FMP denylist: env-var seed + persisted file."""
    global _denied_tools
    if _denied_tools is not None:
        return _denied_tools
    seed: set[str] = set()
    env_seed = os.environ.get("FMP_DENIED_TOOLS", "")
    for n in env_seed.split(","):
        n = n.strip()
        if n:
            seed.add(n)
    try:
        with open(_DENIED_TOOLS_PATH, "r") as f:
            data = json.load(f)
        if isinstance(data, list):
            seed.update(str(n) for n in data if isinstance(n, str))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    _denied_tools = seed
    if seed:
        log.info("FMP denylist loaded: %d tool(s) — %s", len(seed), sorted(seed))
    return _denied_tools


def get_denied_fmp_tools() -> set[str]:
    """Snapshot of FMP tools the current plan cannot access."""
    return set(_load_denied_tools())


def _persist_denied_tools() -> None:
    cache = _denied_tools or set()
    try:
        os.makedirs(os.path.dirname(_DENIED_TOOLS_PATH), exist_ok=True)
        with open(_DENIED_TOOLS_PATH, "w") as f:
            json.dump(sorted(cache), f, indent=2)
    except OSError as exc:
        log.warning(
            "Failed to persist FMP denylist to %s: %s", _DENIED_TOOLS_PATH, exc
        )


def _record_denied_tool(name: str) -> None:
    cache = _load_denied_tools()
    if name not in cache:
        cache.add(name)
        log.warning(
            "FMP tool %r added to denylist (subscription-limited) — persisted to %s",
            name, _DENIED_TOOLS_PATH,
        )
        _persist_denied_tools()


def _looks_like_access_denied(msg: str) -> bool:
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

    Short-circuits when ``name`` is already on the subscription denylist (set
    by a prior failed call or seeded via ``FMP_DENIED_TOOLS``). On a fresh
    access-denied response, the tool is added to the denylist for the rest of
    this process AND persisted so subsequent screening runs skip it too.
    """
    if name in _load_denied_tools():
        return {
            "error": (
                f"FMP tool {name!r} is on the subscription denylist; "
                "skipped without calling FMP."
            )
        }
    try:
        return asyncio.run(_acall_tool(name, args))
    except Exception as exc:
        msg = str(exc)
        if _looks_like_access_denied(msg):
            _record_denied_tool(name)
            return {
                "error": (
                    f"FMP tool {name} requires a plan upgrade — added to denylist."
                )
            }
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
