"""
watchdog.py — Mac Mini health watchdog
=======================================

Two checks every 15 minutes:
  1. Supabase job_health — flags stuck/failed/stale jobs
  2. Local log files     — scans for ERROR/Traceback lines written in the
                           last SCAN_WINDOW_MINUTES minutes

Run every 15 minutes via cron:
    */15 * * * * cd /path/to/swingtrader/code/analytics && \
        .venv/bin/python -m scripts.watchdog >> logs/watchdog.log 2>&1

Environment variables:
    OPENCLAW_CMD          — path to OpenClaw CLI binary
    OPENCLAW_WHATSAPP_TO  — recipient phone number
    SUPABASE_URL, SUPABASE_KEY, SUPABASE_SCHEMA  — standard DB vars
"""

from __future__ import annotations

import logging
import os
import pathlib
import re
import sys
from datetime import datetime, timedelta, timezone

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

_LOGS_DIR = _ANALYTICS.parent.parent / "logs"  # swingtrader/logs/

# Watchdog cadence — must match the cron interval so log scanning doesn't miss lines
SCAN_WINDOW_MINUTES = 20  # slightly wider than 15-min cron to avoid gaps at boundaries

# How long a job can be stuck in 'running' before alerting
MAX_RUNNING_MINUTES = 60

# Log files to monitor: label → filename inside swingtrader/logs/
LOG_FILES: dict[str, str] = {
    "news_ingest":      "swingtrader-news.log",
    "embeddings":       "embeddings.log",
    "blog_post":        "generate_blog_post.log",
    "daily_narrative":  "narrative.log",
    "telegram_updates": "telegram_updates.log",
    "watchdog":         "watchdog.log",
}

# Lines matching these patterns (case-insensitive) are flagged as errors.
# Traceback is included so we capture the context line after the stack trace header.
_ERROR_RE = re.compile(
    r"\b(error|exception|traceback|critical|fatal)\b",
    re.IGNORECASE,
)

# Lines to suppress — noisy non-actionable patterns
_SUPPRESS_RE = re.compile(
    r"(HTTP/2 [245]\d\d|rate.?limit|retry|retrying|sleeping|backoff"
    r"|supabase\.co.*POST|supabase\.co.*GET)",
    re.IGNORECASE,
)


def _tail_errors(log_path: pathlib.Path, since: datetime) -> list[str]:
    """
    Return lines from log_path that:
      - were written at or after `since` (based on file mtime, then line timestamps)
      - match _ERROR_RE and don't match _SUPPRESS_RE

    Uses a fast approach: if the file's mtime is older than `since`, skip entirely.
    Otherwise read up to the last 500 lines to find matches.
    """
    if not log_path.exists():
        return []

    # Fast skip: file hasn't been touched since the last watchdog run
    mtime = datetime.fromtimestamp(log_path.stat().st_mtime, tz=timezone.utc)
    if mtime < since:
        return []

    try:
        text = log_path.read_text(errors="replace")
    except OSError:
        return []

    lines = text.splitlines()
    # Only look at the tail to keep it fast
    lines = lines[-500:]

    # Timestamp pattern at start of line: "2026-04-15 11:29:56" or "11:29:56"
    ts_re = re.compile(r"^(\d{4}-\d{2}-\d{2} )?\d{2}:\d{2}:\d{2}")

    hits: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        # Try to parse a timestamp from the line so we can filter by time.
        # If no parseable timestamp is found, include the line (conservative).
        line_in_window = True
        m = ts_re.match(stripped)
        if m:
            raw_ts = stripped[:19] if stripped[4] == "-" else None
            if raw_ts:
                try:
                    line_dt = datetime.fromisoformat(raw_ts).replace(tzinfo=timezone.utc)
                    line_in_window = line_dt >= since
                except ValueError:
                    pass

        if not line_in_window:
            continue
        if _ERROR_RE.search(stripped) and not _SUPPRESS_RE.search(stripped):
            hits.append(stripped)

    return hits


def check_logs() -> list[str]:
    """Scan log files for recent errors. Returns alert strings."""
    since = datetime.now(timezone.utc) - timedelta(minutes=SCAN_WINDOW_MINUTES)
    alerts: list[str] = []

    for label, filename in LOG_FILES.items():
        path = _LOGS_DIR / filename
        errors = _tail_errors(path, since)
        if not errors:
            continue
        # Deduplicate identical lines, cap at 3 samples
        seen: set[str] = set()
        samples: list[str] = []
        for e in errors:
            if e not in seen:
                seen.add(e)
                samples.append(e)
            if len(samples) >= 3:
                break
        total = len(errors)
        header = f"[LOG:{label}] {total} error line(s) in last {SCAN_WINDOW_MINUTES}min:"
        alerts.append(header + "\n  " + "\n  ".join(samples))

    return alerts


def check_health() -> list[str]:
    """Query Supabase job_health for stuck/failed/stale jobs."""
    from src.db import get_supabase_client, get_schema

    client = get_supabase_client()
    schema = get_schema()
    now = datetime.now(timezone.utc)

    res = (
        client.schema(schema)
        .table("job_health")
        .select(
            "job_name,last_started_at,last_finished_at,last_status,"
            "consecutive_fails,expected_interval"
        )
        .execute()
    )

    alerts: list[str] = []
    for job in res.data or []:
        name = job["job_name"]
        status = job.get("last_status")
        interval_h = job.get("expected_interval")
        finished_at = job.get("last_finished_at")
        started_at = job.get("last_started_at")
        fails = job.get("consecutive_fails", 0) or 0

        if status == "running" and started_at:
            age_min = (now - datetime.fromisoformat(started_at)).total_seconds() / 60
            if age_min > MAX_RUNNING_MINUTES:
                alerts.append(
                    f"[STUCK] {name} has been 'running' for {age_min:.0f}min — "
                    f"likely crashed without reporting."
                )
        elif status == "failed":
            alerts.append(f"[FAILED] {name} — {fails} consecutive failure(s).")
        elif interval_h and finished_at:
            age_h = (now - datetime.fromisoformat(finished_at)).total_seconds() / 3600
            if age_h > interval_h * 1.5:
                alerts.append(
                    f"[STALE] {name} — last success {age_h:.1f}h ago "
                    f"(expected every {interval_h}h)."
                )
        elif interval_h and not finished_at:
            alerts.append(f"[NEVER RUN] {name} — no successful run recorded.")

    return alerts


def main() -> None:
    from src.health import send_whatsapp_alert

    logger.info("Watchdog running...")

    alerts: list[str] = []

    # ── 1. Supabase job_health ─────────────────────────────────────────────
    try:
        alerts += check_health()
    except Exception as exc:
        logger.error("job_health query failed: %s", exc)
        alerts.append(f"[WATCHDOG ERROR] Could not query job_health: {exc}")

    # ── 2. Local log files ─────────────────────────────────────────────────
    try:
        log_alerts = check_logs()
        if log_alerts:
            logger.warning("%d log file alert(s)", len(log_alerts))
        alerts += log_alerts
    except Exception as exc:
        logger.error("Log scan failed: %s", exc)

    # ── Report ─────────────────────────────────────────────────────────────
    if not alerts:
        logger.info("All healthy.")
        return

    logger.warning("%d total alert(s):", len(alerts))
    for a in alerts:
        logger.warning("  %s", a.splitlines()[0])  # log first line only to keep log clean

    msg = "[SwingTrader Watchdog]\n\n" + "\n\n".join(f"• {a}" for a in alerts)
    send_whatsapp_alert(msg)


if __name__ == "__main__":
    main()
