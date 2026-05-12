"""Run a public screening script, persist the result, fan out to subscribers."""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
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


def _format_telegram_message(
    name: str,
    *,
    ticker_count: int | None = None,
    error: bool = False,
    error_summary: str | None = None,
) -> str:
    """Subscriber-facing notification: name + ticker count, no per-symbol detail."""
    if error:
        return f"<b>⚠️ {name}</b>\n\n<i>Run failed: {error_summary}</i>"
    count_part = (
        f"\n{ticker_count} ticker{'s' if ticker_count != 1 else ''}"
        if ticker_count is not None
        else ""
    )
    return f"<b>📊 New screening: {name}</b>{count_part}"


# ── Execution ───────────────────────────────────────────────────────────────


def run_public_screening(
    screening: dict, *, dry_run: bool = False, is_test: bool = False
) -> dict[str, Any]:
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
    except (
        Exception
    ) as exc:  # noqa: BLE001 — surface any script failure as error result
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
        "ticker_count": result.ticker_count,
        "error": bool(result.error),
        "is_test": is_test,
    }


# ── Persistence + Telegram fan-out ──────────────────────────────────────────


def persist_and_deliver_public(
    result: dict[str, Any], result_id: str | None = None
) -> None:
    """Update the shared result row, then deliver to every subscriber with notifications on."""
    client = get_supabase_client()
    now = datetime.now(timezone.utc).isoformat()

    is_test = bool(result.get("is_test"))
    triggered = bool(result.get("triggered"))
    error = bool(result.get("error"))
    status = "error" if error else "done"

    if result_id:
        try:
            client.schema(_SCHEMA).table("public_screening_results").update(
                {
                    "triggered": triggered,
                    "summary": result.get("summary"),
                    "data_used": result.get("data_used", {}),
                    "status": status,
                    "error": result.get("summary") if error else None,
                }
            ).eq("id", result_id).execute()
        except Exception as exc:
            log.error(
                "Failed to update public_screening_results %s: %s", result_id, exc
            )
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
            ins = (
                client.schema(_SCHEMA)
                .table("public_screening_results")
                .insert(row)
                .execute()
            )
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

    # Fan out to subscribers: write a user_screening_results row for each
    # subscriber's operational user_scheduled_screenings copy, then deliver
    # Telegram. Always fans out (even on no-trigger / error) so subscribers'
    # in-app history stays complete and matches private screening behaviour.
    _fan_out_to_subscribers(result)


def _write_scan_artefacts_for_subscriber(
    client,
    *,
    user_id: str,
    source_label: str,
    script_key: str,
    scan_date_str: str,
    started_at_iso: str,
    finished_at_iso: str,
    status: str,
    error_message: str | None,
    data_used: dict[str, Any] | None,
) -> tuple[int | None, int | None, int]:
    """Write the full scan artefacts for one subscriber.

    Inserts one user_scan_jobs row (job metadata), one user_scan_runs row
    (scan instance + payload), and N user_scan_rows (per-ticker). Returns
    (job_id, run_id, row_count). Any individual insert failure is logged but
    does not abort the others — best-effort delivery.
    """
    payload = data_used or {}
    symbols = payload.get("symbols") if isinstance(payload.get("symbols"), list) else []
    script_rel = f"services/public_screenings/scripts/{script_key}.py"
    job_status = "completed" if status == "done" else "failed"
    exit_code = 0 if status == "done" else 1

    # 1. user_scan_jobs — runtime metadata
    job_id: int | None = None
    try:
        ins_job = (
            client.schema(_SCHEMA)
            .table("user_scan_jobs")
            .insert(
                {
                    "started_at": started_at_iso,
                    "finished_at": finished_at_iso,
                    "status": job_status,
                    "scan_source": script_key,
                    "script_rel": script_rel,
                    "args_json": json.dumps([]),
                    "stdout_log": "",
                    "stderr_log": "",
                    "exit_code": exit_code,
                    "error_message": error_message,
                    "user_id": user_id,
                }
            )
            .execute()
        )
        job_id = (ins_job.data or [{}])[0].get("id")
    except Exception as exc:
        log.warning(
            "[fan-out] user=%s: failed to insert user_scan_jobs: %s", user_id, exc
        )

    # 2. user_scan_runs — scan instance
    run_id: int | None = None
    try:
        ins_run = (
            client.schema(_SCHEMA)
            .table("user_scan_runs")
            .insert(
                {
                    "scan_date": scan_date_str,
                    "source": source_label,
                    "status": "active",
                    "market_json": None,
                    "result_json": json.dumps(payload) if payload else None,
                    "user_id": user_id,
                }
            )
            .execute()
        )
        run_id = (ins_run.data or [{}])[0].get("id")
    except Exception as exc:
        log.warning(
            "[fan-out] user=%s: failed to insert user_scan_runs: %s", user_id, exc
        )

    # 3. user_scan_rows — per-ticker payload
    row_count = 0
    if run_id and symbols:
        # The /protected/screenings UI filters user_scan_rows by
        # dataset IN ('public_screening', 'passed_stocks', 'charts_page').
        # The script_key is preserved on user_scan_runs.source.
        # row_data is JSONB — pass the dict directly so PostgREST stores it
        # natively (no double-encoding).
        rows = [
            {
                "run_id": run_id,
                "scan_date": scan_date_str,
                "dataset": script_key,
                "symbol": s.get("symbol") if isinstance(s, dict) else None,
                "row_data": s if isinstance(s, dict) else {"value": s},
                "user_id": user_id,
            }
            for s in symbols
        ]
        try:
            client.schema(_SCHEMA).table("user_scan_rows").insert(rows).execute()
            row_count = len(rows)
        except Exception as exc:
            log.warning(
                "[fan-out] user=%s: failed to insert user_scan_rows: %s", user_id, exc
            )

    log.info(
        "[fan-out] user=%s: job=%s run=%s rows=%d",
        user_id,
        job_id,
        run_id,
        row_count,
    )
    return job_id, run_id, row_count


