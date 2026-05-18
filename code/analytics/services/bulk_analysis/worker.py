"""
Bulk per-ticker technical-analysis worker.

For one job:
  - load tickers from user_scan_rows
  - fetch FMP daily candles + SMAs
  - call Ollama once per ticker (bounded concurrency)
  - append a synthetic chat turn to user_ticker_chart_workspace.ai_chat_messages
  - upsert user_scan_row_notes.status (+ comment)
  - keep the job row's progress counters fresh
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any

from shared.db import get_supabase_client
from shared.llm import client as llm_client

from . import fetch, prompt
from .chart_granularity import DEFAULT_GRANULARITY, normalize_granularity

log = logging.getLogger(__name__)

SCHEMA = "swingtrader"
DEFAULT_CONCURRENCY = int(os.environ.get("BULK_ANALYSIS_CONCURRENCY", "2"))
DEFAULT_PER_TICKER_TIMEOUT = float(os.environ.get("BULK_ANALYSIS_TIMEOUT", "90"))
DEFAULT_MODEL = os.environ.get("BULK_ANALYSIS_MODEL")  # None → backend default
DEFAULT_SUMMARY_TIMEOUT = float(os.environ.get("BULK_ANALYSIS_SUMMARY_TIMEOUT", "90"))


# ── Job lifecycle ────────────────────────────────────────────────────────────


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_job(job_id: str) -> dict | None:
    client = get_supabase_client()
    res = (
        client.schema(SCHEMA)
        .table("user_bulk_analysis_jobs")
        .select("*")
        .eq("id", job_id)
        .limit(1)
        .execute()
    )
    return (res.data or [None])[0]


def _load_trading_strategy(user_id: str) -> str:
    """Saved strategy from profile (``user_trading_strategy``), same source as chart AI."""
    client = get_supabase_client()
    res = (
        client.schema(SCHEMA)
        .table("user_trading_strategy")
        .select("strategy")
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    row = (res.data or [None])[0]
    if not row:
        return ""
    return str(row.get("strategy") or "").strip()


def _load_scan_rows(
    scan_run_id: int,
    user_id: str,
    ticker_subset: list[str] | None = None,
) -> list[dict]:
    """Return [{scan_row_id, ticker}] for rows in the scan run.

    When ``ticker_subset`` is provided, only rows whose symbol is in that
    list are returned. The UI snapshots the visible filtered tickers at
    submit time, so the worker analyses exactly what the user saw —
    not every ticker in the underlying scan run.
    """
    client = get_supabase_client()
    res = (
        client.schema(SCHEMA)
        .table("user_scan_rows")
        .select("id, symbol")
        .eq("run_id", scan_run_id)
        .eq("user_id", user_id)
        .execute()
    )
    allow: set[str] | None = None
    if ticker_subset:
        allow = {s.strip().upper() for s in ticker_subset if s and s.strip()}
        if not allow:
            allow = None  # treat empty subset same as None (analyse all)

    rows = []
    seen: set[str] = set()
    for r in res.data or []:
        sym = (r.get("symbol") or "").strip().upper()
        if not sym or sym in seen:
            continue
        if allow is not None and sym not in allow:
            continue
        seen.add(sym)
        rows.append({"scan_row_id": int(r["id"]), "ticker": sym})
    return rows


def _set_job(job_id: str, **fields: Any) -> None:
    client = get_supabase_client()
    client.schema(SCHEMA).table("user_bulk_analysis_jobs").update(fields).eq(
        "id", job_id
    ).execute()


def _get_bulk_chat_messages(job: dict) -> list[dict[str, Any]]:
    raw = job.get("bulk_chat_messages")
    return list(raw) if isinstance(raw, list) else []


def _set_bulk_chat_messages(job_id: str, messages: list[dict[str, Any]]) -> None:
    _set_job(job_id, bulk_chat_messages=messages)


def _ensure_user_bulk_chat_message(job: dict, user_prompt: str | None) -> None:
    """Keep a single user turn at the start of the All-tickers thread."""
    messages = _get_bulk_chat_messages(job)
    if any(m.get("role") == "user" for m in messages):
        return
    text = (user_prompt or "").strip() or prompt.DEFAULT_USER_INSTRUCTION
    _set_bulk_chat_messages(
        job["id"],
        [{"role": "user", "content": text, "source": "bulk_analysis"}],
    )


async def _finalize_bulk_chat(
    *,
    job: dict,
    job_status: str,
    total: int,
    succeeded: int,
    failed: int,
    status_counts: dict[str, int],
    trading_strategy: str,
    error_message: str | None = None,
) -> None:
    """Append assistant summary to ``bulk_chat_messages`` for the All-tickers tab."""
    job_id = job["id"]
    chart_granularity = normalize_granularity(
        job.get("chart_granularity") or DEFAULT_GRANULARITY
    )
    chart_date_from = job.get("chart_date_from")
    chart_date_to = job.get("chart_date_to")
    if chart_date_from is not None:
        chart_date_from = str(chart_date_from)[:10]
    if chart_date_to is not None:
        chart_date_to = str(chart_date_to)[:10]
    user_prompt = job.get("user_prompt")

    summary_prompt = prompt.build_bulk_summary_prompt(
        job_status=job_status,
        total=total,
        succeeded=succeeded,
        failed=failed,
        status_counts=status_counts,
        user_prompt=user_prompt,
        chart_granularity=chart_granularity,
        chart_date_from=chart_date_from,
        chart_date_to=chart_date_to,
        error_message=error_message,
    )
    system = prompt.with_trading_strategy(
        prompt.BULK_SUMMARY_SYSTEM, trading_strategy
    )
    try:
        text, _latency = await llm_client.chat(
            prompt=summary_prompt,
            system=system,
            backend="ollama",
            model=DEFAULT_MODEL,
            timeout=DEFAULT_SUMMARY_TIMEOUT,
        )
        summary = (text or "").strip()
        if not summary:
            raise ValueError("empty summary")
    except Exception as exc:
        log.warning("Bulk job %s: summary LLM failed, using fallback: %s", job_id[:8], exc)
        summary = prompt.format_bulk_summary_fallback(
            job_status=job_status,
            total=total,
            succeeded=succeeded,
            failed=failed,
            status_counts=status_counts,
            chart_granularity=chart_granularity,
            error_message=error_message,
        )

    fresh = _load_job(job_id) or job
    await asyncio.to_thread(_ensure_user_bulk_chat_message, fresh, user_prompt)
    messages = _get_bulk_chat_messages(_load_job(job_id) or fresh)
    # Drop prior assistant summaries for this job so re-runs replace the recap.
    messages = [m for m in messages if m.get("role") != "assistant"]
    messages.append(
        {"role": "assistant", "content": summary, "source": "bulk_analysis"}
    )
    await asyncio.to_thread(_set_bulk_chat_messages, job_id, messages)


def _bump_completed(job_id: str, *, failed: bool) -> None:
    """Increment completed/failed counters atomically via SQL RPC fallback."""
    client = get_supabase_client()
    # PostgREST doesn't expose increments directly via the table API; fetch
    # current counters and write back. Race-safe enough at our scale (one
    # worker process per job).
    res = (
        client.schema(SCHEMA)
        .table("user_bulk_analysis_jobs")
        .select("completed_tickers, failed_tickers")
        .eq("id", job_id)
        .single()
        .execute()
    )
    cur = res.data or {}
    completed = int(cur.get("completed_tickers") or 0) + 1
    failed_count = int(cur.get("failed_tickers") or 0) + (1 if failed else 0)
    _set_job(job_id, completed_tickers=completed, failed_tickers=failed_count)


# ── Workspace + note writes ──────────────────────────────────────────────────


def _append_chat_turn(
    user_id: str,
    ticker: str,
    user_message: str,
    analysis_markdown: str,
) -> None:
    """
    Read-modify-write append of one user/assistant turn to
    user_ticker_chart_workspace.ai_chat_messages. Race conditions with a
    user actively chatting on the same ticker are accepted at v1.
    """
    client = get_supabase_client()
    sym = ticker.upper().strip()

    res = (
        client.schema(SCHEMA)
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
        {"role": "user", "content": user_message, "source": "bulk_analysis"}
    )
    messages.append(
        {
            "role": "assistant",
            "content": analysis_markdown,
            "chartAnnotations": [],
            "personaReports": [],
            "source": "bulk_analysis",
        }
    )

    payload = {
        "user_id": user_id,
        "ticker": sym,
        "annotations": annotations,
        "ai_chat_messages": messages,
        "updated_at": _now(),
    }
    client.schema(SCHEMA).table("user_ticker_chart_workspace").upsert(
        payload, on_conflict="user_id,ticker"
    ).execute()


def _upsert_note(
    *,
    user_id: str,
    scan_row_id: int,
    run_id: int,
    ticker: str,
    status: str,
    comment: str,
    entry: dict[str, Any] | None = None,
    entry_bar_idx: int | None = None,
    entry_date: str | None = None,
) -> None:
    client = get_supabase_client()
    payload: dict[str, Any] = {
        "scan_row_id": scan_row_id,
        "run_id": run_id,
        "ticker": ticker,
        "user_id": user_id,
        "status": status,
        "comment": comment or None,
        "updated_at": _now(),
    }
    if entry:
        # Merge with existing metadata so we don't clobber other keys (e.g. tags,
        # legacy pivots). The UI's setTickerEntryMarker uses the same shape:
        # metadata_json.entry = { barIdx, date, price, direction, take_profit?, stop_loss? }
        existing = (
            client.schema(SCHEMA)
            .table("user_scan_row_notes")
            .select("metadata_json")
            .eq("scan_row_id", scan_row_id)
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        meta_raw = (existing.data or [{}])[0].get("metadata_json") or {}
        meta: dict[str, Any] = dict(meta_raw) if isinstance(meta_raw, dict) else {}
        # Drop legacy pivot keys when we write a new entry, mirroring the UI.
        meta.pop("pivot", None)
        meta.pop("pivot_points", None)
        meta["entry"] = {
            "barIdx": entry_bar_idx if entry_bar_idx is not None else 0,
            "date": entry_date or "",
            "price": entry["price"],
            "direction": entry["direction"],
            **({"take_profit": entry["take_profit"]} if "take_profit" in entry else {}),
            **({"stop_loss": entry["stop_loss"]} if "stop_loss" in entry else {}),
        }
        payload["metadata_json"] = meta
    client.schema(SCHEMA).table("user_scan_row_notes").upsert(
        payload,
        on_conflict="scan_row_id,user_id",
    ).execute()


# ── Per-ticker processing ────────────────────────────────────────────────────


async def _process_ticker(
    *,
    job_id: str,
    user_id: str,
    scan_row_id: int,
    run_id: int,
    ticker: str,
    user_prompt: str | None,
    chart_granularity: str,
    chart_date_from: str | None,
    chart_date_to: str | None,
    system_prompt: str,
) -> str | None:
    """Returns assigned row status on success, None on any handled failure."""
    try:
        # FMP fetch is synchronous; run in a thread so we don't block the loop.
        df = await asyncio.to_thread(
            fetch.fetch_history,
            ticker,
            granularity=chart_granularity,
            date_from=chart_date_from,
            date_to=chart_date_to,
        )
        snapshot = fetch.summarize_for_prompt(df, granularity=chart_granularity)
        if not snapshot:
            raise RuntimeError("no candles returned")

        text, _latency = await llm_client.chat(
            prompt=prompt.build_user_prompt(ticker, snapshot, user_prompt),
            system=system_prompt,
            backend="ollama",
            model=DEFAULT_MODEL,
            timeout=DEFAULT_PER_TICKER_TIMEOUT,
        )
        parsed = prompt.parse_response(text)

        chat_user_msg = (user_prompt or "").strip() or prompt.DEFAULT_USER_INSTRUCTION
        await asyncio.to_thread(
            _append_chat_turn,
            user_id,
            ticker,
            chat_user_msg,
            parsed["analysis_markdown"],
        )
        entry = parsed.get("entry")
        # The UI resolves bar position by `date` first; barIdx is a fallback.
        # Use the snapshot's last bar as the anchor when the LLM proposes one.
        entry_bar_idx = (
            int(snapshot.get("bars_total") or 0) - 1 if entry else None
        )
        if entry_bar_idx is not None and entry_bar_idx < 0:
            entry_bar_idx = 0
        entry_date = str(snapshot.get("last_date") or "") if entry else None

        await asyncio.to_thread(
            _upsert_note,
            user_id=user_id,
            scan_row_id=scan_row_id,
            run_id=run_id,
            ticker=ticker,
            status=parsed["status"],
            comment=parsed["comment"],
            entry=entry,
            entry_bar_idx=entry_bar_idx,
            entry_date=entry_date,
        )
        await asyncio.to_thread(_bump_completed, job_id, failed=False)
        log.info("[%s] %s → %s", job_id[:8], ticker, parsed["status"])
        return parsed["status"]
    except Exception as exc:  # noqa: BLE001 — keep one bad ticker from killing the job
        log.warning("[%s] %s failed: %s", job_id[:8], ticker, exc)
        try:
            await asyncio.to_thread(_bump_completed, job_id, failed=True)
        except Exception:
            log.exception("counter bump failed for %s", ticker)
        return None


# ── Job entry point ──────────────────────────────────────────────────────────


async def _run_job_async(job: dict) -> dict:
    job_id = job["id"]
    user_id = job["user_id"]
    scan_run_id = int(job["scan_run_id"])
    user_prompt = (job.get("user_prompt") or None)
    ticker_subset_raw = job.get("ticker_subset")
    ticker_subset: list[str] | None = (
        [str(s) for s in ticker_subset_raw]
        if isinstance(ticker_subset_raw, list) and ticker_subset_raw
        else None
    )
    chart_granularity = normalize_granularity(
        job.get("chart_granularity") or DEFAULT_GRANULARITY
    )
    chart_date_from = job.get("chart_date_from")
    chart_date_to = job.get("chart_date_to")
    if chart_date_from is not None:
        chart_date_from = str(chart_date_from)[:10]
    if chart_date_to is not None:
        chart_date_to = str(chart_date_to)[:10]

    rows, trading_strategy = await asyncio.gather(
        asyncio.to_thread(_load_scan_rows, scan_run_id, user_id, ticker_subset),
        asyncio.to_thread(_load_trading_strategy, user_id),
    )
    system_prompt = prompt.build_system(trading_strategy)
    if trading_strategy:
        log.info("Bulk job %s: loaded user trading strategy (%d chars)", job_id, len(trading_strategy))
    if not rows:
        err = (
            "no tickers matched the requested filters"
            if ticker_subset
            else "scan run has no tickers"
        )
        _set_job(
            job_id,
            status="error",
            error_message=err,
            finished_at=_now(),
        )
        await _finalize_bulk_chat(
            job={**job, "user_prompt": user_prompt},
            job_status="error",
            total=0,
            succeeded=0,
            failed=0,
            status_counts={},
            trading_strategy=trading_strategy,
            error_message=err,
        )
        return {"status": "error", "tickers": 0}

    log.info(
        "Bulk job %s: granularity=%s date=%s..%s tickers=%d%s",
        job_id,
        chart_granularity,
        chart_date_from or "(default)",
        chart_date_to or "(default)",
        len(rows),
        f" subset={len(ticker_subset)}" if ticker_subset else "",
    )

    await asyncio.to_thread(_ensure_user_bulk_chat_message, job, user_prompt)

    _set_job(
        job_id,
        status="running",
        started_at=_now(),
        total_tickers=len(rows),
        completed_tickers=0,
        failed_tickers=0,
    )

    status_counts: dict[str, int] = {}
    sem = asyncio.Semaphore(DEFAULT_CONCURRENCY)

    async def _guarded(row: dict) -> bool:
        async with sem:
            return await _process_ticker(
                job_id=job_id,
                user_id=user_id,
                scan_row_id=row["scan_row_id"],
                run_id=scan_run_id,
                ticker=row["ticker"],
                user_prompt=user_prompt,
                chart_granularity=chart_granularity,
                chart_date_from=chart_date_from,
                chart_date_to=chart_date_to,
                system_prompt=system_prompt,
            )

    results = await asyncio.gather(*(_guarded(r) for r in rows))
    for row_status in results:
        if row_status:
            status_counts[row_status] = status_counts.get(row_status, 0) + 1
    succeeded = sum(1 for s in results if s)
    failed = len(results) - succeeded

    _set_job(
        job_id,
        status="done",
        finished_at=_now(),
        completed_tickers=succeeded + failed,
        failed_tickers=failed,
    )
    await _finalize_bulk_chat(
        job={**job, "user_prompt": user_prompt},
        job_status="done",
        total=len(rows),
        succeeded=succeeded,
        failed=failed,
        status_counts=status_counts,
        trading_strategy=trading_strategy,
    )
    return {"status": "done", "tickers": len(rows), "succeeded": succeeded, "failed": failed}


def run_job(job_id: str) -> dict:
    """Sync entry point used by the CLI subprocess."""
    job = _load_job(job_id)
    if not job:
        return {"status": "error", "error": "job not found"}
    if job.get("status") not in ("queued", "running"):
        return {"status": "skipped", "current_status": job.get("status")}

    try:
        return asyncio.run(_run_job_async(job))
    except Exception as exc:  # noqa: BLE001
        log.exception("Bulk job %s failed", job_id)
        err = str(exc)[:1000]
        _set_job(
            job_id,
            status="error",
            error_message=err,
            finished_at=_now(),
        )
        try:
            j = _load_job(job_id) or job
            strategy = await asyncio.to_thread(_load_trading_strategy, j["user_id"])
            await _finalize_bulk_chat(
                job=j,
                job_status="error",
                total=int(j.get("total_tickers") or 0),
                succeeded=0,
                failed=int(j.get("total_tickers") or 0),
                status_counts={},
                trading_strategy=strategy,
                error_message=err,
            )
        except Exception:
            log.exception("Bulk job %s: failed to write bulk chat summary", job_id)
        return {"status": "error", "error": str(exc)}
