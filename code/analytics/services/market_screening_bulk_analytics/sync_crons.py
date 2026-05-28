"""Register the public-bulk-analysis scheduler tick in OpenClaw (every minute)."""

from __future__ import annotations

import json
import logging
import os
import subprocess

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

_TICK_JOB_NAME = "public-bulk-analysis-tick"
_ANALYTICS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_VENV_PYTHON = os.path.join(_ANALYTICS, ".venv", "bin", "python")
if not os.path.exists(_VENV_PYTHON):
    _VENV_PYTHON = "python3"


def _openclaw(*args: str) -> dict:
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


def _get_tick_job() -> dict | None:
    data = _openclaw("cron", "list")
    jobs = data if isinstance(data, list) else data.get("jobs", [])
    for j in jobs:
        if j.get("name") == _TICK_JOB_NAME:
            return j
    return None


def setup_market_bulk_analysis_tick_cron() -> dict:
    """Ensure exactly one ``public-bulk-analysis-tick`` cron exists."""
    existing = _get_tick_job()
    tick_command = (
        f"{_VENV_PYTHON} -m services.market_screening_bulk_analytics.cli tick"
    )

    if existing:
        log.info(
            "Public bulk-analysis tick cron already registered (id=%s)",
            existing.get("id"),
        )
        return {"status": "already_exists", "job": existing}

    r = subprocess.run(
        [
            "openclaw",
            "cron",
            "add",
            "--name",
            _TICK_JOB_NAME,
            "--cron",
            "* * * * *",
            "--tz",
            "UTC",
            "--session",
            "isolated",
            "--no-deliver",
            "--timeout",
            str(int(os.environ.get("PUBLIC_BULK_ANALYSIS_TIMEOUT_MS", 1_800_000))),
            "--message",
            tick_command,
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if r.returncode != 0:
        log.error(
            "Failed to register public bulk-analysis tick cron: %s", r.stderr[:300]
        )
        return {"status": "error", "detail": r.stderr[:300]}

    try:
        result = json.loads(r.stdout)
    except json.JSONDecodeError:
        result = {}

    log.info(
        "Registered public bulk-analysis tick cron (id=%s)", result.get("id")
    )
    return {"status": "created", "job": result}
