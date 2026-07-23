"""Meta Conversions API — forward `early_access_signups` leads to Meta as CRM
`Lead` events (Meta's "Qualified Leads" / CRM integration).

Reads swingtrader.early_access_signups, SHA-256-hashes the PII (email + geo),
and POSTs `Lead` events to the dataset's /events endpoint with
`action_source: system_generated` and `custom_data.event_source: crm` — exactly
the CRM-lead shape Meta's guide specifies. It is:

  • Idempotent — every event carries `event_id = signup id`, so Meta dedups; and
    each uploaded row is stamped `meta_capi_sent_at`, so a re-run only sends new
    leads.
  • Privacy-safe — all contact info (email, city/region/country) is hashed
    before it leaves the server; user-agent / click-ids are sent raw as Meta
    requires (they are not contact PII).

These are our OWN web signups, not Meta Lead Ads, so there is no Meta-generated
`lead_id` to send (it's optional). Email is the primary match key; geo + UA are
added when captured. If we later capture `fbclid`→`fbc` on the signup form, it
flows through automatically (highest-priority match).

Config (code/analytics/.env):
  META_PIXEL_ID          dataset id (formerly pixel) — the /events target
  META_CAPI_TOKEN        access token for that dataset (falls back to META_ADS_TOKEN)
  META_API_VERSION       Graph API version (default from client)
  META_CAPI_LEAD_SOURCE  the CRM name reported as `lead_event_source` (default below)
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone

import requests

from . import client

DATASET = os.environ.get("META_PIXEL_ID", "")
CAPI_TOKEN = os.environ.get("META_CAPI_TOKEN") or client.TOKEN
LEAD_EVENT_SOURCE = os.environ.get("META_CAPI_LEAD_SOURCE", "News Impact Screener")
EVENT_NAME = "Lead"
_SCHEMA = "swingtrader"
_MAX_PER_REQUEST = 1000        # Meta hard cap per /events call


# ── hashing ──────────────────────────────────────────────────────────────────

def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _hash_email(email: str) -> str | None:
    e = str(email or "").strip().lower()
    return _sha(e) if e and "@" in e else None


def _hash_plain(value) -> str | None:
    """Normalize (trim, lowercase, drop internal spaces) then SHA-256 — for
    city / region / country / zip. None for empties."""
    v = str(value or "").strip().lower().replace(" ", "")
    return _sha(v) if v else None


# ── event construction ───────────────────────────────────────────────────────

def build_user_data(signup: dict) -> dict:
    """The `user_data` block: hashed contact info + raw match hints. Higher match
    quality = better attribution, so we send every field we actually have."""
    md = signup.get("metadata") or {}
    geo = md.get("geo") or {}
    device = md.get("device") or {}
    ud: dict = {}

    em = _hash_email(signup.get("email", ""))
    if em:
        ud["em"] = [em]
        ud["external_id"] = [em]        # stable per-user id (hashed email)

    for key, src in (("ct", geo.get("city")), ("st", geo.get("region")),
                     ("country", geo.get("country")), ("zp", geo.get("zip"))):
        h = _hash_plain(src)
        if h:
            ud[key] = [h]

    # click-ids / user-agent are sent RAW (not contact PII). Only present once the
    # signup form captures them — future-proofed here so no code change is needed.
    fbc = md.get("fbc") or md.get("fbclid")
    if fbc:
        ud["fbc"] = fbc
    if md.get("fbp"):
        ud["fbp"] = md["fbp"]
    if device.get("ua"):
        ud["client_user_agent"] = device["ua"]
    return ud


def _event_time(signup: dict) -> int:
    ts = signup.get("created_at")
    if isinstance(ts, datetime):
        dt = ts
    elif isinstance(ts, str):
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    else:
        dt = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def build_event(signup: dict) -> dict:
    """One CRM `Lead` server event for a signup row, per Meta's CRM guide."""
    return {
        "event_name": EVENT_NAME,
        "event_time": _event_time(signup),
        "action_source": "system_generated",
        "event_id": str(signup.get("id")),          # dedup key
        "custom_data": {
            "event_source": "crm",
            "lead_event_source": LEAD_EVENT_SOURCE,
        },
        "user_data": build_user_data(signup),
    }


# ── transport ────────────────────────────────────────────────────────────────

