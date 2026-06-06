"""
billing.py — shared subscription/billing-state helpers for the Python layer.

Agents only run for users on an active/trialing **paid** plan (investor/trader).
Everyone else — the free Observer tier (no subscription row) and lapsed/failing
subscriptions (past_due, unpaid, canceled, incomplete*) — is the "observer"
tier and must NOT consume LLM resources; their due runs send a billing reminder
only.

Mirrors the UI's tier logic (code/ui/lib/subscription.ts) and is gated by the
same pre-launch open-access switch (code/ui/lib/launch.ts) so that during the
open beta every user's agents keep running. Flip PRELAUNCH_OPEN_ACCESS=false in
the Python env at launch to turn enforcement on.
"""

from __future__ import annotations

import logging
import os

from .db import get_supabase_client

log = logging.getLogger(__name__)

_GOOD_STANDING = ("active", "trialing")
_PAID = ("investor", "trader")


def _prelaunch_open_access() -> bool:
    """Mirror of the UI PRELAUNCH_OPEN_ACCESS flag. Default true (open beta)."""
    return os.environ.get("PRELAUNCH_OPEN_ACCESS", "true").strip().lower() != "false"


def agents_blocked(user_id: str) -> bool:
    """True when this user's scheduled agents should NOT run — i.e. they are on
    the free Observer tier or their paid plan has lapsed.

    Returns False (allow) during pre-launch open access and on any lookup error,
    so the failure mode is "run normally" rather than silently going dark for a
    paying user.
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

    if not rows:
        return True  # no subscription → free Observer → blocked
    row = rows[0]
    status = row.get("status") or ""
    plan = row.get("plan") or ""
    # Only an active/trialing paid plan may run agents.
    return not (status in _GOOD_STANDING and plan in _PAID)
