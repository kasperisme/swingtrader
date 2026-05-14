"""Cron / timezone helpers shared by screening schedulers (agent + public).

Keeps next_run_at logic identical across user_scheduled_screenings and
public_screenings without coupling the two scheduler packages.
"""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter
from dateutil.parser import parse as parse_dt


def parse_schedule(screening: dict) -> tuple[str, ZoneInfo]:
    schedule = (screening.get("schedule") or "0 7 * * 1-5").strip()
    if len(schedule.split()) != 5:
        schedule = "0 7 * * 1-5"
    tz_name = screening.get("timezone") or "America/New_York"
    try:
        tz = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        tz = ZoneInfo("America/New_York")
    return schedule, tz


def next_run_after(schedule: str, tz: ZoneInfo, after_utc: datetime) -> datetime:
    """Next cron fire strictly after ``after_utc``, as UTC-aware datetime."""
    after_local_naive = after_utc.astimezone(tz).replace(tzinfo=None)
    next_local_naive = croniter(schedule, after_local_naive).get_next(datetime)
    return next_local_naive.replace(tzinfo=tz).astimezone(timezone.utc)


def to_utc(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = parse_dt(value)
    return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
