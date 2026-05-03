"""
Context assembly for LLM prompts.

Extracted from services/agent/engine.py (_get_linked_scan_run_context).
"""

from __future__ import annotations

import logging
from typing import Any

from shared.db import get_supabase_client

log = logging.getLogger(__name__)


def get_linked_scan_run_context(
    user_id: str | None,
    scan_run_ids: list[int],
    filtered_tickers: list[str] | None = None,
) -> str:
    """Build a human-readable summary of linked screening runs + notes.

    Used to inject scan context into the agent's system prompt.
    Returns empty string if user_id or scan_run_ids are missing.
    """
    if not user_id or not scan_run_ids:
        return ""

    client = get_supabase_client()
    schema = "swingtrader"

    runs = (
        client.schema(schema)
        .table("user_scan_runs")
        .select("id, scan_date, source")
        .in_("id", scan_run_ids)
        .eq("user_id", user_id)
        .execute()
    ).data or []

    if not runs:
        return ""

    notes_by_run: dict[int, list[dict]] = {}
    for n in (
        client.schema(schema)
        .table("user_scan_row_notes")
        .select("run_id, ticker, status, highlighted, comment, stage, priority, tags")
        .in_("run_id", scan_run_ids)
        .eq("user_id", user_id)
        .execute()
    ).data or []:
        notes_by_run.setdefault(n["run_id"], []).append(n)

    lines: list[str] = []
    for r in runs:
        run_id = r.get("id", "")
        date = str(r.get("scan_date", ""))[:10]
        source = r.get("source") or ""
        label = f"Scan {run_id} ({date}" + (f", {source}" if source else "") + ")"

        run_notes = notes_by_run.get(run_id, [])
        if run_notes:
            for n in run_notes[:20]:
                ticker = n.get("ticker", "")
                parts = [p for p in [
                    "★" if n.get("highlighted") else "",
                    n.get("status", ""),
                    n.get("stage") or "",
                    (n.get("comment") or "")[:120],
                ] if p]
                note_str = f"{ticker} — {' '.join(parts)}" if parts else ticker
                lines.append(f"- {label}: {note_str}")
        else:
            lines.append(f"- {label}: (no notes)")

    if filtered_tickers:
        sample = filtered_tickers[:30]
        lines.append(
            f"\nFiltered tickers ({len(filtered_tickers)} total): "
            + ", ".join(sample)
            + (f" +{len(filtered_tickers) - 30} more" if len(filtered_tickers) > 30 else "")
        )

    return "\n".join(lines)
