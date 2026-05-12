"""
scheduler.py — Single-cron tick scheduler for screening agent.

Called every minute by one OpenClaw cron job. Two phases per tick:

  1. Queue:    Insert status='due' rows for any screening whose cron just fired.
               Uses next_run_at on user_scheduled_screenings so missed runs
               accumulate in the queue rather than being dropped.

  2. Dispatch: Pick the oldest due rows up to MAX_CONCURRENT - running_count,
               flip them to status='running', launch subprocesses.
"""

from __future__ import annotations

import logging
import os
import pathlib
import subprocess
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter
from dateutil.parser import parse as parse_dt

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

_ANALYTICS = pathlib.Path(__file__).resolve().parent.parent.parent
_VENV_PYTHON = str(_ANALYTICS / ".venv" / "bin" / "python")
if not os.path.exists(_VENV_PYTHON):
    _VENV_PYTHON = "python3"

MAX_CONCURRENT = int(os.environ.get("SCREENING_MAX_CONCURRENT", "1"))
STUCK_TIMEOUT_MINUTES = int(os.environ.get("SCREENING_STUCK_TIMEOUT_MINUTES", "20"))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_schedule(screening: dict) -> tuple[str, ZoneInfo]:
    schedule = (screening.get("schedule") or "0 7 * * 1-5").strip()
    if len(schedule.split()) != 5:
        schedule = "0 7 * * 1-5"
    tz_name = screening.get("timezone") or "America/New_York"
    try:
        tz = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        tz = ZoneInfo("America/New_York")
    return schedule, tz


def _next_run_after(schedule: str, tz: ZoneInfo, after_utc: datetime) -> datetime:
    """Return the next cron fire time after after_utc, as a UTC-aware datetime."""
    after_local_naive = after_utc.astimezone(tz).replace(tzinfo=None)
    next_local_naive = croniter(schedule, after_local_naive).get_next(datetime)
    return next_local_naive.replace(tzinfo=tz).astimezone(timezone.utc)


def _to_utc(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = parse_dt(value)
    return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)


# ── Phase 1: Queue ────────────────────────────────────────────────────────────

def _queue_due_screenings(client, screenings: list[dict], now_utc: datetime, schema: str) -> int:
    """
    For each active screening whose next_run_at has passed, insert a
    status='due' result row and advance next_run_at to the following
    scheduled time.

    Screenings with next_run_at=NULL get their first next_run_at computed
    and saved; they do not run until the following tick.
    """
    queued = 0

    for s in screenings:
        sid = s["id"]
        schedule, tz = _parse_schedule(s)
        next_run_at = _to_utc(s.get("next_run_at"))

        # First-time setup: compute and save next_run_at, don't queue yet.
        if next_run_at is None:
            last = _to_utc(s.get("last_run_at") or s.get("created_at"))
            start = last or now_utc
            first_next = _next_run_after(schedule, tz, start)
            client.schema(schema).table("user_scheduled_screenings").update(
                {"next_run_at": first_next.isoformat()}
            ).eq("id", sid).execute()
            log.info("Initialized next_run_at for %s → %s", sid, first_next.isoformat())
            continue

        if next_run_at > now_utc:
            continue  # Not yet due.

        # Insert due row.
        try:
            client.schema(schema).table("user_screening_results").insert({
                "screening_id": sid,
                "user_id": s["user_id"],
                "run_at": next_run_at.isoformat(),
                "status": "due",
                "triggered": False,
                "delivered": False,
                "is_test": False,
            }).execute()
            queued += 1
            log.info("Queued screening %s (scheduled %s)", sid, next_run_at.isoformat())
        except Exception as exc:
            log.warning("Failed to queue %s: %s", sid, exc)

        # Advance next_run_at regardless of insert outcome to prevent
        # re-queueing the same scheduled time on the next tick.
        new_next = _next_run_after(schedule, tz, next_run_at)
        client.schema(schema).table("user_scheduled_screenings").update(
            {"next_run_at": new_next.isoformat()}
        ).eq("id", sid).execute()

    # Handle manual triggers (run_requested_at set by user).
    for s in screenings:
        if not s.get("run_requested_at"):
            continue
        sid = s["id"]
        # Only queue if not already due/running for this screening.
        existing = (
            client.schema(schema)
            .table("user_screening_results")
            .select("id", count="exact")
            .eq("screening_id", sid)
            .in_("status", ["due", "running"])
            .execute()
        )
        if (existing.count or 0) > 0:
            continue
        try:
            client.schema(schema).table("user_screening_results").insert({
                "screening_id": sid,
                "user_id": s["user_id"],
                "run_at": now_utc.isoformat(),
                "status": "due",
                "triggered": False,
                "delivered": False,
                "is_test": True,
            }).execute()
            queued += 1
            log.info("Queued manual trigger for screening %s", sid)
        except Exception as exc:
            log.warning("Failed to queue manual trigger %s: %s", sid, exc)

    return queued


