"""
Job health tracking for Mac Mini background jobs.

Upserts into swingtrader.job_health on every job start/finish.
On failure, fires a WhatsApp alert via OpenClaw CLI (OPENCLAW_CMD env var).

Usage:
    from src.health import JobHeartbeat

    with JobHeartbeat("news_ingest", expected_interval=1.0):
        run_news_pipeline()

Environment variables:
    OPENCLAW_CMD          — path to openclaw binary (default: "openclaw" on PATH)
    OPENCLAW_WHATSAPP_TO  — recipient phone number, e.g. "+15555550123"
"""

from __future__ import annotations

import logging
import os
import subprocess
import traceback
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Generator, Optional

logger = logging.getLogger(__name__)


def _system_exit_is_failure(exc: SystemExit) -> bool:
    """True when ``SystemExit`` should be recorded as a failed job (e.g. argparse code 2)."""
    code = exc.code
    if code is None or code is False:
        return False
    if isinstance(code, int):
        return code != 0
    # ``sys.exit("message")`` stores a string (truthy) — treat as failure.
    return True


class PartialJobFailure(Exception):
    """
    Raise inside a JobHeartbeat block when some work items failed but others
    succeeded.  JobHeartbeat records status='partial_fail' (instead of
    'failed') and still fires a WhatsApp alert, but does NOT re-raise so the
    cron process exits 0.

    Example:
        processed, failed = await generate_all()
        if failed and processed:
            raise PartialJobFailure(f"{len(failed)} users failed: {failed}")
        elif failed:
            raise RuntimeError(f"All {len(failed)} users failed: {failed}")
    """


def _upsert_job(job_name: str, fields: dict[str, Any]) -> None:
    """Write job health fields to Supabase, silently swallowing errors."""
    try:
        from src.db import get_supabase_client, get_schema
        client = get_supabase_client()
        schema = get_schema()
        client.schema(schema).table("job_health").upsert(
            {"job_name": job_name, **fields},
            on_conflict="job_name",
        ).execute()
    except Exception as exc:
        logger.warning("[health] upsert failed for %s: %s", job_name, exc)


def _insert_run(
    job_name: str,
    started_at: str,
    finished_at: str,
    status: str,
    duration_s: float,
    error: Optional[str],
) -> None:
    """Append one row to job_runs. Silently swallows errors."""
    try:
        from src.db import get_supabase_client, get_schema
        client = get_supabase_client()
        schema = get_schema()
        client.schema(schema).table("job_runs").insert({
            "job_name": job_name,
            "started_at": started_at,
            "finished_at": finished_at,
            "status": status,
            "duration_s": round(duration_s, 2),
            "error": error,
        }).execute()
    except Exception as exc:
        logger.warning("[health] job_runs insert failed for %s: %s", job_name, exc)


def _is_already_running(job_name: str) -> bool:
    """Return True if job_health shows this job is currently running."""
    try:
        from src.db import get_supabase_client, get_schema
        client = get_supabase_client()
        schema = get_schema()
        res = (
            client.schema(schema)
            .table("job_health")
            .select("last_status")
            .eq("job_name", job_name)
            .limit(1)
            .execute()
        )
        return (res.data or [{}])[0].get("last_status") == "running"
    except Exception:
        return False


def update_job_metadata(job_name: str, metadata: dict[str, Any]) -> None:
    """
    Merge extra metadata into an existing job_health row.
    Call this after JobHeartbeat exits to attach run-time stats.

    Example:
        update_job_metadata("watchdog", {"alerts_fired": 2, "jobs_checked": 8})
    """
    _upsert_job(job_name, {"metadata": metadata})


def _get_consecutive_fails(job_name: str) -> int:
    try:
        from src.db import get_supabase_client, get_schema
        client = get_supabase_client()
        schema = get_schema()
        res = (
            client.schema(schema)
            .table("job_health")
            .select("consecutive_fails")
            .eq("job_name", job_name)
            .limit(1)
            .execute()
        )
        return int((res.data or [{}])[0].get("consecutive_fails") or 0)
    except Exception:
        return 0


