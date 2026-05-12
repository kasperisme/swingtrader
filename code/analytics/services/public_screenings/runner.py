"""Run a public screening script, persist the result, fan out to subscribers."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from shared.db import get_supabase_client
from shared.telegram import (
    get_user_chat_id,
    log_telegram_message,
    send_telegram_chunks,
)

from .registry import get_script
from .types import ScreeningResult

log = logging.getLogger(__name__)

_SCHEMA = "swingtrader"


# ── Telegram formatting ─────────────────────────────────────────────────────

def _format_telegram_message(name: str, triggered: bool, summary: str | None, error: bool = False) -> str:
    if error:
        return f"<b>⚠️ {name}</b>\n\n<i>Run failed: {summary}</i>"
    if triggered:
        return f"<b>🔔 {name}</b>\n\n{summary}"
    return f"<b>✅ {name}</b>\n\n<i>No trigger — conditions not met.</i>"


# ── Execution ───────────────────────────────────────────────────────────────

def run_public_screening(screening: dict, *, dry_run: bool = False, is_test: bool = False) -> dict[str, Any]:
    """Look up the script for `screening` and execute it.

    Returns a dict shape compatible with `persist_and_deliver_public`. Errors
    in the script are caught and turned into an error result so the runner
    never crashes — the worst case is a 'status=error' row.
    """
    script_key = screening.get("script_key")
    script = get_script(script_key) if script_key else None

    if not script:
        return {
            "screening_id": screening["id"],
            "name": screening.get("name") or script_key or "(unknown)",
            "script_key": script_key,
            "triggered": False,
            "summary": f"Unknown script_key: {script_key!r}",
            "data_used": {},
            "error": True,
            "is_test": is_test,
        }

    client = get_supabase_client()

    try:
        result = script(client, screening)
        if not isinstance(result, ScreeningResult):
            raise TypeError(
                f"Script {script_key!r} returned {type(result).__name__}, expected ScreeningResult"
            )
    except Exception as exc:  # noqa: BLE001 — surface any script failure as error result
        log.exception("Public screening %s (%s) failed", screening["id"], script_key)
        return {
            "screening_id": screening["id"],
            "name": screening.get("name") or script_key,
            "script_key": script_key,
            "triggered": False,
            "summary": str(exc),
            "data_used": {},
            "error": True,
            "is_test": is_test,
        }

    return {
        "screening_id": screening["id"],
        "name": screening.get("name") or script_key,
        "script_key": script_key,
        "triggered": bool(result.triggered),
        "summary": result.summary,
        "data_used": result.data_used or {},
        "error": bool(result.error),
        "is_test": is_test,
    }


# ── Persistence + Telegram fan-out ──────────────────────────────────────────

def persist_and_deliver_public(result: dict[str, Any], result_id: str | None = None) -> None:
    """Update the shared result row, then deliver to every subscriber with notifications on."""
    client = get_supabase_client()
    now = datetime.now(timezone.utc).isoformat()

    is_test = bool(result.get("is_test"))
    triggered = bool(result.get("triggered"))
    error = bool(result.get("error"))
    status = "error" if error else "done"

    if result_id:
        try:
            client.schema(_SCHEMA).table("public_screening_results").update({
                "triggered": triggered,
                "summary": result.get("summary"),
                "data_used": result.get("data_used", {}),
                "status": status,
                "error": result.get("summary") if error else None,
            }).eq("id", result_id).execute()
        except Exception as exc:
            log.error("Failed to update public_screening_results %s: %s", result_id, exc)
            return
    else:
        row = {
            "public_screening_id": result["screening_id"],
            "run_at": now,
            "started_at": now,
            "triggered": triggered,
            "summary": result.get("summary"),
            "data_used": result.get("data_used", {}),
            "is_test": is_test,
            "status": status,
            "error": result.get("summary") if error else None,
        }
        try:
            ins = client.schema(_SCHEMA).table("public_screening_results").insert(row).execute()
            result_id = (ins.data or [{}])[0].get("id")
        except Exception as exc:
            log.error("Failed to persist public_screening_results: %s", exc)
            return

    # Update parent screening tracking columns.
    update_fields: dict[str, Any] = {
        "last_run_at": now,
        "last_triggered": triggered,
    }
    if is_test:
        update_fields["run_requested_at"] = None
    client.schema(_SCHEMA).table("public_screenings").update(
        update_fields,
    ).eq("id", result["screening_id"]).execute()

    # Fan out Telegram to subscribers (only when there's something to say).
    if error or triggered:
        _fan_out_telegram(result)


def _fan_out_telegram(result: dict[str, Any]) -> None:
    client = get_supabase_client()
    screening_id = result["screening_id"]
    name = result.get("name") or "Public screening"
    triggered = bool(result.get("triggered"))
    error = bool(result.get("error"))

    subs_res = (
        client.schema(_SCHEMA)
        .table("public_screening_subscriptions")
        .select("user_id, notifications_enabled")
        .eq("public_screening_id", screening_id)
        .eq("notifications_enabled", True)
        .execute()
    )
    subscribers = subs_res.data or []
    if not subscribers:
        log.info("Public screening %s: no subscribers with notifications enabled", screening_id)
        return

    html = _format_telegram_message(name, triggered, result.get("summary"), error=error)
    message_type = (
        "public_screening_error" if error
        else "public_screening_alert" if triggered
        else "public_screening_no_trigger"
    )

    delivered = 0
    skipped = 0
    failed = 0

    for sub in subscribers:
        user_id = sub["user_id"]
        chat_id = get_user_chat_id(user_id)
        if not chat_id:
            skipped += 1
            continue
        success, msg_id, err = send_telegram_chunks(chat_id, html)
        if success:
            delivered += 1
        else:
            failed += 1
            log.warning(
                "Public screening %s: Telegram send failed user=%s err=%s",
                screening_id, user_id, err,
            )
        log_telegram_message(
            user_id=user_id,
            chat_id=chat_id,
            message_type=message_type,
            message_text=html,
            success=success,
            telegram_message_id=msg_id,
            error_text=err,
        )

    log.info(
        "Public screening %s fan-out: delivered=%d skipped_no_telegram=%d failed=%d total_subs=%d",
        screening_id, delivered, skipped, failed, len(subscribers),
    )
