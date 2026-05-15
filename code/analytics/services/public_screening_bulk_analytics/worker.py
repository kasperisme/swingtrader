"""
Public-screening bulk LLM analytics worker.

For one queued `public_screening_results` row:
  - load the parent screening (for `llm_prompt`) and the per-ticker rows
  - fetch FMP daily candles + SMAs (reused from services.bulk_analysis.fetch)
  - call the LLM once per ticker (bounded concurrency)
  - merge {status, comment, analysis_markdown, entry} into row_data and write back
  - update bulk_analysis_status on the result row
  - trigger fan-out to subscribers from the now-enriched DB rows
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any

from shared.db import get_supabase_client
from shared.llm import client as llm_client

# Reuse the existing single-pass technical-analysis pipeline. The parser
# and user-prompt builder are shared with services.bulk_analysis; the
# SYSTEM prompt is screening-specific (no baked-in status semantics) so
# each public screening's `llm_prompt` can define its own status rubric
# (e.g. momentum screenings using statuses as a breakout timeline).
from services.bulk_analysis import fetch, prompt as bulk_prompt
from services.public_screenings.runner import fan_out_from_db

from . import prompt as ps_prompt

log = logging.getLogger(__name__)

SCHEMA = "swingtrader"
DEFAULT_CONCURRENCY = int(os.environ.get("PUBLIC_BULK_ANALYSIS_CONCURRENCY", "2"))
DEFAULT_PER_TICKER_TIMEOUT = float(
    os.environ.get("PUBLIC_BULK_ANALYSIS_TIMEOUT", "90")
)
DEFAULT_MODEL = os.environ.get("PUBLIC_BULK_ANALYSIS_MODEL")  # None → backend default
DEFAULT_BACKEND = os.environ.get("PUBLIC_BULK_ANALYSIS_BACKEND", "ollama")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Loaders ──────────────────────────────────────────────────────────────────


def _load_result(result_id: str) -> dict | None:
    client = get_supabase_client()
    res = (
        client.schema(SCHEMA)
        .table("public_screening_results")
        .select("id, public_screening_id, status, bulk_analysis_status")
        .eq("id", result_id)
        .limit(1)
        .execute()
    )
    return (res.data or [None])[0]


def _load_screening(screening_id: str) -> dict | None:
    client = get_supabase_client()
    res = (
        client.schema(SCHEMA)
        .table("public_screenings")
        .select("id, name, llm_prompt")
        .eq("id", screening_id)
        .limit(1)
        .execute()
    )
    return (res.data or [None])[0]


def _load_result_rows(result_id: str) -> list[dict]:
    client = get_supabase_client()
    res = (
        client.schema(SCHEMA)
        .table("public_screening_result_rows")
        .select("id, symbol, row_data")
        .eq("result_id", result_id)
        .execute()
    )
    out: list[dict] = []
    for r in res.data or []:
        sym = (r.get("symbol") or "").strip().upper()
        if not sym:
            continue
        out.append(
            {
                "row_id": int(r["id"]),
                "ticker": sym,
                "row_data": dict(r.get("row_data") or {}),
            }
        )
    return out


def _set_result(result_id: str, **fields: Any) -> None:
    client = get_supabase_client()
    client.schema(SCHEMA).table("public_screening_results").update(fields).eq(
        "id", result_id
    ).execute()


# ── Per-ticker enrichment ────────────────────────────────────────────────────


def _merge_analysis_into_row(
    row_data: dict, parsed: dict, snapshot: dict | None = None
) -> dict:
    """Return a new dict with LLM analysis merged under a stable namespace.

    When `entry` is present, also stash the snapshot's last bar as the
    anchor (`entry_bar_idx`, `entry_date`) so the fan-out can populate
    user_scan_row_notes.metadata_json.entry in the same shape
    services.bulk_analysis writes (the chart UI resolves the marker by
    `date` first, with `barIdx` as a fallback).
    """
    merged = dict(row_data)
    entry = parsed.get("entry")
    entry_bar_idx: int | None = None
    entry_date: str | None = None
    if entry and snapshot:
        bars_total = int(snapshot.get("bars_total") or 0)
        entry_bar_idx = max(0, bars_total - 1)
        entry_date = str(snapshot.get("last_date") or "") or None
    merged["llm_analysis"] = {
        "status": parsed["status"],
        "comment": parsed["comment"],
        "analysis_markdown": parsed["analysis_markdown"],
        "entry": entry,
        "entry_bar_idx": entry_bar_idx,
        "entry_date": entry_date,
        "generated_at": _now(),
    }
    return merged


def _write_row_data(row_id: int, row_data: dict) -> None:
    client = get_supabase_client()
    client.schema(SCHEMA).table("public_screening_result_rows").update(
        {"row_data": row_data}
    ).eq("id", row_id).execute()


async def _process_ticker(
    *,
    result_id: str,
    row_id: int,
    ticker: str,
    row_data: dict,
    llm_prompt: str,
) -> bool:
    try:
        df = await asyncio.to_thread(fetch.fetch_history, ticker)
        snapshot = fetch.summarize_for_prompt(df)
        if not snapshot:
            raise RuntimeError("no candles returned")

        text, _latency = await llm_client.chat(
            prompt=bulk_prompt.build_user_prompt(ticker, snapshot, llm_prompt),
            system=ps_prompt.SYSTEM,
            backend=DEFAULT_BACKEND,
            model=DEFAULT_MODEL,
            timeout=DEFAULT_PER_TICKER_TIMEOUT,
        )
        parsed = bulk_prompt.parse_response(text)

        merged = _merge_analysis_into_row(row_data, parsed, snapshot=snapshot)
        await asyncio.to_thread(_write_row_data, row_id, merged)
        log.info("[%s] %s → %s", result_id[:8], ticker, parsed["status"])
        return True
    except Exception as exc:  # noqa: BLE001 — keep one bad ticker from killing the pass
        log.warning("[%s] %s failed: %s", result_id[:8], ticker, exc)
        return False


# ── Pass entry point ─────────────────────────────────────────────────────────


async def _run_pass_async(result: dict, screening: dict) -> dict:
    result_id = result["id"]
    llm_prompt = (screening.get("llm_prompt") or "").strip()
    if not llm_prompt:
        _set_result(
            result_id,
            bulk_analysis_status="error",
            bulk_analysis_error="screening has no llm_prompt",
            bulk_analysis_finished_at=_now(),
        )
        return {"status": "error", "tickers": 0, "reason": "no llm_prompt"}

    rows = await asyncio.to_thread(_load_result_rows, result_id)
    if not rows:
        # Nothing to enrich — mark done and fan out the empty result so
        # subscribers still get the (no-trigger) notification.
        _set_result(
            result_id,
            bulk_analysis_status="done",
            bulk_analysis_started_at=_now(),
            bulk_analysis_finished_at=_now(),
        )
        await asyncio.to_thread(fan_out_from_db, result_id)
        return {"status": "done", "tickers": 0}

    _set_result(
        result_id,
        bulk_analysis_status="running",
        bulk_analysis_started_at=_now(),
    )

    sem = asyncio.Semaphore(DEFAULT_CONCURRENCY)

    async def _guarded(row: dict) -> bool:
        async with sem:
            return await _process_ticker(
                result_id=result_id,
                row_id=row["row_id"],
                ticker=row["ticker"],
                row_data=row["row_data"],
                llm_prompt=llm_prompt,
            )

    results = await asyncio.gather(*(_guarded(r) for r in rows))
    succeeded = sum(1 for ok in results if ok)
    failed = len(results) - succeeded

    _set_result(
        result_id,
        bulk_analysis_status="done",
        bulk_analysis_finished_at=_now(),
    )

    # Fan out from the enriched DB rows. Best-effort — if it fails we still
    # leave the analysis persisted so the public page renders correctly.
    try:
        await asyncio.to_thread(fan_out_from_db, result_id)
    except Exception:
        log.exception("fan_out_from_db failed for result %s", result_id)

    return {
        "status": "done",
        "tickers": len(rows),
        "succeeded": succeeded,
        "failed": failed,
    }


def run_pass(result_id: str) -> dict:
    """Sync entry point used by the CLI subprocess."""
    result = _load_result(result_id)
    if not result:
        return {"status": "error", "error": "result not found"}
    if result.get("bulk_analysis_status") not in ("queued", "running"):
        return {
            "status": "skipped",
            "current_status": result.get("bulk_analysis_status"),
        }

    screening = _load_screening(result["public_screening_id"])
    if not screening:
        _set_result(
            result_id,
            bulk_analysis_status="error",
            bulk_analysis_error="parent screening not found",
            bulk_analysis_finished_at=_now(),
        )
        return {"status": "error", "error": "screening not found"}

    try:
        return asyncio.run(_run_pass_async(result, screening))
    except Exception as exc:  # noqa: BLE001
        log.exception("Public bulk-analysis pass %s failed", result_id)
        _set_result(
            result_id,
            bulk_analysis_status="error",
            bulk_analysis_error=str(exc)[:1000],
            bulk_analysis_finished_at=_now(),
        )
        return {"status": "error", "error": str(exc)}