def _fan_out_to_subscribers(result: dict[str, Any]) -> None:
    client = get_supabase_client()
    screening_id = result["screening_id"]
    name = result.get("name") or "Public screening"
    triggered = bool(result.get("triggered"))
    error = bool(result.get("error"))
    summary = result.get("summary")
    data_used = result.get("data_used", {})
    is_test = bool(result.get("is_test"))
    status = "error" if error else "done"
    now = datetime.now(timezone.utc).isoformat()
    scan_date_str = date.today().isoformat()

    subs_res = (
        client.schema(_SCHEMA)
        .table("public_screening_subscriptions")
        .select("user_id, notifications_enabled")
        .eq("public_screening_id", screening_id)
        .execute()
    )
    subscribers = subs_res.data or []
    if not subscribers:
        log.info("Public screening %s: no subscribers", screening_id)
        return

    ps_res = (
        client.schema(_SCHEMA)
        .table("public_screenings")
        .select("name, slug, script_key")
        .eq("id", screening_id)
        .limit(1)
        .execute()
    )
    public_meta = (ps_res.data or [{}])[0]
    source_label = f"public_screening:{public_meta.get('slug') or screening_id}"
    dataset_key = public_meta.get("script_key") or "public_screening"

    html = _format_telegram_message(
        name,
        ticker_count=result.get("ticker_count"),
        error=error,
        error_summary=summary if error else None,
    )
    message_type = (
        "public_screening_error"
        if error
        else "public_screening_alert" if triggered else "public_screening_no_trigger"
    )

    scan_jobs_written = 0
    scan_runs_written = 0
    delivered = 0
    skipped = 0
    failed = 0

    log.info(
        "Public screening %s: starting fan-out to %d subscriber(s)",
        screening_id,
        len(subscribers),
    )

    for sub in subscribers:
        user_id = sub["user_id"]
        notif_enabled = bool(sub.get("notifications_enabled"))
        log.info(
            "[fan-out] processing subscriber user=%s notif=%s", user_id, notif_enabled
        )

        try:
            # 1. Write the scan artefacts: user_scan_jobs + user_scan_runs +
            #    user_scan_rows. This is the only persistence path for public
            #    screenings — no user_screening_results write.
            job_id, run_id, _row_count = _write_scan_artefacts_for_subscriber(
                client,
                user_id=user_id,
                source_label=source_label,
                script_key=dataset_key,
                scan_date_str=scan_date_str,
                started_at_iso=now,
                finished_at_iso=now,
                status=status,
                error_message=summary if error else None,
                data_used=data_used,
            )
            if job_id:
                scan_jobs_written += 1
            if run_id:
                scan_runs_written += 1

            # 2. Telegram delivery — fires on every run so subscribers know
            #    fresh results are available, matching private screenings.
            if not notif_enabled:
                log.info(
                    "[fan-out] user=%s: notifications disabled, skipping Telegram",
                    user_id,
                )
                skipped += 1
                continue
            chat_id = get_user_chat_id(user_id)
            if not chat_id:
                log.info(
                    "[fan-out] user=%s: no Telegram chat connected, skipping", user_id
                )
                skipped += 1
                continue

            log.info("[fan-out] user=%s: sending Telegram to chat=%s", user_id, chat_id)
            success, msg_id, err = send_telegram_chunks(chat_id, html)
            if success:
                delivered += 1
                log.info(
                    "[fan-out] user=%s: Telegram delivered (msg_id=%s)", user_id, msg_id
                )
            else:
                failed += 1
                log.warning(
                    "[fan-out] user=%s: Telegram send FAILED: %s",
                    user_id,
                    err,
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
        except Exception as exc:
            failed += 1
            log.exception(
                "[fan-out] user=%s: unexpected error, continuing with next subscriber: %s",
                user_id,
                exc,
            )

    log.info(
        "Public screening %s fan-out done: subscribers=%d scan_jobs=%d scan_runs=%d telegram_delivered=%d telegram_skipped=%d telegram_failed=%d",
        screening_id,
        len(subscribers),
        scan_jobs_written,
        scan_runs_written,
        delivered,
        skipped,
        failed,
    )
