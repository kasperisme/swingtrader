"""Register the arena's nightly job in OpenClaw.

One cron, not three. `run-day` sequences fill -> mark -> decide itself, and the
order matters (marking before filling values a book that does not exist yet), so
splitting them into separate schedules would only create a way for them to drift
out of step.

Timing: 21:15 UTC is 17:15 ET, a bit over an hour after the close. That is late
enough for FMP's daily bars to have settled and for the day's news scoring to
have run, and early enough that a full roster pass (10-20 minutes, agents run
sequentially) finishes well before the next open.

Mirrors ``services/market_screenings/sync_crons.py``.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

_JOB_NAME = "arena-run-day"
_SCHEDULE = "15 21 * * 1-5"  # weekdays, 21:15 UTC = 17:15 ET

_ANALYTICS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_VENV_PYTHON = os.path.join(_ANALYTICS, ".venv", "bin", "python")
if not os.path.exists(_VENV_PYTHON):
    _VENV_PYTHON = "python3"


def _openclaw(*args: str) -> dict:
    r = subprocess.run(
        ["openclaw", *args, "--json"], capture_output=True, text=True, timeout=30
    )
    if r.returncode != 0:
        log.warning("openclaw %s failed: %s", args[0], r.stderr[:200])
        return {}
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return {}


def _get_job() -> dict | None:
    data = _openclaw("cron", "list")
    jobs = data if isinstance(data, list) else data.get("jobs", [])
    return next((j for j in jobs if j.get("name") == _JOB_NAME), None)


def setup_arena_cron() -> dict:
    """Ensure exactly one ``arena-run-day`` cron exists."""
    existing = _get_job()
    if existing:
        log.info("Arena cron already registered (id=%s)", existing.get("id"))
        return {"status": "already_exists", "job": existing}

    command = f"cd {_ANALYTICS} && {_VENV_PYTHON} -m services.arena.cli run-day"
    r = subprocess.run(
        [
            "openclaw", "cron", "add",
            "--name", _JOB_NAME,
            "--schedule", _SCHEDULE,
            "--command", command,
            "--json",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if r.returncode != 0:
        log.error("Failed to register arena cron: %s", r.stderr[:400])
        return {"status": "error", "error": r.stderr[:400]}

    log.info("Registered %s (%s UTC): %s", _JOB_NAME, _SCHEDULE, command)
    return {"status": "created", "schedule": _SCHEDULE, "command": command}


if __name__ == "__main__":
    print(json.dumps(setup_arena_cron(), indent=2))