# ── Phase 1b: Queue public screenings ────────────────────────────────────────

def _queue_due_public_screenings(client, screenings: list[dict], now_utc: datetime, schema: str) -> int:
    """Mirror of _queue_due_screenings for the shared `public_screenings` table.

    Differences from the user variant:
      - Writes to `public_screening_results` (no user_id).
      - Advances `next_run_at` on `public_screenings`.
      - Only processes rows where `is_published = TRUE` (caller filters).
    """
    queued = 0

    for s in screenings:
        sid = s["id"]
        schedule, tz = _parse_schedule(s)
        next_run_at = _to_utc(s.get("next_run_at"))

        if next_run_at is None:
            last = _to_utc(s.get("last_run_at") or s.get("created_at"))
            start = last or now_utc
            first_next = _next_run_after(schedule, tz, start)
            client.schema(schema).table("public_screenings").update(
                {"next_run_at": first_next.isoformat()}
            ).eq("id", sid).execute()
            log.info("Initialized next_run_at for public screening %s → %s", sid, first_next.isoformat())
            continue

        if next_run_at > now_utc:
            continue

        try:
            client.schema(schema).table("public_screening_results").insert({
                "public_screening_id": sid,
                "run_at": next_run_at.isoformat(),
                "status": "due",
                "triggered": False,
                "is_test": False,
            }).execute()
            queued += 1
            log.info("Queued public screening %s (scheduled %s)", sid, next_run_at.isoformat())
        except Exception as exc:
            log.warning("Failed to queue public screening %s: %s", sid, exc)

        new_next = _next_run_after(schedule, tz, next_run_at)
        client.schema(schema).table("public_screenings").update(
            {"next_run_at": new_next.isoformat()}
        ).eq("id", sid).execute()

    # Manual triggers (admin clicked "test run").
    for s in screenings:
        if not s.get("run_requested_at"):
            continue
        sid = s["id"]
        existing = (
            client.schema(schema)
            .table("public_screening_results")
            .select("id", count="exact")
            .eq("public_screening_id", sid)
            .in_("status", ["due", "running"])
            .execute()
        )
        if (existing.count or 0) > 0:
            continue
        try:
            client.schema(schema).table("public_screening_results").insert({
                "public_screening_id": sid,
                "run_at": now_utc.isoformat(),
                "status": "due",
                "triggered": False,
                "is_test": True,
            }).execute()
            queued += 1
            log.info("Queued manual trigger for public screening %s", sid)
        except Exception as exc:
            log.warning("Failed to queue manual trigger for public %s: %s", sid, exc)

    return queued


# ── Phase 2: Dispatch ─────────────────────────────────────────────────────────

def _dispatch_due(client, available: int, now_utc: datetime, schema: str) -> int:
    """
    Pick the oldest due rows (up to available slots), flip to running,
    and launch a subprocess for each.
    """
    if available <= 0:
        return 0

    due_res = (
        client.schema(schema)
        .table("user_screening_results")
        .select("id, screening_id, user_id, is_test")
        .eq("status", "due")
        .order("run_at", desc=False)
        .limit(available)
        .execute()
    )
    due_rows = due_res.data or []
    launched = 0

    for row in due_rows:
        result_id = row["id"]
        screening_id = row["screening_id"]

        client.schema(schema).table("user_screening_results").update({
            "status": "running",
            "started_at": now_utc.isoformat(),
        }).eq("id", result_id).execute()

        cmd = [
            _VENV_PYTHON, "-m", "services.agent.cli",
            "run", screening_id,
            "--result-id", result_id,
        ]
        if row.get("is_test"):
            cmd.append("--is-test")

        subprocess.Popen(cmd, cwd=str(_ANALYTICS))
        log.info("Dispatched screening %s (result %s)", screening_id, result_id)
        launched += 1

    return launched


