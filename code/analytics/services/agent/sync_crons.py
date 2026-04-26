"""
sync_crons.py — Reconcile Supabase scheduled screenings with OpenClaw cron jobs.

Creates, updates, and removes OpenClaw cron jobs to match the current state of
user_scheduled_screenings. Run this periodically (every minute via a single
OpenClaw cron) to keep cron jobs in sync.

OpenClaw handles the actual scheduling, retries, and execution per screening.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from typing import Any

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

_ANALYTICS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_VENV_PYTHON = os.path.join(_ANALYTICS, ".venv", "bin", "python")
if not os.path.exists(_VENV_PYTHON):
    _VENV_PYTHON = "python3"

_CRON_PREFIX = "screening-"


def _openclaw(*args: str) -> dict[str, Any]:
    r = subprocess.run(
        ["openclaw", *args, "--json"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if r.returncode != 0:
        log.warning("openclaw %s failed: %s", args[0], r.stderr[:200])
        return {}
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return {}


def _get_existing_jobs() -> dict[str, dict]:
    data = _openclaw("cron", "list")
    jobs = data if isinstance(data, list) else data.get("jobs", [])
    out = {}
    for j in jobs:
        name = j.get("name", "")
        if name.startswith(_CRON_PREFIX):
            screening_id = name.removeprefix(_CRON_PREFIX)
            out[screening_id] = j
    return out


def _cron_id_for(screening_id: str) -> str | None:
    name = f"{_CRON_PREFIX}{screening_id}"
    data = _openclaw("cron", "list")
    jobs = data if isinstance(data, list) else data.get("jobs", [])
    for j in jobs:
        if j.get("name") == name:
            return j.get("id")
    return None


def _parse_cron_expr(schedule: str) -> str:
    parts = schedule.strip().split()
    if len(parts) == 5:
        return schedule.strip()
    return "0 7 * * 1-5"


def _add_job(screening: dict) -> str | None:
    screening_id = screening["id"]
    schedule = _parse_cron_expr(screening.get("schedule", "0 7 * * 1-5"))
    tz = screening.get("timezone", "UTC")
    name = screening["name"] if len(screening["name"]) <= 60 else screening["name"][:57] + "..."

    r = subprocess.run(
        [
            "openclaw", "cron", "add",
            "--name", f"{_CRON_PREFIX}{screening_id}",
            "--cron", schedule,
            "--tz", tz,
            "--session", "isolated",
            "--no-deliver",
            "--timeout", "180000",
            "--message",
            f"Run screening {screening_id}: {_VENV_PYTHON} -m services.agent.cli run {screening_id}",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if r.returncode != 0:
        log.error("Failed to add cron for %s: %s", screening_id, r.stderr[:300])
        return None
    try:
        result = json.loads(r.stdout)
        job_id = result.get("id")
        log.info("Added cron job %s for screening %s (%s)", job_id, screening_id, name)
        return job_id
    except json.JSONDecodeError:
        log.info("Added cron job for screening %s (%s)", screening_id, name)
        return None


def _remove_job(screening_id: str) -> None:
    job_id = _cron_id_for(screening_id)
    if not job_id:
        return
    subprocess.run(
        ["openclaw", "cron", "rm", job_id],
        capture_output=True,
        text=True,
        timeout=15,
    )
    log.info("Removed cron job %s for screening %s", job_id, screening_id)


def _sync_job(screening: dict, existing: dict) -> None:
    schedule = _parse_cron_expr(screening.get("schedule", "0 7 * * 1-5"))
    tz = screening.get("timezone", "UTC")
    job_id = existing.get("id")

    sched_data = existing.get("schedule", {})
    current_cron = sched_data.get("cron", "")
    current_tz = sched_data.get("tz", "")

    if current_cron == schedule and current_tz == tz and existing.get("enabled", True):
        return

    r = subprocess.run(
        [
            "openclaw", "cron", "edit", job_id,
            "--cron", schedule,
            "--tz", tz,
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )
    if r.returncode == 0:
        log.info("Updated cron job %s for screening %s", job_id, screening["id"])
    else:
        log.warning("Failed to update cron %s: %s", job_id, r.stderr[:200])


def run_sync() -> dict[str, int]:
    sys.path.insert(0, _ANALYTICS)
    from dotenv import load_dotenv
    load_dotenv(os.path.join(_ANALYTICS, ".env"))

    from shared.db import get_supabase_client

    client = get_supabase_client()
    schema = "swingtrader"

    res = (
        client.schema(schema)
        .table("user_scheduled_screenings")
        .select("id, name, schedule, timezone, is_active, run_requested_at")
        .execute()
    )
    screenings = res.data or []

    existing = _get_existing_jobs()

    db_ids = set()
    added = 0
    updated = 0
    removed = 0
    tested = 0

    for s in screenings:
        sid = s["id"]
        db_ids.add(sid)

        if s.get("is_active"):
            if sid in existing:
                _sync_job(s, existing[sid])
                updated += 1
            else:
                _add_job(s)
                added += 1

            if s.get("run_requested_at"):
                job_id = _cron_id_for(sid)
                if job_id:
                    subprocess.run(
                        ["openclaw", "cron", "run", job_id],
                        capture_output=True,
                        text=True,
                        timeout=15,
                    )
                    log.info("Force-ran screening %s (test request)", sid)
                    tested += 1
        else:
            if sid in existing:
                _remove_job(sid)
                removed += 1

    for sid in set(existing.keys()) - db_ids:
        _remove_job(sid)
        removed += 1

    log.info("Sync complete: %d added, %d updated, %d removed, %d tested", added, updated, removed, tested)
    return {"added": added, "updated": updated, "removed": removed, "tested": tested}


if __name__ == "__main__":
    run_sync()
