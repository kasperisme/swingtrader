"""
Scheduler tick for the public-screening bulk-analytics worker.

Mirrors `services.bulk_analysis.scheduler` in shape, scoped to
`public_screening_results.bulk_analysis_status` instead of
`user_bulk_analysis_jobs.status`.

  1. Stuck-pass cleanup: rows with bulk_analysis_status='running' older than
     STUCK_TIMEOUT_MINUTES are flipped to 'error'.
  2. Dispatch: pick the oldest 'queued' rows up to MAX_CONCURRENT - running,
     flip them to 'running', launch a subprocess per row.

Per-ticker concurrency lives inside the worker (asyncio.Semaphore), so this
scheduler caps pass concurrency low.
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
MAX_CONCURRENT = int(
    os.environ.get("PUBLIC_BULK_ANALYSIS_MAX_CONCURRENT", "1")
)
STUCK_TIMEOUT_MINUTES = int(
    os.environ.get("PUBLIC_BULK_ANALYSIS_STUCK_TIMEOUT_MINUTES", "60")
)


def run_tick(max_concurrent: int | None = None) -> dict:
    from shared.db import get_supabase_client

    client = get_supabase_client()
    limit = max_concurrent if max_concurrent is not None else MAX_CONCURRENT
    now = datetime.now(timezone.utc)

    stuck_cutoff = (now - timedelta(minutes=STUCK_TIMEOUT_MINUTES)).isoformat()
    try:
        client.schema(SCHEMA).table("public_screening_results").update(
            {
                "bulk_analysis_status": "error",
                "bulk_analysis_error": "Pass timed out (stuck detection)",
                "bulk_analysis_finished_at": now.isoformat(),
            }
        ).eq("bulk_analysis_status", "running").lt(
            "bulk_analysis_started_at", stuck_cutoff
        ).execute()
    except Exception as exc:
        log.warning("Stuck-pass cleanup failed: %s", exc)

    running_res = (
        client.schema(SCHEMA)
        .table("public_screening_results")
        .select("id", count="exact")
        .eq("bulk_analysis_status", "running")
        .execute()
    )
    running_count = running_res.count or 0
    available = limit - running_count
    if available <= 0:
        return {
            "launched": 0,
            "running_before": running_count,
            "available_slots": 0,
        }

    queued_res = (
        client.schema(SCHEMA)
        .table("public_screening_results")
        .select("id, public_screening_id")
        .eq("bulk_analysis_status", "queued")
        .order("run_at", desc=False)
        .limit(available)
        .execute()
    )
    queued = queued_res.data or []
    launched = 0

    for row in queued:
        result_id = row["id"]
        # Flip to running here so a slow worker startup doesn't double-dispatch.
        client.schema(SCHEMA).table("public_screening_results").update(
            {
                "bulk_analysis_status": "running",
                "bulk_analysis_started_at": now.isoformat(),
            }
        ).eq("id", result_id).execute()

        cmd = [
            _VENV_PYTHON,
            "-m",
            "services.public_screening_bulk_analytics.cli",
            "run",
            result_id,
        ]
        subprocess.Popen(cmd, cwd=str(_ANALYTICS))
        log.info("Dispatched public bulk-analysis pass %s", result_id)
        launched += 1

    return {
        "launched": launched,
        "running_before": running_count,
        "available_slots": available,
    }
