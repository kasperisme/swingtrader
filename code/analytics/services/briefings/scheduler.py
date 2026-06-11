"""scheduler.py — minute tick for the news-briefing service.

One OpenClaw cron calls ``tick`` every minute. Each tick does two things:

  1. Immediate sends: any subscription with ``initial_briefing_requested_at``
     set (just signed up, or asked for a fresh one) gets its briefing now, then
     the flag is cleared. New subscribers receive their first PDF within ~1 min.

  2. Daily fan-out: one hour before the NYSE open (08:30 America/New_York,
     weekdays), every active subscription receives a briefing. Idempotency comes
     from ``last_sent_at`` — we only send when the last delivery predates the
     most recent scheduled fire, so a missed/duplicated tick can't double-send
     and a tick that runs a few minutes late still catches the day.

Sending is inline but bounded (``BRIEFING_MAX_PER_TICK``); if more are due than
the cap, the next tick continues where this one left off. Rendering a PDF takes
~1–2s, so the cap keeps a single tick well under the cron timeout.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from croniter import croniter

from shared.db import get_supabase_client
from shared.screening_schedule import to_utc

from .send import send_briefing

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

_SCHEMA = "swingtrader"
# 08:30 ET, weekdays — one hour before the 09:30 NYSE open. Override via env.
_DAILY_CRON = os.environ.get("BRIEFING_DAILY_CRON", "30 8 * * 1-5")
_DAILY_TZ = ZoneInfo(os.environ.get("BRIEFING_TZ", "America/New_York"))
MAX_PER_TICK = int(os.environ.get("BRIEFING_MAX_PER_TICK", "25"))


def _most_recent_fire(now_utc: datetime) -> datetime:
    """Most recent scheduled fire (UTC) at or before ``now_utc``."""
    now_local = now_utc.astimezone(_DAILY_TZ).replace(tzinfo=None)
    prev_local = croniter(_DAILY_CRON, now_local).get_prev(datetime)
    return prev_local.replace(tzinfo=_DAILY_TZ).astimezone(timezone.utc)


_TABLE = "news_briefing_subscriptions"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _claim_immediate(client, sub_id: str) -> bool:
    """Atomically claim a pending immediate send by clearing the flag.

    Only one tick wins: the conditional update matches only while the flag is
    still set, so a concurrent (overlapping) tick that already cleared it gets
    zero rows back. Returns True if THIS tick claimed the row.
    """
    res = (
        client.schema(_SCHEMA).table(_TABLE)
        .update({"initial_briefing_requested_at": None, "updated_at": _now_iso()})
        .eq("id", sub_id)
        .not_.is_("initial_briefing_requested_at", "null")
        .execute()
    )
    return bool(res.data)


def _claim_daily(client, sub_id: str, fire_iso: str) -> bool:
    """Atomically claim a daily send by stamping last_sent_at=now.

    The conditional update only matches while last_sent_at is still before this
    fire, so overlapping ticks claim disjoint rows — never the same one twice.
    """
    res = (
        client.schema(_SCHEMA).table(_TABLE)
        .update({"last_sent_at": _now_iso(), "updated_at": _now_iso()})
        .eq("id", sub_id)
        .or_(f"last_sent_at.is.null,last_sent_at.lt.{fire_iso}")
        .execute()
    )
    return bool(res.data)


def _rearm_immediate(client, sub_id: str) -> None:
    """Send failed after claiming — restore the flag so a later tick retries."""
    client.schema(_SCHEMA).table(_TABLE).update(
        {"initial_briefing_requested_at": _now_iso(), "updated_at": _now_iso()}
    ).eq("id", sub_id).execute()


def _release_daily(client, sub_id: str) -> None:
    """Send failed after claiming — clear last_sent_at so a later tick retries."""
    client.schema(_SCHEMA).table(_TABLE).update(
        {"last_sent_at": None, "updated_at": _now_iso()}
    ).eq("id", sub_id).execute()


def _send_immediate(client, budget: int) -> int:
    """Send to subscriptions awaiting their first/forced briefing.

    Claim-before-send makes this safe under overlapping crontab ticks: each row
    is sent at most once; a send failure re-arms the flag for a later retry.
    """
    if budget <= 0:
        return 0
    rows = (
        client.schema(_SCHEMA)
        .table(_TABLE)
        .select("*")
        .eq("status", "active")
        .not_.is_("initial_briefing_requested_at", "null")
        .order("initial_briefing_requested_at", desc=False)
        .limit(budget)
        .execute()
    ).data or []

    sent = 0
    for sub in rows:
        if not _claim_immediate(client, sub["id"]):
            continue  # another tick already took this one
        ok, _info = send_briefing(sub, is_welcome=True)
        if ok:
            # Stamp the delivery time (the claim already cleared the flag).
            client.schema(_SCHEMA).table(_TABLE).update(
                {"last_sent_at": _now_iso(), "updated_at": _now_iso()}
            ).eq("id", sub["id"]).execute()
            sent += 1
        else:
            _rearm_immediate(client, sub["id"])
    return sent


def _send_daily(client, fire_utc: datetime, budget: int) -> int:
    """Send the daily briefing to active subs not yet served for ``fire_utc``.

    Claim-before-send (stamping last_sent_at) means overlapping ticks drain the
    queue in parallel on disjoint rows; a send failure clears the stamp so the
    row is retried on a later tick.
    """
    if budget <= 0:
        return 0
    fire_iso = fire_utc.isoformat()
    # Active, no pending immediate send (those are handled above), and either
    # never sent or last sent before this fire.
    rows = (
        client.schema(_SCHEMA)
        .table(_TABLE)
        .select("*")
        .eq("status", "active")
        .is_("initial_briefing_requested_at", "null")
        .or_(f"last_sent_at.is.null,last_sent_at.lt.{fire_iso}")
        .order("last_sent_at", desc=False)
        .limit(budget)
        .execute()
    ).data or []

    sent = 0
    for sub in rows:
        if not _claim_daily(client, sub["id"], fire_iso):
            continue  # another tick already took this one
        ok, _info = send_briefing(sub, is_welcome=False)
        if ok:
            sent += 1
        else:
            _release_daily(client, sub["id"])
    return sent


def run_tick(max_per_tick: int | None = None) -> dict:
    """One scheduler tick. Called every minute by the briefing-tick cron."""
    client = get_supabase_client()
    cap = max_per_tick if max_per_tick is not None else MAX_PER_TICK
    now_utc = datetime.now(timezone.utc)

    immediate = _send_immediate(client, cap)

    # Only run the daily pass if a scheduled fire has occurred today (i.e. the
    # most recent fire is today in the schedule's timezone). Outside the daily
    # window the prev-fire is yesterday and every active sub was already served,
    # so this is naturally a no-op — but we still gate to avoid the query.
    fire = _most_recent_fire(now_utc)
    daily = 0
    remaining = cap - immediate
    if remaining > 0 and fire.astimezone(_DAILY_TZ).date() == now_utc.astimezone(_DAILY_TZ).date():
        daily = _send_daily(client, fire, remaining)

    log.info("Briefing tick: immediate=%d daily=%d (fire=%s)", immediate, daily, fire.isoformat())
    return {"immediate": immediate, "daily": daily, "fire": fire.isoformat()}


# Re-exported for callers that want the helper in tests / CLI.
__all__ = ["run_tick", "_most_recent_fire", "to_utc"]
