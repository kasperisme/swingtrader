"""sync_crons.py — register the OpenClaw minute cron for the briefing tick.

One cron (``briefing-tick``) calls ``services.briefings.cli tick`` every minute;
the tick itself decides what to send (immediate signup sends + the daily 08:30 ET
fan-out). Run once (or after infra changes):

    python -m services.briefings.cli setup-cron
"""

from __future__ import annotations

import json
import logging
import os
import subprocess

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

_TICK_JOB_NAME = "briefing-tick"
_ANALYTICS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_VENV_PYTHON = os.path.join(_ANALYTICS, ".venv", "bin", "python")
if not os.path.exists(_VENV_PYTHON):
    _VENV_PYTHON = "python3"


def _openclaw(*args: str) -> dict | list:
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


def setup_briefing_tick_cron() -> dict:
    """Ensure the ``briefing-tick`` OpenClaw cron exists (every minute, UTC)."""
    existing = _get_tick_job()
    if existing:
        log.info("Briefing tick cron already registered (id=%s)", existing.get("id"))
        return {"status": "already_exists", "job": existing}

    tick_command = f"{_VENV_PYTHON} -m services.briefings.cli tick"
    r = subprocess.run(
        [
            "openclaw", "cron", "add",
            "--name", _TICK_JOB_NAME,
            "--cron", "* * * * *",
            "--tz", "UTC",
            "--session", "isolated",
            "--no-deliver",
            "--timeout", str(int(os.environ.get("BRIEFING_TIMEOUT_MS", 600_000))),
            "--message", tick_command,
        ],
        capture_output=True, text=True, timeout=30,
    )
    if r.returncode != 0:
        log.error("Failed to register briefing tick cron: %s", r.stderr[:300])
        return {"status": "error", "detail": r.stderr[:300]}
    try:
        result = json.loads(r.stdout)
    except json.JSONDecodeError:
        result = {}
    log.info("Registered briefing tick cron (id=%s)", result.get("id"))
    return {"status": "created", "job": result}


if __name__ == "__main__":
    import pprint
    pprint.pprint(setup_briefing_tick_cron())
