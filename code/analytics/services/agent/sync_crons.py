"""
sync_crons.py — Register the single scheduler tick cron in OpenClaw.

The old model (one OpenClaw cron per screening) caused rate-limit issues.
The new model is a single cron that fires every minute and calls `cli tick`,
which evaluates due screenings internally using croniter.

Run once to set up:
    python -m services.agent.cli setup-cron
"""

from __future__ import annotations

import json
import logging
import os
import subprocess

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

_TICK_JOB_NAME = "screening-tick"
_ANALYTICS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_VENV_PYTHON = os.path.join(_ANALYTICS, ".venv", "bin", "python")
if not os.path.exists(_VENV_PYTHON):
    _VENV_PYTHON = "python3"


def _openclaw(*args: str) -> dict:
    r = subprocess.run(
        ["openclaw", *args, "--json"],
        capture_output=True, text=True, timeout=30,
    )
    if r.returncode != 0:
        log.warning("openclaw %s failed: %s", args[0], r.stderr[:200])
        return {}
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return {}


def _get_tick_job() -> dict | None:
    data = _openclaw("cron", "list")
    jobs = data if isinstance(data, list) else data.get("jobs", [])
    for j in jobs:
        if j.get("name") == _TICK_JOB_NAME:
            return j
    return None


def _remove_old_per_screening_crons() -> int:
    """Remove any leftover per-screening cron jobs (screening-<uuid> pattern)."""
    data = _openclaw("cron", "list")
    jobs = data if isinstance(data, list) else data.get("jobs", [])
    removed = 0
    for j in jobs:
        name = j.get("name", "")
        # Old jobs were named "screening-<uuid>"; the new tick job is "screening-tick".
        if name.startswith("screening-") and name != _TICK_JOB_NAME:
            job_id = j.get("id")
            if job_id:
                subprocess.run(
                    ["openclaw", "cron", "rm", job_id],
                    capture_output=True, text=True, timeout=15,
                )
                log.info("Removed old per-screening cron: %s (%s)", name, job_id)
                removed += 1
    return removed


def setup_tick_cron() -> dict:
    """Ensure exactly one 'screening-tick' cron exists, firing every minute."""
    existing = _get_tick_job()
    removed = _remove_old_per_screening_crons()

    tick_command = f"{_VENV_PYTHON} -m services.agent.cli tick"

    if existing:
        log.info("Tick cron already registered (id=%s)", existing.get("id"))
        return {"status": "already_exists", "job": existing, "old_crons_removed": removed}

    r = subprocess.run(
        [
            "openclaw", "cron", "add",
            "--name", _TICK_JOB_NAME,
            "--cron", "* * * * *",
            "--tz", "UTC",
            "--session", "isolated",
            "--no-deliver",
            "--timeout", str(int(os.environ.get("SCREENING_TIMEOUT_MS", 600_000))),
            "--message", tick_command,
        ],
        capture_output=True, text=True, timeout=30,
    )
    if r.returncode != 0:
        log.error("Failed to register tick cron: %s", r.stderr[:300])
        return {"status": "error", "detail": r.stderr[:300], "old_crons_removed": removed}

    try:
        result = json.loads(r.stdout)
    except json.JSONDecodeError:
        result = {}

    log.info("Registered tick cron (id=%s), removed %d old crons", result.get("id"), removed)
    return {"status": "created", "job": result, "old_crons_removed": removed}


if __name__ == "__main__":
    import pprint
    pprint.pprint(setup_tick_cron())
