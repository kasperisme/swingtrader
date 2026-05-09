"""
screening_writes.py — write-side helpers for the user's screening data.

These functions mirror the UI server actions in
``code/ui/app/actions/screenings.ts`` (``screeningsAddTicker``,
``screeningsUpsertDismissNote``) and are intended for agent-driven use.

Every function takes ``user_id`` as the first argument and enforces it on
every Supabase query / mutation. The agent service keys are not RLS'd —
guarding ownership in code is mandatory.

Callers must NEVER expose these functions to an agent without first wrapping
them in ``services.agent_core.market_tools.build_screening_write_registry``
which additionally restricts the writeable ``run_id`` set to the screening
the scheduled agent is linked to.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from shared.db import get_supabase_client


_SCHEMA = "swingtrader"

_VALID_STATUSES = {"active", "dismissed", "watchlist", "pipeline"}


# ── Internal helpers ────────────────────────────────────────────────────────


def _normalise_ticker(raw: Any) -> str:
    if not isinstance(raw, str):
        raise ValueError("ticker must be a string")
    sym = raw.strip().upper()
    if not sym:
        raise ValueError("ticker required")
    if len(sym) > 16:
        raise ValueError("ticker too long")
    return sym


def _verify_run_belongs_to_user(client, user_id: str, run_id: int) -> dict:
    """Fetch the scan run, verify it belongs to the user and is active.

    Raises a ValueError on any guard failure; returns the run row otherwise.
    """
    if not user_id or not isinstance(user_id, str):
        raise ValueError("user_id required")
    if not isinstance(run_id, int) or run_id < 1:
        raise ValueError("run_id must be a positive integer")

    res = (
        client.schema(_SCHEMA)
        .table("user_scan_runs")
        .select("id, scan_date, status, user_id")
        .eq("id", run_id)
        .eq("user_id", user_id)
        .maybeSingle()
        .execute()
    )
    row = res.data
    if not row:
        raise ValueError(f"screening run {run_id} not found for this user")
    if row.get("status") == "deleted":
        raise ValueError(f"screening run {run_id} has been deleted")
    return row


def _find_scan_row(
    client, user_id: str, run_id: int, ticker: str
) -> dict | None:
    res = (
        client.schema(_SCHEMA)
        .table("user_scan_rows")
        .select("id, symbol")
        .eq("run_id", run_id)
        .eq("user_id", user_id)
        .eq("symbol", ticker)
        .limit(1)
        .maybeSingle()
        .execute()
    )
    return res.data or None


# ── Public write functions ──────────────────────────────────────────────────


def add_ticker_to_screening(
    user_id: str, run_id: int, ticker: str
) -> dict[str, Any]:
    """Add a ticker to the user's screening. Idempotent — returns the existing
    row if the ticker is already in the screening.

    Returns ``{ok, scan_row_id, ticker, run_id, created}``. Raises ``ValueError``
    on guard failures.
    """
    sym = _normalise_ticker(ticker)
    client = get_supabase_client()
    run = _verify_run_belongs_to_user(client, user_id, run_id)

    existing = _find_scan_row(client, user_id, run_id, sym)
    if existing:
        return {
            "ok": True,
            "scan_row_id": int(existing["id"]),
            "ticker": sym,
            "run_id": run_id,
            "created": False,
        }

    scan_date = str(
        run.get("scan_date") or datetime.now(timezone.utc).date().isoformat()
    )[:10]

    inserted = (
        client.schema(_SCHEMA)
        .table("user_scan_rows")
        .insert(
            {
                "run_id": run_id,
                "scan_date": scan_date,
                "dataset": "agent_add",
                "symbol": sym,
                "row_data": {},
                "user_id": user_id,
            }
        )
        .select("id")
        .single()
        .execute()
    )
    row_id = int((inserted.data or {}).get("id") or 0)
    if row_id < 1:
        raise RuntimeError("insert succeeded but no id returned")
    return {
        "ok": True,
        "scan_row_id": row_id,
        "ticker": sym,
        "run_id": run_id,
        "created": True,
    }


def set_screening_ticker_status(
    user_id: str,
    run_id: int,
    ticker: str,
    status: str | None = None,
    comment: str | None = None,
    highlighted: bool | None = None,
) -> dict[str, Any]:
    """Upsert workflow state on a ticker that's already in the screening.

    The ticker MUST already be in the screening — this fn does not create
    rows. Use ``add_ticker_to_screening`` first if you need to.

    Any field left as ``None`` is preserved from the existing note (or set
    to its default on first write). Returns the full upserted note row.
    """
    sym = _normalise_ticker(ticker)
    if status is not None:
        if not isinstance(status, str) or status not in _VALID_STATUSES:
            raise ValueError(
                f"status must be one of {sorted(_VALID_STATUSES)}"
            )
    if comment is not None and not isinstance(comment, str):
        raise ValueError("comment must be a string or null")
    if comment is not None and len(comment) > 4000:
        raise ValueError("comment too long (max 4000 chars)")
    if highlighted is not None and not isinstance(highlighted, bool):
        raise ValueError("highlighted must be a boolean")

    client = get_supabase_client()
    _verify_run_belongs_to_user(client, user_id, run_id)

    row = _find_scan_row(client, user_id, run_id, sym)
    if not row:
        raise ValueError(
            f"ticker {sym} is not in screening run {run_id} — "
            "call add_ticker_to_screening first"
        )
    scan_row_id = int(row["id"])

    # Read existing note (so we can preserve unspecified fields)
    existing = (
        client.schema(_SCHEMA)
        .table("user_scan_row_notes")
        .select("status, comment, highlighted, metadata_json")
        .eq("scan_row_id", scan_row_id)
        .eq("user_id", user_id)
        .limit(1)
        .maybeSingle()
        .execute()
    ).data or {}

    next_status = status if status is not None else (existing.get("status") or "active")
    next_comment = (
        comment if comment is not None else existing.get("comment")
    )
    if next_comment is not None:
        next_comment = next_comment.strip() or None
    next_highlighted = (
        highlighted
        if highlighted is not None
        else bool(existing.get("highlighted") or False)
    )

    payload = {
        "scan_row_id": scan_row_id,
        "run_id": run_id,
        "ticker": sym,
        "user_id": user_id,
        "status": next_status,
        "highlighted": next_highlighted,
        "comment": next_comment,
        "metadata_json": existing.get("metadata_json") or {},
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    client.schema(_SCHEMA).table("user_scan_row_notes").upsert(
        payload, on_conflict="scan_row_id,user_id"
    ).execute()

    return {
        "ok": True,
        "scan_row_id": scan_row_id,
        "ticker": sym,
        "run_id": run_id,
        "status": next_status,
        "highlighted": next_highlighted,
        "comment": next_comment,
    }


def set_screening_ticker_note(
    user_id: str,
    run_id: int,
    ticker: str,
    comment: str,
) -> dict[str, Any]:
    """Convenience wrapper for editing only the comment on a ticker.

    Sentinel: passing an empty / whitespace-only string clears the note.
    """
    return set_screening_ticker_status(
        user_id=user_id,
        run_id=run_id,
        ticker=ticker,
        comment=comment,
    )


__all__ = [
    "add_ticker_to_screening",
    "set_screening_ticker_status",
    "set_screening_ticker_note",
]
