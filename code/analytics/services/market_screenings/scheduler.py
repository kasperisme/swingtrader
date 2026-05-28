"""
Scheduler tick for market screenings only.

Queue + dispatch due ``market_screening_results`` rows. Independent from
``services.agent.scheduler`` but uses the same cron helpers in
``shared.screening_schedule``.
"""

from __future__ import annotations

import logging
import os
import pathlib
import subprocess
from datetime import datetime, timedelta, timezone

from shared.screening_schedule import next_run_after, parse_schedule, to_utc

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

_ANALYTICS = pathlib.Path(__file__).resolve().parent.parent.parent
_VENV_PYTHON = str(_ANALYTICS / ".venv" / "bin" / "python")
if not os.path.exists(_VENV_PYTHON):
    _VENV_PYTHON = "python3"

MAX_CONCURRENT = int(
    os.environ.get(
        "MARKET_SCREENING_MAX_CONCURRENT",
        os.environ.get("SCREENING_MAX_CONCURRENT", "1"),
    )
)
STUCK_TIMEOUT_MINUTES = int(os.environ.get("SCREENING_STUCK_TIMEOUT_MINUTES", "20"))
_SCHEMA = "swingtrader"


def _queue_due_market_screenings(
    client, screenings: list[dict], now_utc: datetime, schema: str
) -> int:
    """Insert due rows for published market screenings; advance next_run_at."""
    queued = 0

    for s in screenings:
        sid = s["id"]
        schedule, tz = parse_schedule(s)
        next_run_at = to_utc(s.get("next_run_at"))

        if next_run_at is None:
            last = to_utc(s.get("last_run_at") or s.get("created_at"))
            start = last or now_utc
            first_next = next_run_after(schedule, tz, start)
            client.schema(schema).table("market_screenings").update(
                {"next_run_at": first_next.isoformat()}
            ).eq("id", sid).execute()
            log.info(
                "Initialized next_run_at for market screening %s → %s",
                sid,
                first_next.isoformat(),
            )
            continue

        if next_run_at > now_utc:
            continue

        try:
            client.schema(schema).table("market_screening_results").insert(
                {
                    "market_screening_id": sid,
                    "run_at": next_run_at.isoformat(),
                    "status": "due",
                    "triggered": False,
                    "is_test": False,
                }
            ).execute()
            queued += 1
            log.info(
                "Queued market screening %s (scheduled %s)",
                sid,
                next_run_at.isoformat(),
            )
        except Exception as exc:
            log.warning("Failed to queue market screening %s: %s", sid, exc)

        new_next = next_run_after(schedule, tz, next_run_at)
        client.schema(schema).table("market_screenings").update(
            {"next_run_at": new_next.isoformat()}
        ).eq("id", sid).execute()

    for s in screenings:
        if not s.get("run_requested_at"):
            continue
        sid = s["id"]
        existing = (
            client.schema(schema)
            .table("market_screening_results")
            .select("id", count="exact")
            .eq("market_screening_id", sid)
            .in_("status", ["due", "running"])
            .execute()
        )
        if (existing.count or 0) > 0:
            continue
        try:
            client.schema(schema).table("market_screening_results").insert(
                {
                    "market_screening_id": sid,
                    "run_at": now_utc.isoformat(),
                    "status": "due",
                    "triggered": False,
                    "is_test": True,
                }
            ).execute()
            queued += 1
            log.info("Queued manual trigger for market screening %s", sid)
        except Exception as exc:
            log.warning("Failed to queue manual trigger for public %s: %s", sid, exc)

    return queued


def _dispatch_due_public(client, available: int, now_utc: datetime, schema: str) -> int:
    if available <= 0:
        return 0

    due_res = (
        client.schema(schema)
        .table("market_screening_results")
        .select("id, market_screening_id, is_test")
        .eq("status", "due")
        .order("run_at", desc=False)
        .limit(available)
        .execute()
    )
    due_rows = due_res.data or []
    launched = 0

    for row in due_rows:
        result_id = row["id"]
        screening_id = row["market_screening_id"]

        client.schema(schema).table("market_screening_results").update(
            {
                "status": "running",
                "started_at": now_utc.isoformat(),
            }
        ).eq("id", result_id).execute()

        cmd = [
            _VENV_PYTHON,
            "-m",
            "services.market_screenings.cli",
            "run",
            screening_id,
            "--result-id",
            result_id,
        ]
        if row.get("is_test"):
            cmd.append("--is-test")

        subprocess.Popen(cmd, cwd=str(_ANALYTICS))
        log.info("Dispatched market screening %s (result %s)", screening_id, result_id)
        launched += 1

    return launched


def run_tick(max_concurrent: int | None = None) -> dict:
    """One tick: queue due public definitions, dispatch due result rows."""
    from shared.db import get_supabase_client

    client = get_supabase_client()
    limit = max_concurrent if max_concurrent is not None else MAX_CONCURRENT
    now_utc = datetime.now(timezone.utc)

    stuck_cutoff = (now_utc - timedelta(minutes=STUCK_TIMEOUT_MINUTES)).isoformat()
    try:
        client.schema(_SCHEMA).table("market_screening_results").update(
            {"status": "error", "summary": "Job timed out (stuck detection)"}
        ).eq("status", "running").lt("started_at", stuck_cutoff).execute()
    except Exception as exc:
        log.warning("Stuck-job cleanup failed for market_screening_results: %s", exc)

    running_count = (
        client.schema(_SCHEMA)
        .table("market_screening_results")
        .select("id", count="exact")
        .eq("status", "running")
        .execute()
    ).count or 0
    available = limit - running_count

    market_screenings = (
        client.schema(_SCHEMA)
        .table("market_screenings")
        .select("*")
        .eq("is_active", True)
        .eq("is_published", True)
        .execute()
    ).data or []

    queued = _queue_due_market_screenings(
        client, market_screenings, now_utc, _SCHEMA
    )
    launched = _dispatch_due_public(client, available, now_utc, _SCHEMA)

    log.info(
        "Market screening tick: queued=%d launched=%d running_before=%d",
        queued,
        launched,
        running_count,
    )
    return {
        "queued": queued,
        "launched": launched,
        "running_before": running_count,
        "available_slots": available,
    }