def send_events(events: list[dict], test_event_code: str | None = None) -> dict:
    """POST a batch of events to graph.facebook.com/<VERSION>/<DATASET>/events.
    Raises MetaError on a Graph API error; otherwise returns the parsed body
    (events_received, messages, fbtrace_id)."""
    if not DATASET:
        raise client.MetaError("META_PIXEL_ID (dataset id) not set in .env")
    if not CAPI_TOKEN:
        raise client.MetaError("META_CAPI_TOKEN / META_ADS_TOKEN not set in .env")
    if len(events) > _MAX_PER_REQUEST:
        raise client.MetaError(f"{len(events)} events exceeds Meta's {_MAX_PER_REQUEST}/request cap")
    form = {"data": json.dumps(events), "access_token": CAPI_TOKEN}
    if test_event_code:
        form["test_event_code"] = test_event_code
    r = requests.post(f"{client.BASE}/{DATASET}/events", data=form, timeout=60)
    return client._check(r)


# ── Supabase read / mark ─────────────────────────────────────────────────────

def fetch_unsent(since: str | None = None, limit: int = 500) -> list[dict]:
    """Early-access signups not yet forwarded to Meta, oldest first."""
    from shared.db import get_supabase_client
    c = get_supabase_client()
    q = (c.schema(_SCHEMA).table("early_access_signups")
         .select("id,email,created_at,metadata")
         .is_("meta_capi_sent_at", "null")
         .order("created_at", desc=False).limit(limit))
    if since:
        q = q.gte("created_at", since)
    return q.execute().data or []


def mark_sent(ids: list[str]) -> None:
    if not ids:
        return
    from shared.db import get_supabase_client
    c = get_supabase_client()
    now = datetime.now(timezone.utc).isoformat()
    for i in range(0, len(ids), 200):
        (c.schema(_SCHEMA).table("early_access_signups")
         .update({"meta_capi_sent_at": now}).in_("id", ids[i:i + 200]).execute())


# ── orchestration ────────────────────────────────────────────────────────────

def sync(since: str | None = None, limit: int = 500, dry_run: bool = False,
         test_event_code: str | None = None, batch: int = 500) -> int:
    """Upload all pending early-access leads to Meta. On a real (non-test) run,
    successfully-sent rows are stamped `meta_capi_sent_at`. Test runs never mark."""
    rows = fetch_unsent(since, limit)
    if not rows:
        print("No unsent early-access leads.")
        return 0

    # Skip rows with no hashable email — they have no usable match key.
    usable = [(r, build_event(r)) for r in rows]
    usable = [(r, e) for r, e in usable if e["user_data"].get("em")]
    skipped = len(rows) - len(usable)
    print(f"{len(rows)} unsent lead(s) · {len(usable)} with a hashable email"
          + (f" · {skipped} skipped (no email)" if skipped else ""))

    if dry_run:
        print("\n[dry-run] sample event (PII already hashed):")
        if usable:
            print(json.dumps(usable[0][1], indent=2))
        print(f"\n[dry-run] would POST {len(usable)} event(s) to dataset {DATASET}. Nothing sent.")
        return 0

    sent_ids: list[str] = []
    received = 0
    for i in range(0, len(usable), batch):
        chunk = usable[i:i + batch]
        resp = send_events([e for _, e in chunk], test_event_code=test_event_code)
        received += int(resp.get("events_received", 0) or 0)
        print(f"  batch {i // batch + 1}: events_received={resp.get('events_received')} "
              f"· fbtrace_id={resp.get('fbtrace_id')}")
        for m in resp.get("messages") or []:
            print(f"    ⚠ {m}")
        if not test_event_code:                     # only real uploads are persisted
            sent_ids += [str(r["id"]) for r, _ in chunk]

    if sent_ids:
        mark_sent(sent_ids)
    tag = " (TEST — rows NOT marked sent)" if test_event_code else f" · {len(sent_ids)} marked sent"
    print(f"\n✓ {received} event(s) received by Meta{tag}")
    return 0


def send_test(test_event_code: str) -> dict:
    """Send ONE synthetic Lead event (dummy hashed email) to verify the live
    connection. Shows up under Events Manager → Test Events for the given code."""
    ev = {
        "event_name": EVENT_NAME,
        "event_time": int(datetime.now(timezone.utc).timestamp()),
        "action_source": "system_generated",
        "event_id": "capi-conn-test",
        "custom_data": {"event_source": "crm", "lead_event_source": LEAD_EVENT_SOURCE},
        "user_data": {"em": [_sha("test@newsimpactscreener.com")]},
    }
    return send_events([ev], test_event_code=test_event_code)
