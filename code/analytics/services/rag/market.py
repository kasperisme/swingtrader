"""
Market data retrieval via FMP.

Centralises access to:
  - services/screener/fmp.py  — 26-method REST wrapper (FMPClient)
  - services/agent/fmp_tools  — MCP-based dynamic tool discovery

Services should import FMPClient from here rather than screener/fmp directly.
"""

from __future__ import annotations

from services.screener.fmp import fmp as FMPClient
from services.agent.fmp_tools import get_fmp_tool_schemas, call_fmp_tool

__all__ = ["FMPClient", "get_fmp_tool_schemas", "call_fmp_tool"]
