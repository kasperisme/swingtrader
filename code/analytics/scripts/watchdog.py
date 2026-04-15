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
# watchdog.log is intentionally excluded — it would always contain its own ERROR lines
LOG_FILES: dict[str, str] = {
    "news_ingest":      "swingtrader-news.log",
    "embeddings":       "embeddings.log",
    "blog_post":        "generate_blog_post.log",
    "daily_narrative":  "narrative.log",
    "telegram_updates": "telegram_updates.log",
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


def check_health() -> tuple[list[str], list[str]]:
    """
    Query Supabase job_health for stuck/failed/stale jobs.
    Returns (alerts, ok_lines) where ok_lines are per-job status summaries.
    """
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
        .order("job_name")
        .execute()
    )

    alerts: list[str] = []
    ok_lines: list[str] = []

    for job in res.data or []:
        name = job["job_name"]
        status = job.get("last_status")
        finished_at = job.get("last_finished_at")
        started_at = job.get("last_started_at")
        fails = job.get("consecutive_fails", 0) or 0

        # expected_interval may be DOUBLE PRECISION (float) or INTERVAL (string "HH:MM:SS")
        raw_interval = job.get("expected_interval")
        interval_h: float | None = None
        if raw_interval is not None:
            try:
                interval_h = float(raw_interval)
            except (TypeError, ValueError):
                # Postgres INTERVAL string e.g. "0:15:00" or "1 day 02:00:00"
                try:
                    s = str(raw_interval)
                    days = 0
                    if "day" in s:
                        parts = s.split("day")
                        days = int(parts[0].strip())
                        s = parts[1].strip().lstrip("s").strip()
                    h, m, sec = (float(x) for x in s.split(":"))
                    interval_h = days * 24 + h + m / 60 + sec / 3600
                except Exception:
                    interval_h = None

        def _age(iso: str) -> str:
            dt = datetime.fromisoformat(iso)
            mins = (now - dt).total_seconds() / 60
            if mins < 90:
                return f"{mins:.0f}min ago"
            return f"{mins / 60:.1f}h ago"

        if status == "running" and started_at:
            age_min = (now - datetime.fromisoformat(started_at)).total_seconds() / 60
            if age_min > MAX_RUNNING_MINUTES:
                alerts.append(
                    f"[STUCK] {name} has been 'running' for {age_min:.0f}min — "
                    f"likely crashed without reporting."
                )
            else:
                ok_lines.append(f"  {name:<35} running  (started {_age(started_at)})")
        elif status == "failed":
            alerts.append(f"[FAILED] {name} — {fails} consecutive failure(s).")
        elif interval_h and finished_at:
            age_h = (now - datetime.fromisoformat(finished_at)).total_seconds() / 3600
            if age_h > interval_h * 1.5:
                alerts.append(
                    f"[STALE] {name} — last success {_age(finished_at)} "
                    f"(expected every {interval_h}h)."
                )
            else:
                ok_lines.append(f"  {name:<35} ok       (last success {_age(finished_at)})")
        elif interval_h and not finished_at:
            alerts.append(f"[NEVER RUN] {name} — no successful run recorded.")
        else:
            ok_lines.append(f"  {name:<35} {status or 'unknown':<8} (last success {_age(finished_at) if finished_at else 'never'})")

    return alerts, ok_lines


def main() -> dict:
    """Run all checks and return a summary dict written to job_health metadata."""
    from src.health import send_whatsapp_alert

    logger.info("━━━ Watchdog started ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    alerts: list[str] = []
    jobs_checked = 0
    logs_clean: list[str] = []
    logs_with_errors: list[str] = []

    # ── 1. Supabase job_health ─────────────────────────────────────────────
    logger.info("Checking Supabase job_health...")
    try:
        health_alerts, ok_lines = check_health()
        jobs_checked = len(ok_lines) + len(health_alerts)
        if ok_lines:
            logger.info("  Jobs screened:")
            for line in ok_lines:
                logger.info(line)
        if health_alerts:
            for a in health_alerts:
                logger.warning("  ALERT: %s", a.splitlines()[0])
        else:
            logger.info("  All tracked jobs healthy ✓")
        alerts += health_alerts
    except Exception as exc:
        logger.error("  job_health query failed: %s", exc)
        alerts.append(f"[WATCHDOG ERROR] Could not query job_health: {exc}")

    # ── 2. Local log files ─────────────────────────────────────────────────
    logger.info("Scanning log files (last %dmin)...", SCAN_WINDOW_MINUTES)
    try:
        log_alerts = check_logs()
        for label, filename in LOG_FILES.items():
            path = _LOGS_DIR / filename
            label_alerts = [a for a in log_alerts if f"[LOG:{label}]" in a]
            if not path.exists():
                logger.info("  %-20s not found (no log yet)", filename)
            elif label_alerts:
                logger.warning("  %-20s ERRORS detected", filename)
                logs_with_errors.append(filename)
            else:
                logger.info("  %-20s clean ✓", filename)
                logs_clean.append(filename)
        alerts += log_alerts
    except Exception as exc:
        logger.error("  Log scan failed: %s", exc)

    # ── Summary ────────────────────────────────────────────────────────────
    summary = {
        "jobs_checked": jobs_checked,
        "alerts_fired": len(alerts),
        "logs_clean": logs_clean,
        "logs_with_errors": logs_with_errors,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }

    if not alerts:
        logger.info("━━━ All clear. No alerts. ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        return summary

    logger.warning("━━━ %d alert(s) — sending WhatsApp ━━━━━━━━━━━━━━━━━━━━━━", len(alerts))
    for a in alerts:
        logger.warning("  → %s", a.splitlines()[0])

    msg = "[SwingTrader Watchdog]\n\n" + "\n\n".join(f"• {a}" for a in alerts)
    send_whatsapp_alert(msg)
    return summary


if __name__ == "__main__":
    try:
        from src.health import JobHeartbeat, update_job_metadata
        with JobHeartbeat("watchdog", expected_interval=15 / 60):  # every 15 min
            summary = main()
        update_job_metadata("watchdog", summary)
    except ImportError:
        main()