def send_whatsapp_alert(message: str) -> None:
    """
    Fire a WhatsApp message via OpenClaw CLI.

    Required env vars:
        OPENCLAW_CMD          — path to openclaw binary, e.g. "/usr/local/bin/openclaw"
        OPENCLAW_WHATSAPP_TO  — recipient phone number, e.g. "+15555550123"

    Equivalent to:
        openclaw message send --target +15555550123 --message "..."
    """
    cmd = os.environ.get("OPENCLAW_CMD", "openclaw").strip()
    recipient = os.environ.get("OPENCLAW_WHATSAPP_TO", "").strip()
    if not recipient:
        logger.warning("[health] OPENCLAW_WHATSAPP_TO not set — skipping WhatsApp alert")
        return
    try:
        subprocess.run(
            [cmd, "message", "send", "--channel", "whatsapp", "--target", recipient, "--message", message],
            timeout=30,
            check=False,
        )
        logger.info("[health] WhatsApp alert sent to %s", recipient)
    except Exception as exc:
        logger.warning("[health] WhatsApp alert failed: %s", exc)


@contextmanager
def JobHeartbeat(
    job_name: str,
    expected_interval: Optional[float] = None,
    metadata: Optional[dict] = None,
) -> Generator[None, None, None]:
    """
    Context manager that tracks job lifecycle in swingtrader.job_health.

    - Upserts status='running' on entry.
    - On clean exit: upserts status='success', resets consecutive_fails.
    - On exception: upserts status='failed', increments consecutive_fails,
      sends a WhatsApp alert, then re-raises.
    - ``SystemExit`` with a non-zero / non-clean code (e.g. argparse) is recorded
      as ``failed`` then re-raised so the process exit code is preserved.
    - ``KeyboardInterrupt`` is recorded as ``failed`` then re-raised.

    Args:
        job_name: Unique stable identifier, e.g. "news_ingest", "daily_narrative".
        expected_interval: Expected run cadence in hours (stored for dashboard
                             staleness checks). e.g. 1.0 for hourly, 24.0 for daily.
        metadata: Optional dict stored as JSONB (e.g. args, counts).
    """
    started_at = datetime.now(timezone.utc)

    # Only mark as 'running' if no other instance is already running.
    # This prevents concurrent cron runs from clobbering each other's state —
    # the first instance to start owns the row until it finishes.
    already_running = _is_already_running(job_name)
    if not already_running:
        start_fields: dict[str, Any] = {
            "last_started_at": started_at.isoformat(),
            "last_status": "running",
            "last_error": None,
        }
        if expected_interval is not None:
            start_fields["expected_interval"] = expected_interval
        if metadata:
            start_fields["metadata"] = metadata
        _upsert_job(job_name, start_fields)
    error_text: Optional[str] = None
    partial_failure: Optional[PartialJobFailure] = None
    try:
        yield
    except PartialJobFailure as exc:
        # Capture but do NOT re-raise — partial failures are not fatal.
        partial_failure = exc
        error_text = str(exc)
    except SystemExit as exc:
        if _system_exit_is_failure(exc):
            error_text = f"SystemExit({exc.code!r})"
        raise
    except KeyboardInterrupt as exc:
        error_text = f"KeyboardInterrupt: {exc!r}"
        raise
    except Exception:
        error_text = traceback.format_exc()
        raise
    finally:
        finished_at = datetime.now(timezone.utc)
        finished_iso = finished_at.isoformat()
        duration_s = (finished_at - started_at).total_seconds()

        if partial_failure is not None:
            status = "partial_fail"
        elif error_text:
            status = "failed"
        else:
            status = "success"

        # ── Append to job_runs history ─────────────────────────────────────
        _insert_run(
            job_name=job_name,
            started_at=started_at.isoformat(),
            finished_at=finished_iso,
            status=status,
            duration_s=duration_s,
            error=error_text[:2000] if error_text else None,
        )

        # ── Update job_health current state ────────────────────────────────
        if status in ("failed", "partial_fail"):
            fails = _get_consecutive_fails(job_name) + 1
            _upsert_job(job_name, {
                "last_finished_at": finished_iso,
                "last_status": status,
                "last_error": error_text[:2000] if error_text else None,
                "consecutive_fails": fails,
            })
            alert_prefix = "Job PARTIAL FAIL" if status == "partial_fail" else "Job FAILED"
            send_whatsapp_alert(
                f"[SwingTrader] {alert_prefix}: {job_name}\n"
                f"Consecutive failures: {fails}\n\n"
                f"{(error_text or '')[:600]}"
            )
        else:
            _upsert_job(job_name, {
                "last_finished_at": finished_iso,
                "last_status": "success",
                "last_error": None,
                "consecutive_fails": 0,
            })
