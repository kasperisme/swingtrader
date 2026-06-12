"""
billing.py — shared subscription/billing-state helpers for the Python layer.

Agents run for users who are either (a) on an active/trialing **paid** plan
(investor/trader), or (b) still inside their app-managed signup trial — every
account gets the full product free for TRIAL_DAYS from signup, with or without a
payment method. Everyone else — the free Observer tier and lapsed subscriptions
(past_due, unpaid, canceled, incomplete*) whose trial has also expired — must NOT
consume LLM resources; their due runs send a billing reminder only.

Mirrors the UI's tier logic (code/ui/lib/subscription.ts + lib/plans.ts —
TRIAL_DAYS / TRIAL_TIER) and is gated by the same pre-launch open-access switch
(code/ui/lib/launch.ts) so that during the open beta every user's agents keep
running. Flip PRELAUNCH_OPEN_ACCESS=false in the Python env at launch to turn
enforcement on.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

from .db import get_supabase_client

log = logging.getLogger(__name__)

_GOOD_STANDING = ("active", "trialing")
_PAID = ("investor", "trader")

# Mirror of code/ui/lib/plans.ts TRIAL_DAYS — keep in sync.
TRIAL_DAYS = 14


def _prelaunch_open_access() -> bool:
    """Mirror of the UI PRELAUNCH_OPEN_ACCESS flag. Default true (open beta)."""
    return os.environ.get("PRELAUNCH_OPEN_ACCESS", "true").strip().lower() != "false"


def _within_signup_trial(user_id: str) -> bool:
    """True while the account is inside its TRIAL_DAYS window from signup.

    Anchored on auth.users.created_at (read via the service-role admin API).
    Fails CLOSED (not in trial) on any error — the paid-subscription check runs
    first, so real customers are unaffected, and a blip can't extend the trial
    indefinitely.
    """
    try:
        client = get_supabase_client()
        resp = client.auth.admin.get_user_by_id(user_id)
        created = getattr(getattr(resp, "user", None), "created_at", None)
        if created is None:
            return False
        if isinstance(created, str):
            created = datetime.fromisoformat(created.replace("Z", "+00:00"))
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        age_days = (datetime.now(timezone.utc) - created).total_seconds() / 86400
        return age_days < TRIAL_DAYS
    except Exception as exc:
        log.warning("[billing] trial lookup failed for %s: %s", user_id, exc)
        return False


def agents_blocked(user_id: str) -> bool:
    """True when this user's scheduled agents should NOT run — i.e. they are on
    the free Observer tier, or their paid plan has lapsed AND their signup trial
    has expired.

    Returns False (allow) during pre-launch open access and on any subscription
    lookup error, so the failure mode is "run normally" rather than silently
    going dark for a paying user.
    """
    if _prelaunch_open_access():
        return False
    if not user_id:
        return False
    try:
        client = get_supabase_client()
        res = (
            client.schema("swingtrader")
            .table("user_subscriptions")
            .select("plan,status")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        rows = res.data or []
    except Exception as exc:  # never let a billing check break a run
        log.warning("[billing] tier lookup failed for %s: %s", user_id, exc)
        return False  # fail-open

    # An active/trialing paid plan always runs.
    if rows:
        row = rows[0]
        status = row.get("status") or ""
        plan = row.get("plan") or ""
        if status in _GOOD_STANDING and plan in _PAID:
            return False

    # No paid plan — allow only while still inside the signup trial window.
    if _within_signup_trial(user_id):
        return False

    return True
