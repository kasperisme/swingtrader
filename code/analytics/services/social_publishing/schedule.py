"""Resolve *when* to publish — explicit time or best-engagement time.

Two sources of a schedule time, both returned as timezone-aware UTC datetimes
(we always send Zernio `scheduledFor` in UTC + `timezone:"UTC"` to avoid offset
ambiguity):

1. Explicit  — parse a user "YYYY-MM-DD HH:MM" in a local tz (default ET).
2. Best-time — Zernio `/v1/analytics/best-time` returns weekday×hour slots ranked
   by the account's own historical engagement. We take the top slot and schedule
   the next future occurrence. When there's no history yet (new account) or no
   Analytics add-on, we fall back to a clearly-labelled generic heuristic.

day_of_week convention is 0=Mon..6=Sun — matches both Zernio's slots and Python's
datetime.weekday(), so no remapping is needed.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

# Audience-local timezone for explicit times and the fallback heuristic.
DEFAULT_TZ = os.environ.get("SOCIAL_SCHEDULE_TZ", "America/New_York")

# Generic fallback when the account has no engagement history. NOT data — a
# documented default for a US retail-trader audience: Tue–Thu, platform-typical
# local hour. Always printed as "(generic default)" by the CLI.
_FALLBACK_LOCAL_HOUR = {
    "instagram": 19,   # evening scroll
    "tiktok": 20,      # prime-time evening
    "facebook": 13,    # midday
    "linkedin": 9,     # weekday morning, B2B
}
_FALLBACK_WEEKDAYS = (1, 2, 3)  # Tue, Wed, Thu


def parse_explicit(text: str, tz_name: str | None = None) -> datetime:
    """Parse 'YYYY-MM-DD HH:MM' (local tz) → aware UTC datetime."""
    tz = ZoneInfo(tz_name or DEFAULT_TZ)
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            naive = datetime.strptime(text.strip(), fmt)
            break
        except ValueError:
            naive = None
    if naive is None:
        raise ValueError(f"Could not parse time {text!r}; use 'YYYY-MM-DD HH:MM'.")
    return naive.replace(tzinfo=tz).astimezone(timezone.utc)


def next_occurrence_utc(day_of_week: int, hour: int, now_utc: datetime) -> datetime:
    """Next future UTC datetime matching (weekday, hour). Used for analytics slots."""
    days_ahead = (day_of_week - now_utc.weekday()) % 7
    cand = now_utc.replace(hour=hour, minute=0, second=0, microsecond=0) + timedelta(days=days_ahead)
    if cand <= now_utc:
        cand += timedelta(days=7)
    return cand


def fallback_utc(platform: str, now_utc: datetime, tz_name: str | None = None) -> datetime:
    """Soonest future Tue–Thu slot at the platform's local hour → aware UTC."""
    tz = ZoneInfo(tz_name or DEFAULT_TZ)
    hour = _FALLBACK_LOCAL_HOUR.get(platform, 19)
    now_local = now_utc.astimezone(tz)
    best: datetime | None = None
    for wd in _FALLBACK_WEEKDAYS:
        days_ahead = (wd - now_local.weekday()) % 7
        cand = now_local.replace(hour=hour, minute=0, second=0, microsecond=0) + timedelta(days=days_ahead)
        if cand <= now_local:
            cand += timedelta(days=7)
        if best is None or cand < best:
            best = cand
    return best.astimezone(timezone.utc)


def resolve_best(
    slots: list[dict] | None, platform: str, now_utc: datetime
) -> tuple[datetime, str]:
    """Pick a schedule time from analytics slots, else the fallback.

    Returns (utc_datetime, source_label) — label is shown to the user so a
    generic default is never mistaken for the account's real data.
    """
    if slots:
        top = max(slots, key=lambda s: s.get("avg_engagement", 0))
        when = next_occurrence_utc(int(top["day_of_week"]), int(top["hour"]), now_utc)
        label = (
            f"best-time (avg_engagement {top.get('avg_engagement')}, "
            f"{top.get('post_count')} posts)"
        )
        return when, label
    return fallback_utc(platform, now_utc), "generic default (no engagement history yet)"