def _dispatch_due_public(client, available: int, now_utc: datetime, schema: str) -> int:
    """Pick oldest due public_screening_results, flip to running, launch run-public subprocesses."""
    if available <= 0:
        return 0

    due_res = (
        client.schema(schema)
        .table("public_screening_results")
        .select("id, public_screening_id, is_test")
        .eq("status", "due")
        .order("run_at", desc=False)
        .limit(available)
        .execute()
    )
    due_rows = due_res.data or []
    launched = 0

    for row in due_rows:
        result_id = row["id"]
        screening_id = row["public_screening_id"]

        client.schema(schema).table("public_screening_results").update({
            "status": "running",
            "started_at": now_utc.isoformat(),
        }).eq("id", result_id).execute()

        cmd = [
            _VENV_PYTHON, "-m", "services.agent.cli",
            "run-public", screening_id,
            "--result-id", result_id,
        ]
        if row.get("is_test"):
            cmd.append("--is-test")

        subprocess.Popen(cmd, cwd=str(_ANALYTICS))
        log.info("Dispatched public screening %s (result %s)", screening_id, result_id)
        launched += 1

    return launched


# ── Main tick ─────────────────────────────────────────────────────────────────

def run_tick(max_concurrent: int | None = None) -> dict:
    """One tick of the scheduler. Called every minute."""
    from shared.db import get_supabase_client

    client = get_supabase_client()
    schema = "swingtrader"
    limit = max_concurrent if max_concurrent is not None else MAX_CONCURRENT
    now_utc = datetime.now(timezone.utc)

    # Expire stuck running jobs (both kinds).
    stuck_cutoff = (now_utc - timedelta(minutes=STUCK_TIMEOUT_MINUTES)).isoformat()
    for table in ("user_screening_results", "public_screening_results"):
        try:
            client.schema(schema).table(table).update(
                {"status": "error", "summary": "Job timed out (stuck detection)"}
            ).eq("status", "running").lt("started_at", stuck_cutoff).execute()
        except Exception as exc:
            log.warning("Stuck-job cleanup failed for %s: %s", table, exc)

    # Count currently running jobs across both queues.
    running_user = (
        client.schema(schema).table("user_screening_results")
        .select("id", count="exact").eq("status", "running").execute()
    ).count or 0
    running_public = (
        client.schema(schema).table("public_screening_results")
        .select("id", count="exact").eq("status", "running").execute()
    ).count or 0
    running_count = running_user + running_public
    available = limit - running_count

    # Fetch active screenings of both kinds.
    user_screenings = (
        client.schema(schema).table("user_scheduled_screenings")
        .select("*").eq("is_active", True).execute()
    ).data or []
    public_screenings = (
        client.schema(schema).table("public_screenings")
        .select("*").eq("is_active", True).eq("is_published", True).execute()
    ).data or []

    # Phase 1: queue due screenings (both kinds).
    queued_user = _queue_due_screenings(client, user_screenings, now_utc, schema)
    queued_public = _queue_due_public_screenings(client, public_screenings, now_utc, schema)

    # Phase 2: dispatch oldest due rows up to available slots.
    # Drain user queue first, then public, with shared concurrency budget.
    launched_user = _dispatch_due(client, available, now_utc, schema)
    available_after = max(0, available - launched_user)
    launched_public = _dispatch_due_public(client, available_after, now_utc, schema)

    log.info(
        "Tick done: queued_user=%d queued_public=%d launched_user=%d launched_public=%d running_before=%d",
        queued_user, queued_public, launched_user, launched_public, running_count,
    )
    return {
        "queued": queued_user + queued_public,
        "queued_user": queued_user,
        "queued_public": queued_public,
        "launched": launched_user + launched_public,
        "launched_user": launched_user,
        "launched_public": launched_public,
        "running_before": running_count,
        "available_slots": available,
    }
