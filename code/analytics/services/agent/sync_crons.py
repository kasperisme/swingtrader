"""
sync_crons.py — Register OpenClaw minute crons for screening schedulers.

Registers ``screening-tick`` (LLM user screenings → ``services.agent.cli tick``)
and ensures ``public-screening-tick`` exists (→ ``services.public_screenings.cli tick``).

Run once (or after infra changes):
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
    """Ensure ``screening-tick`` and ``public-screening-tick`` OpenClaw crons exist."""
    removed = _remove_old_per_screening_crons()
    existing = _get_tick_job()
    tick_command = f"{_VENV_PYTHON} -m services.agent.cli tick"

    if existing:
        log.info("Tick cron already registered (id=%s)", existing.get("id"))
        agent_result: dict = {"status": "already_exists", "job": existing}
    else:
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
            agent_result = {"status": "error", "detail": r.stderr[:300]}
        else:
            try:
                result = json.loads(r.stdout)
            except json.JSONDecodeError:
                result = {}
            log.info(
                "Registered tick cron (id=%s), removed %d old crons",
                result.get("id"),
                removed,
            )
            agent_result = {"status": "created", "job": result}

    public_tick: dict = {}
    try:
        from services.public_screenings.sync_crons import setup_public_screening_tick_cron

        public_tick = setup_public_screening_tick_cron()
    except Exception as exc:
        log.warning("Public screening tick registration failed: %s", exc)
        public_tick = {"status": "error", "detail": str(exc)}

    out = {
        **agent_result,
        "old_crons_removed": removed,
        "public_screening_tick": public_tick,
    }
    return out


if __name__ == "__main__":
    import pprint
    pprint.pprint(setup_tick_cron())
