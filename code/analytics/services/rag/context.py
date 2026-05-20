"""
Context assembly for LLM prompts.

Extracted from services/agent/engine.py (_get_linked_scan_run_context).
"""

from __future__ import annotations

import json
import logging
from typing import Any

from shared.db import get_supabase_client

log = logging.getLogger(__name__)


def _format_entry(metadata_json: Any) -> str:
    """Render `metadata_json.entry` as a compact `entry@X long, tp@Y, sl@Z`.

    Returns empty string when no entry marker is set so the caller can skip it.
    Accepts both dict and JSON-string shapes (Supabase JSONB normally arrives
    parsed, but defensive parsing keeps unit-tests and edge cases honest).
    """
    if isinstance(metadata_json, str):
        try:
            metadata_json = json.loads(metadata_json)
        except Exception:
            return ""
    if not isinstance(metadata_json, dict):
        return ""
    entry = metadata_json.get("entry")
    if not isinstance(entry, dict):
        return ""
    price = entry.get("price")
    if not isinstance(price, (int, float)):
        return ""
    direction = entry.get("direction") or "long"
    parts = [f"entry@{price:g} {direction}"]
    tp = entry.get("take_profit")
    sl = entry.get("stop_loss")
    if isinstance(tp, (int, float)):
        parts.append(f"tp@{tp:g}")
    if isinstance(sl, (int, float)):
        parts.append(f"sl@{sl:g}")
    return ", ".join(parts)


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
        .select(
            "run_id, ticker, status, highlighted, comment, stage, priority, tags, metadata_json"
        )
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
                entry_str = _format_entry(n.get("metadata_json"))
                parts = [p for p in [
                    "★" if n.get("highlighted") else "",
                    n.get("status", ""),
                    n.get("stage") or "",
                    entry_str,
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
