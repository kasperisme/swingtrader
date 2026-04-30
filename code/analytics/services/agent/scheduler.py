"""
scheduler.py — Single-cron tick scheduler for screening agent.

Called every minute by one OpenClaw cron job. Evaluates which screenings are
due (via croniter), enforces a concurrency limit, and launches each due
screening as a background subprocess that updates its own DB result row.
"""

from __future__ import annotations

import logging
import os
import pathlib
import subprocess
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from croniter import croniter
from dateutil.parser import parse as parse_dt

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

_ANALYTICS = pathlib.Path(__file__).resolve().parent.parent.parent
_VENV_PYTHON = str(_ANALYTICS / ".venv" / "bin" / "python")
if not os.path.exists(_VENV_PYTHON):
    _VENV_PYTHON = "python3"

# How many screenings may run at the same time. Override via env var.
MAX_CONCURRENT = int(os.environ.get("SCREENING_MAX_CONCURRENT", "1"))

# Jobs still marked 'running' after this many minutes are considered stuck.
STUCK_TIMEOUT_MINUTES = int(os.environ.get("SCREENING_STUCK_TIMEOUT_MINUTES", "20"))


def _is_due(screening: dict, now_utc: datetime) -> bool:
    """Return True if this screening's cron schedule fired within the last minute."""
    schedule = (screening.get("schedule") or "0 7 * * 1-5").strip()
    parts = schedule.split()
    if len(parts) != 5:
        schedule = "0 7 * * 1-5"

    tz_name = screening.get("timezone") or "America/New_York"
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("America/New_York")

    try:
        now_local_naive = now_utc.astimezone(tz).replace(tzinfo=None)
        prev_naive = croniter(schedule, now_local_naive).get_prev(datetime)

        # Must have fired within the last 90 seconds (tolerates slight cron drift).
        age_seconds = (now_local_naive - prev_naive).total_seconds()
        if not (0 <= age_seconds <= 90):
            return False

        # Already ran after this scheduled time → skip.
        last_run_at = screening.get("last_run_at")
        if last_run_at:
            last_run_local = parse_dt(last_run_at).astimezone(tz).replace(tzinfo=None)
            if last_run_local >= prev_naive:
                return False

        return True
    except Exception as exc:
        log.warning("Cron check failed for screening %s: %s", screening.get("id"), exc)
        return False


def run_tick(max_concurrent: int | None = None) -> dict:
    """
    One tick of the scheduler. Should be called every minute.

    Returns a stats dict: {launched, skipped_due, already_running, running_before}.
    """
    from shared.db import get_supabase_client

    client = get_supabase_client()
    schema = "swingtrader"
    limit = max_concurrent if max_concurrent is not None else MAX_CONCURRENT
    now_utc = datetime.now(timezone.utc)

    # ── 1. Expire stuck 'running' jobs ───────────────────────────────────────
    stuck_cutoff = (now_utc - timedelta(minutes=STUCK_TIMEOUT_MINUTES)).isoformat()
    try:
        client.schema(schema).table("user_screening_results").update(
            {"status": "error", "summary": "Job timed out (stuck detection)"}
        ).eq("status", "running").lt("started_at", stuck_cutoff).execute()
    except Exception as exc:
        log.warning("Stuck-job cleanup failed: %s", exc)

    # ── 2. Count currently running jobs ──────────────────────────────────────
    try:
        running_res = (
            client.schema(schema)
            .table("user_screening_results")
            .select("screening_id", count="exact")
            .eq("status", "running")
            .execute()
        )
        running_count = running_res.count or 0
        running_ids: set[str] = {r["screening_id"] for r in (running_res.data or [])}
    except Exception as exc:
        log.error("Failed to query running jobs: %s", exc)
        return {"error": str(exc)}

    available = limit - running_count
    if available <= 0:
        log.info("Concurrency limit reached (%d/%d). Skipping tick.", running_count, limit)
        return {"launched": 0, "skipped_due": 0, "already_running": running_count, "running_before": running_count}

    # ── 3. Fetch active screenings ────────────────────────────────────────────
    try:
        res = (
            client.schema(schema)
            .table("user_scheduled_screenings")
            .select("*")
            .eq("is_active", True)
            .execute()
        )
        screenings = res.data or []
    except Exception as exc:
        log.error("Failed to fetch screenings: %s", exc)
        return {"error": str(exc)}

    # ── 4. Determine due screenings ───────────────────────────────────────────
    due: list[dict] = []
    for s in screenings:
        if s["id"] in running_ids:
            continue
        # Manual trigger takes priority over schedule check.
        if s.get("run_requested_at"):
            due.append(s)
        elif _is_due(s, now_utc):
            due.append(s)

    to_run = due[:available]
    skipped_due = len(due) - len(to_run)
    launched = 0

    # ── 5. Pre-insert 'running' rows and launch subprocesses ─────────────────
    for screening in to_run:
        is_test = bool(screening.get("run_requested_at"))
        try:
            insert_res = (
                client.schema(schema)
                .table("user_screening_results")
                .insert({
                    "screening_id": screening["id"],
                    "user_id": screening["user_id"],
                    "run_at": now_utc.isoformat(),
                    "started_at": now_utc.isoformat(),
                    "status": "running",
                    "triggered": False,
                    "delivered": False,
                    "is_test": is_test,
                })
                .execute()
            )
            result_id = insert_res.data[0]["id"]
        except Exception as exc:
            log.error("Failed to pre-insert result row for %s: %s", screening["id"], exc)
            continue

        cmd = [
            _VENV_PYTHON, "-m", "services.agent.cli",
            "run", screening["id"],
            "--result-id", result_id,
        ]
        if is_test:
            cmd.append("--is-test")

        subprocess.Popen(cmd, cwd=str(_ANALYTICS))
        log.info("Launched screening %s (result %s, test=%s)", screening["id"], result_id, is_test)
        launched += 1

    log.info(
        "Tick complete: launched=%d skipped=%d running_before=%d",
        launched, skipped_due, running_count,
    )
    return {
        "launched": launched,
        "skipped_due": skipped_due,
        "already_running": running_count,
        "running_before": running_count,
    }
