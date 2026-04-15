"""
watchdog.py — Mac Mini health watchdog
=======================================

Queries swingtrader.job_health and fires WhatsApp alerts via OpenClaw
for any job that is overdue or stuck in 'running'.

Run every 15 minutes via cron:
    */15 * * * * cd /path/to/swingtrader/code/analytics && \
        .venv/bin/python -m scripts.watchdog >> logs/watchdog.log 2>&1

Environment variables:
    OPENCLAW_CMD          — path to OpenClaw CLI binary
    OPENCLAW_WHATSAPP_TO  — recipient number (if required by the CLI)
    SUPABASE_URL, SUPABASE_KEY, SUPABASE_SCHEMA  — standard DB vars
"""

from __future__ import annotations

import logging
import pathlib
import sys
from datetime import datetime, timezone

from dotenv import load_dotenv

_ANALYTICS = pathlib.Path(__file__).resolve().parent.parent
if str(_ANALYTICS) not in sys.path:
    sys.path.insert(0, str(_ANALYTICS))

load_dotenv(_ANALYTICS / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# How long a job can be stuck in 'running' before we alert (minutes)
MAX_RUNNING_MINUTES = 60


def check_health() -> list[str]:
    """Return a list of alert strings for any unhealthy jobs."""
    from src.db import get_supabase_client, get_schema
    from src.health import send_whatsapp_alert

    client = get_supabase_client()
    schema = get_schema()
    now = datetime.now(timezone.utc)

    res = (
        client.schema(schema)
        .table("job_health")
        .select(
            "job_name,last_started_at,last_finished_at,last_status,"
            "consecutive_fails,expected_interval_h"
        )
        .execute()
    )

    alerts: list[str] = []
    for job in res.data or []:
        name = job["job_name"]
        status = job.get("last_status")
        interval_h = job.get("expected_interval_h")
        finished_at = job.get("last_finished_at")
        started_at = job.get("last_started_at")
        fails = job.get("consecutive_fails", 0) or 0

        # Job stuck in 'running' too long (crash before self-reporting)
        if status == "running" and started_at:
            age_min = (now - datetime.fromisoformat(started_at)).total_seconds() / 60
            if age_min > MAX_RUNNING_MINUTES:
                alerts.append(
                    f"[STUCK] {name} has been 'running' for {age_min:.0f}min — "
                    f"likely crashed without reporting."
                )

        # Last run failed
        elif status == "failed":
            alerts.append(
                f"[FAILED] {name} — {fails} consecutive failure(s)."
            )

        # Job is overdue (hasn't run within 1.5× expected interval)
        elif interval_h and finished_at:
            age_h = (now - datetime.fromisoformat(finished_at)).total_seconds() / 3600
            if age_h > interval_h * 1.5:
                alerts.append(
                    f"[STALE] {name} — last success {age_h:.1f}h ago "
                    f"(expected every {interval_h}h)."
                )

        # Job has never completed
        elif interval_h and not finished_at:
            alerts.append(f"[NEVER RUN] {name} — no successful run recorded.")

    return alerts


def main() -> None:
    from src.health import send_whatsapp_alert

    logger.info("Watchdog running...")
    try:
        alerts = check_health()
    except Exception as exc:
        logger.error("Watchdog failed to query health: %s", exc)
        send_whatsapp_alert(f"[SwingTrader Watchdog] ERROR — could not query job_health: {exc}")
        return

    if not alerts:
        logger.info("All jobs healthy.")
        return

    logger.warning("%d alert(s):", len(alerts))
    for a in alerts:
        logger.warning("  %s", a)

    msg = "[SwingTrader Watchdog]\n" + "\n".join(f"• {a}" for a in alerts)
    send_whatsapp_alert(msg)


if __name__ == "__main__":
    main()
