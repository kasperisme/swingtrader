"""Email the correction stress-test subscribers when a new analysis is published.

The list is swingtrader.drawdown_analysis_subscriptions (migration 20261122120000),
filled by /api/correction/subscribe: the header link, the /correction page and the
site-wide promo. Until that migration is applied, signups wait in
early_access_signups (source "correction_updates"); `send` backfills them first.

Rules:
  * one mail per published day (`drawdown_analysis_notifications`, claimed BEFORE
    any mail goes out, so a re-run or a crash mid-send never mails twice);
  * a subscriber only hears about analyses published AFTER they signed up;
  * the mail carries the group counts and the link. Nothing members-only.

    python -m services.drawdown.cli notify --dry-run      # who would get what
    python -m services.drawdown.cli notify                # send for the latest run

`judge apply --db` calls `send` once the reviewed day is written, so a published
analysis mails its subscribers without another step.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

log = logging.getLogger(__name__)

SCHEMA = "swingtrader"
SLUG = "correction"
GROUP_COPY = [
    ("on_top", "On top", "survive a bust-sized forecast cut, with recovery upside"),
    ("holds", "Holds", "survive a correction-sized cut"),
    ("fragile", "Fragile", "only just paid for"),
    ("drowns", "Drowns", "the price already funds more growth than analysts forecast"),
]


def _unsub_url(email: str) -> str:
    from shared.update_lists import unsubscribe_url

    return unsubscribe_url("/api/correction/unsubscribe", email, SLUG)


def render(run: dict, prev: dict | None, email: str) -> tuple[str, str, str]:
    from shared.email import _hesc, app_url, cta_primary

    url = f"{app_url()}/correction"
    g, pg = run.get("groups") or {}, (prev or {}).get("groups") or {}
    rows, lines = [], []
    for key, label, gloss in GROUP_COPY:
        n = int(g.get(key) or 0)
        delta = "" if not prev else f" ({n - int(pg.get(key) or 0):+d} since {prev['as_of']})"
        rows.append(
            f'<tr><td style="padding:8px 0;font-weight:600;color:#0f1729;">{label}</td>'
            f'<td style="padding:8px 0;text-align:right;font-family:ui-monospace,Menlo,monospace;color:#0f1729;">'
            f'{n}{_hesc(delta)}</td></tr>'
            f'<tr><td colspan="2" style="padding:0 0 8px 0;font-size:12px;color:#546378;border-bottom:1px solid #dfd6cd;">{gloss}</td></tr>')
        lines.append(f"{label}: {n}{delta}")
    subject = f"New correction stress test: {run['as_of']}"
    unsub = _unsub_url(email)
    html = f"""<!doctype html><html><body style="margin:0;padding:0;background:#f1ece4;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f1ece4;padding:32px 16px;"><tr><td align="center">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:520px;background:#fefdfb;border:1px solid #dfd6cd;border-radius:12px;">
<tr><td style="padding:28px 28px 8px 28px;font-family:'Plus Jakarta Sans',-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;">
<div style="font-family:ui-monospace,Menlo,monospace;font-size:11px;letter-spacing:.18em;text-transform:uppercase;color:#b45309;">Correction stress test &middot; {_hesc(run['as_of'])}</div>
<h1 style="font-size:22px;line-height:1.3;color:#0f1729;margin:14px 0 0 0;">A new analysis is out</h1>
<p style="font-size:15px;line-height:1.6;color:#0f1729;margin:12px 0 0 0;">We re-solved what {int(run.get('universe') or 0)} share prices need to be true at the latest close, and how far analysts' forecasts can be cut before each one is short. Here is where they landed:</p>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-top:16px;font-size:14px;">{''.join(rows)}</table>
</td></tr>
<tr><td style="padding:20px 28px 28px 28px;">{cta_primary("See every name", url)}</td></tr>
<tr><td style="padding:18px 28px;border-top:1px solid #dfd6cd;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;">
<p style="font-size:11px;line-height:1.6;color:#546378;margin:0;">Research, not investment advice. Nothing here has been graded against returns yet. You're receiving this because you asked for correction stress test updates. <a href="{_hesc(unsub)}" style="color:#546378;">Unsubscribe</a>.</p>
</td></tr></table></td></tr></table></body></html>"""
    text = "\n".join([f"A new correction stress test is out ({run['as_of']}).", "", *lines, "", f"See every name: {url}",
                      "", "Research, not investment advice.", f"Unsubscribe: {unsub}"])
    return subject, html, text


def send(as_of: str | None = None, dry_run: bool = False, sb=None) -> dict:
    from shared.db import get_supabase_client
    from shared.email import send_email
    from shared.update_lists import backfill

    st = (sb or get_supabase_client()).schema(SCHEMA)
    runs = st.table("drawdown_narrative_runs").select("as_of,universe,groups,finished_at").order("as_of", desc=True).limit(10).execute().data or []
    run = next((r for r in runs if not as_of or r["as_of"] == as_of), None)
    if not run:
        return {"ok": False, "reason": f"no published run{' for ' + as_of if as_of else ''}"}
    prev = next((r for r in runs if r["as_of"] < run["as_of"]), None)
    if st.table("drawdown_analysis_notifications").select("as_of").eq("as_of", run["as_of"]).execute().data:
        return {"ok": True, "as_of": run["as_of"], "skipped": "already notified"}
    backfilled = 0 if dry_run else backfill(st, "drawdown_analysis_subscriptions", SLUG)
    published = run.get("finished_at") or datetime.now(timezone.utc).isoformat()
    subs = st.table("drawdown_analysis_subscriptions").select("email,created_at,last_notified_as_of") \
        .eq("status", "active").lt("created_at", published).execute().data or []
    subs = [s for s in subs if not s.get("last_notified_as_of") or s["last_notified_as_of"] < run["as_of"]]
    if dry_run:
        return {"ok": True, "as_of": run["as_of"], "dry_run": True, "recipients": len(subs),
                "subject": render(run, prev, "x@example.com")[0]}
    # Claim the day first: a second run (or a crash mid-send) must never mail twice.
    st.table("drawdown_analysis_notifications").insert({"as_of": run["as_of"], "recipients": len(subs)}).execute()
    sent = failed = 0
    for s in subs:
        subject, html, text = render(run, prev, s["email"])
        ok, info = send_email(to=s["email"], subject=subject, html=html, text=text,
                              tags=[{"name": "type", "value": "correction_new_analysis"}])
        if ok:
            sent += 1
            st.table("drawdown_analysis_subscriptions").update({"last_notified_as_of": run["as_of"]}).eq("email", s["email"]).execute()
        else:
            failed += 1
            log.warning("correction notify %s: %s", s["email"], info)
    st.table("drawdown_analysis_notifications").update(
        {"finished_at": datetime.now(timezone.utc).isoformat(), "sent": sent, "failed": failed}).eq("as_of", run["as_of"]).execute()
    return {"ok": True, "as_of": run["as_of"], "recipients": len(subs), "sent": sent, "failed": failed, "backfilled": backfilled}
