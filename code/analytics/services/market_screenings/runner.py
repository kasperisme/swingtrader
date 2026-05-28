"""Run a market screening script, persist the result, fan out to subscribers."""

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


def run_market_screening(
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
        log.exception("Market screening %s (%s) failed", screening["id"], script_key)
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
        "llm_prompt": screening.get("llm_prompt"),
    }


# ── Persistence + Telegram fan-out ──────────────────────────────────────────


def _split_symbols_from_data_used(
    data_used: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Pop `symbols` out of `data_used` so the per-ticker payload can be
    persisted in market_screening_result_rows instead of bloating the JSONB
    on market_screening_results. Returns (symbols, lean_data_used).
    """
    src = data_used or {}
    symbols_raw = src.get("symbols")
    symbols = symbols_raw if isinstance(symbols_raw, list) else []
    lean = {k: v for k, v in src.items() if k != "symbols"}
    return symbols, lean


def _write_market_screening_result_rows(
    client,
    *,
    market_screening_id: str,
    result_id: str,
    scan_date_str: str,
    dataset: str,
    symbols: list[dict[str, Any]],
) -> int:
    """Insert one market_screening_result_rows row per ticker. Returns inserted count."""
    if not result_id or not symbols:
        return 0
    rows = [
        {
            "market_screening_id": market_screening_id,
            "result_id": result_id,
            "scan_date": scan_date_str,
            "dataset": dataset,
            "symbol": s.get("symbol") if isinstance(s, dict) else None,
            "row_data": s if isinstance(s, dict) else {"value": s},
        }
        for s in symbols
    ]
    try:
        client.schema(_SCHEMA).table("market_screening_result_rows").insert(rows).execute()
        return len(rows)
    except Exception as exc:
        log.warning(
            "Failed to insert market_screening_result_rows for result=%s: %s",
            result_id, exc,
        )
        return 0


def persist_and_deliver_public(
    result: dict[str, Any], result_id: str | None = None
) -> None:
    """Update the shared result row, then deliver to every subscriber with notifications on."""
    client = get_supabase_client()
    now = datetime.now(timezone.utc).isoformat()
    scan_date_str = date.today().isoformat()

    is_test = bool(result.get("is_test"))
    triggered = bool(result.get("triggered"))
    error = bool(result.get("error"))
    status = "error" if error else "done"

    # Split the per-ticker symbols out of data_used. Symbols go to the
    # market_screening_result_rows table; data_used keeps only summary stats.
    symbols, lean_data_used = _split_symbols_from_data_used(result.get("data_used"))
    dataset = "trend_template"  # matches the convention used by user_scan_rows

    if result_id:
        try:
            client.schema(_SCHEMA).table("market_screening_results").update(
                {
                    "triggered": triggered,
                    "summary": result.get("summary"),
                    "data_used": lean_data_used,
                    "status": status,
                    "error": result.get("summary") if error else None,
                }
            ).eq("id", result_id).execute()
        except Exception as exc:
            log.error(
                "Failed to update market_screening_results %s: %s", result_id, exc
            )
            return
    else:
        row = {
            "market_screening_id": result["screening_id"],
            "run_at": now,
            "started_at": now,
            "triggered": triggered,
            "summary": result.get("summary"),
            "data_used": lean_data_used,
            "is_test": is_test,
            "status": status,
            "error": result.get("summary") if error else None,
        }
        try:
            ins = (
                client.schema(_SCHEMA)
                .table("market_screening_results")
                .insert(row)
                .execute()
            )
            result_id = (ins.data or [{}])[0].get("id")
        except Exception as exc:
            log.error("Failed to persist market_screening_results: %s", exc)
            return

    # Persist the per-ticker rows into the canonical table.
    if result_id:
        inserted = _write_market_screening_result_rows(
            client,
            market_screening_id=result["screening_id"],
            result_id=result_id,
            scan_date_str=scan_date_str,
            dataset=dataset,
            symbols=symbols,
        )
        log.info(
            "Market screening %s: persisted %d/%d row(s) into market_screening_result_rows",
            result["screening_id"], inserted, len(symbols),
        )

    # Update parent screening tracking columns.
    update_fields: dict[str, Any] = {
        "last_run_at": now,
        "last_triggered": triggered,
    }
    if is_test:
        update_fields["run_requested_at"] = None
    client.schema(_SCHEMA).table("market_screenings").update(
        update_fields,
    ).eq("id", result["screening_id"]).execute()

    # If an LLM bulk-analysis pass is configured AND the screening produced
    # tickers AND the run didn't error out, defer fan-out: queue the result
    # for the bulk-analytics worker, which will enrich the per-ticker rows
    # then trigger fan-out from the enriched data. Otherwise fan out now.
    llm_prompt = (result.get("llm_prompt") or "").strip()
    should_queue_bulk = (
        bool(llm_prompt) and bool(symbols) and not error and bool(result_id)
    )
    if should_queue_bulk:
        try:
            client.schema(_SCHEMA).table("market_screening_results").update(
                {"bulk_analysis_status": "queued"}
            ).eq("id", result_id).execute()
            log.info(
                "Market screening %s: queued result %s for LLM bulk-analysis (%d tickers); fan-out deferred",
                result["screening_id"], result_id, len(symbols),
            )
        except Exception as exc:
            log.exception(
                "Failed to queue bulk-analysis for result %s; falling back to immediate fan-out: %s",
                result_id, exc,
            )
            fan_out_to_subscribers(result)
        return

    fan_out_to_subscribers(result)


# ── Fan-out reconstruction (called by bulk-analytics worker) ────────────────


def fan_out_from_db(result_id: str) -> None:
    """Rebuild the fan-out payload from persisted rows and deliver to subscribers.

    Called by the market_screening_bulk_analytics worker after it has enriched
    the per-ticker `row_data` with LLM analysis. Subscribers get the enriched
    rows copied into their `user_scan_rows`, so they only see (and get notified
    about) results that include the analysis.
    """
    client = get_supabase_client()

    res_row = (
        client.schema(_SCHEMA)
        .table("market_screening_results")
        .select(
            "id, market_screening_id, triggered, summary, data_used, status, is_test"
        )
        .eq("id", result_id)
        .limit(1)
        .execute()
    )
    result_row = (res_row.data or [None])[0]
    if not result_row:
        log.warning("fan_out_from_db: result %s not found", result_id)
        return

    rows_res = (
        client.schema(_SCHEMA)
        .table("market_screening_result_rows")
        .select("symbol, row_data")
        .eq("result_id", result_id)
        .execute()
    )
    symbols = [
        (r.get("row_data") if isinstance(r.get("row_data"), dict) else {"value": r.get("row_data")})
        for r in (rows_res.data or [])
    ]

    ps_res = (
        client.schema(_SCHEMA)
        .table("market_screenings")
        .select("name, script_key")
        .eq("id", result_row["market_screening_id"])
        .limit(1)
        .execute()
    )
    ps_meta = (ps_res.data or [{}])[0]

    data_used = dict(result_row.get("data_used") or {})
    data_used["symbols"] = symbols

    payload = {
        "screening_id": result_row["market_screening_id"],
        "name": ps_meta.get("name") or "Market screening",
        "script_key": ps_meta.get("script_key"),
        "triggered": bool(result_row.get("triggered")),
        "summary": result_row.get("summary"),
        "data_used": data_used,
        "ticker_count": len(symbols),
        "error": result_row.get("status") == "error",
        "is_test": bool(result_row.get("is_test")),
    }
    fan_out_to_subscribers(payload)


def _append_market_screening_chat_turn(
    client,
    *,
    user_id: str,
    ticker: str,
    llm_prompt: str,
    analysis_markdown: str,
) -> None:
    """Append one user+assistant chat turn to a subscriber's chart workspace,
    tagged as a market-screening result.

    Mirrors the bulk-analysis pattern in
    `services.bulk_analysis.worker._append_chat_turn`. Race conditions with a
    user actively chatting on the same ticker are accepted.
    """
    sym = ticker.upper().strip()
    if not sym:
        return
    user_message = llm_prompt.strip() or "Run a technical analysis."

    res = (
        client.schema(_SCHEMA)
        .table("user_ticker_chart_workspace")
        .select("ai_chat_messages, annotations")
        .eq("user_id", user_id)
        .eq("ticker", sym)
        .limit(1)
        .execute()
    )
    existing = (res.data or [None])[0]
    messages = list((existing or {}).get("ai_chat_messages") or [])
    annotations = list((existing or {}).get("annotations") or [])

    messages.append(
        {"role": "user", "content": user_message, "source": "market_screening"}
    )
    messages.append(
        {
            "role": "assistant",
            "content": analysis_markdown,
            "chartAnnotations": [],
            "personaReports": [],
            "source": "market_screening",
        }
    )

    payload = {
        "user_id": user_id,
        "ticker": sym,
        "annotations": annotations,
        "ai_chat_messages": messages,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    client.schema(_SCHEMA).table("user_ticker_chart_workspace").upsert(
        payload, on_conflict="user_id,ticker"
    ).execute()


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
) -> tuple[int | None, int | None, int, int]:
    """Write the full scan artefacts for one subscriber.

    Inserts one user_scan_jobs row (job metadata), one user_scan_runs row
    (scan instance + payload), and N user_scan_rows (per-ticker). For any
    ticker whose row_data carries `llm_analysis` (the bulk-analytics pass
    has run), also upserts a user_scan_row_notes row carrying the LLM's
    status (active/watchlist/pipeline/dismissed), comment, and entry
    metadata — same shape services.bulk_analysis writes for its own jobs.

    Returns (job_id, run_id, row_count, notes_written). Any individual
    insert failure is logged but does not abort the others — best-effort
    delivery.
    """
    payload = data_used or {}
    symbols = payload.get("symbols") if isinstance(payload.get("symbols"), list) else []
    script_rel = f"services/market_screenings/scripts/{script_key}.py"
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

    # 3. user_scan_rows — per-ticker payload. .select() returns the inserted
    # rows in the same order they were sent so we can map each ticker back
    # to its scan_row_id for the note write below.
    row_count = 0
    inserted_rows: list[dict] = []
    if run_id and symbols:
        # The /protected/screenings UI filters user_scan_rows by
        # dataset IN ('market_screening', 'passed_stocks', 'charts_page').
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
            ins_rows = (
                client.schema(_SCHEMA)
                .table("user_scan_rows")
                .insert(rows)
                .execute()
            )
            inserted_rows = list(ins_rows.data or [])
            row_count = len(inserted_rows) or len(rows)
        except Exception as exc:
            log.warning(
                "[fan-out] user=%s: failed to insert user_scan_rows: %s", user_id, exc
            )

    # 4. user_scan_row_notes — copy the LLM's verdict into the workflow
    # state for tickers the bulk-analytics worker enriched. The status
    # comes straight from llm_analysis.status (active/watchlist/pipeline/
    # dismissed), which the parser validated against the same CHECK
    # constraint scan_row_notes carries.
    notes_written = 0
    if inserted_rows and run_id:
        notes_to_upsert: list[dict[str, Any]] = []
        for idx, payload in enumerate(symbols):
            if idx >= len(inserted_rows):
                break
            if not isinstance(payload, dict):
                continue
            llm = payload.get("llm_analysis")
            if not isinstance(llm, dict):
                continue
            llm_status = llm.get("status")
            if llm_status not in ("active", "watchlist", "pipeline", "dismissed"):
                continue
            scan_row_id = inserted_rows[idx].get("id")
            ticker = (
                payload.get("symbol")
                or inserted_rows[idx].get("symbol")
                or ""
            )
            if not scan_row_id or not ticker:
                continue
            # Always set metadata_json (default {}). PostgREST bulk upserts
            # require every object in the batch to carry identical keys, so a
            # mix of entry/no-entry tickers must not omit the key on some rows
            # — doing so fails the whole batch and writes zero notes.
            metadata_json: dict[str, Any] = {}
            entry = llm.get("entry")
            if isinstance(entry, dict) and entry.get("price") is not None:
                # Match services.bulk_analysis.worker._upsert_note's entry
                # shape so the chart UI's setTickerEntryMarker resolves it
                # the same way (by date first, then barIdx fallback).
                entry_block: dict[str, Any] = {
                    "barIdx": int(llm.get("entry_bar_idx") or 0),
                    "date": str(llm.get("entry_date") or ""),
                    "price": entry.get("price"),
                    "direction": entry.get("direction"),
                }
                if "take_profit" in entry:
                    entry_block["take_profit"] = entry["take_profit"]
                if "stop_loss" in entry:
                    entry_block["stop_loss"] = entry["stop_loss"]
                metadata_json["entry"] = entry_block
            note: dict[str, Any] = {
                "scan_row_id": scan_row_id,
                "run_id": run_id,
                "ticker": ticker,
                "user_id": user_id,
                "status": llm_status,
                "comment": ((llm.get("comment") or "").strip()[:400] or None),
                "metadata_json": metadata_json,
                "updated_at": finished_at_iso,
            }
            notes_to_upsert.append(note)

        if notes_to_upsert:
            try:
                client.schema(_SCHEMA).table("user_scan_row_notes").upsert(
                    notes_to_upsert,
                    on_conflict="scan_row_id,user_id",
                ).execute()
                notes_written = len(notes_to_upsert)
            except Exception as exc:
                log.warning(
                    "[fan-out] user=%s: failed to upsert user_scan_row_notes: %s",
                    user_id,
                    exc,
                )

    log.info(
        "[fan-out] user=%s: job=%s run=%s rows=%d notes=%d",
        user_id,
        job_id,
        run_id,
        row_count,
        notes_written,
    )
    return job_id, run_id, row_count, notes_written


def fan_out_to_subscribers(result: dict[str, Any]) -> None:
    client = get_supabase_client()
    screening_id = result["screening_id"]
    name = result.get("name") or "Market screening"
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
        .table("market_screening_subscriptions")
        .select("user_id, notifications_enabled")
        .eq("market_screening_id", screening_id)
        .execute()
    )
    subscribers = subs_res.data or []
    if not subscribers:
        log.info("Market screening %s: no subscribers", screening_id)
        return

    ps_res = (
        client.schema(_SCHEMA)
        .table("market_screenings")
        .select("name, slug, script_key, llm_prompt")
        .eq("id", screening_id)
        .limit(1)
        .execute()
    )
    market_meta = (ps_res.data or [{}])[0]
    source_label = f"market_screening:{market_meta.get('slug') or screening_id}"
    dataset_key = market_meta.get("script_key") or "market_screening"
    llm_prompt = (market_meta.get("llm_prompt") or "").strip()

    # Pre-extract symbols enriched with LLM analysis so we can fan them out
    # into each subscriber's chart-workspace chat. Symbols without
    # llm_analysis.analysis_markdown are skipped — those subscribers still
    # get the scan_rows + Telegram, just no synthetic chat turn.
    raw_symbols = data_used.get("symbols") if isinstance(data_used, dict) else None
    symbols_for_chat: list[tuple[str, str]] = []
    if llm_prompt and isinstance(raw_symbols, list):
        for s in raw_symbols:
            if not isinstance(s, dict):
                continue
            sym = (s.get("symbol") or "").strip().upper() if isinstance(s.get("symbol"), str) else ""
            llm = s.get("llm_analysis")
            md = (
                llm.get("analysis_markdown")
                if isinstance(llm, dict)
                else None
            )
            if sym and isinstance(md, str) and md.strip():
                symbols_for_chat.append((sym, md))

    html = _format_telegram_message(
        name,
        ticker_count=result.get("ticker_count"),
        error=error,
        error_summary=summary if error else None,
    )
    message_type = (
        "market_screening_error"
        if error
        else "market_screening_alert" if triggered else "market_screening_no_trigger"
    )

    scan_jobs_written = 0
    scan_runs_written = 0
    notes_written_total = 0
    chat_turns_written = 0
    delivered = 0
    skipped = 0
    failed = 0

    log.info(
        "Market screening %s: starting fan-out to %d subscriber(s)",
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
            job_id, run_id, _row_count, notes_written = (
                _write_scan_artefacts_for_subscriber(
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
            )
            if job_id:
                scan_jobs_written += 1
            if run_id:
                scan_runs_written += 1
            notes_written_total += notes_written

            # 2. Per-ticker chat turn — for every symbol the bulk-analytics
            #    worker enriched with LLM analysis, append a synthetic chat
            #    turn (tagged source="market_screening") to this subscriber's
            #    user_ticker_chart_workspace so the analysis shows up in their
            #    chat the next time they open that ticker. Mirrors the
            #    services.bulk_analysis pattern. Best-effort per ticker.
            for sym, analysis_markdown in symbols_for_chat:
                try:
                    _append_market_screening_chat_turn(
                        client,
                        user_id=user_id,
                        ticker=sym,
                        llm_prompt=llm_prompt,
                        analysis_markdown=analysis_markdown,
                    )
                    chat_turns_written += 1
                except Exception as exc:
                    log.warning(
                        "[fan-out] user=%s ticker=%s: chat append failed: %s",
                        user_id,
                        sym,
                        exc,
                    )

            # 3. Telegram delivery — fires on every run so subscribers know
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
        "Market screening %s fan-out done: subscribers=%d scan_jobs=%d scan_runs=%d notes=%d chat_turns=%d telegram_delivered=%d telegram_skipped=%d telegram_failed=%d",
        screening_id,
        len(subscribers),
        scan_jobs_written,
        scan_runs_written,
        notes_written_total,
        chat_turns_written,
        delivered,
        skipped,
        failed,
    )
