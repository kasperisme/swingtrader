"""
scheduler.py — Single-cron tick scheduler for the bulk-analysis worker.

Mirrors services.agent.scheduler in shape:
  1. Stuck-job cleanup: rows with status='running' older than the timeout
     are flipped to 'error'.
  2. Dispatch:          Pick the oldest 'queued' rows up to MAX_CONCURRENT
                        - running_count, flip them to 'running', launch a
                        subprocess for each.

Per-ticker concurrency lives inside the worker (asyncio.Semaphore), so this
scheduler intentionally caps job concurrency low.
"""

from __future__ import annotations

import logging
import os
import pathlib
import subprocess
from datetime import datetime, timedelta, timezone

log = logging.getLogger(__name__)

_ANALYTICS = pathlib.Path(__file__).resolve().parent.parent.parent
_VENV_PYTHON = str(_ANALYTICS / ".venv" / "bin" / "python")
if not os.path.exists(_VENV_PYTHON):
    _VENV_PYTHON = "python3"

SCHEMA = "swingtrader"
MAX_CONCURRENT = int(os.environ.get("BULK_ANALYSIS_MAX_CONCURRENT", "1"))
STUCK_TIMEOUT_MINUTES = int(os.environ.get("BULK_ANALYSIS_STUCK_TIMEOUT_MINUTES", "60"))


def run_tick(max_concurrent: int | None = None) -> dict:
    from shared.db import get_supabase_client

    client = get_supabase_client()
    limit = max_concurrent if max_concurrent is not None else MAX_CONCURRENT
    now = datetime.now(timezone.utc)

    stuck_cutoff = (now - timedelta(minutes=STUCK_TIMEOUT_MINUTES)).isoformat()
    try:
        client.schema(SCHEMA).table("user_bulk_analysis_jobs").update(
            {
                "status": "error",
                "error_message": "Job timed out (stuck detection)",
                "finished_at": now.isoformat(),
            }
        ).eq("status", "running").lt("started_at", stuck_cutoff).execute()
    except Exception as exc:
        log.warning("Stuck-job cleanup failed: %s", exc)

    running_res = (
        client.schema(SCHEMA)
        .table("user_bulk_analysis_jobs")
        .select("id", count="exact")
        .eq("status", "running")
        .execute()
    )
    running_count = running_res.count or 0
    available = limit - running_count
    if available <= 0:
        return {"launched": 0, "running_before": running_count, "available_slots": 0}

    queued_res = (
        client.schema(SCHEMA)
        .table("user_bulk_analysis_jobs")
        .select("id, user_id, scan_run_id")
        .eq("status", "queued")
        .order("created_at", desc=False)
        .limit(available)
        .execute()
    )
    queued = queued_res.data or []
    launched = 0

    for row in queued:
        job_id = row["id"]
        # Flip to running here so a slow worker startup doesn't double-dispatch.
        client.schema(SCHEMA).table("user_bulk_analysis_jobs").update(
            {"status": "running", "started_at": now.isoformat()}
        ).eq("id", job_id).execute()

        cmd = [_VENV_PYTHON, "-m", "services.bulk_analysis.cli", "run", job_id]
        subprocess.Popen(cmd, cwd=str(_ANALYTICS))
        log.info("Dispatched bulk-analysis job %s", job_id)
        launched += 1

    return {
        "launched": launched,
        "running_before": running_count,
        "available_slots": available,
    }
