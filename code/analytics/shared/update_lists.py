"""Email-only update lists (correction stress test, Arena digest): the shared bits.

Signups come from the site (/api/<list>/subscribe, code/ui/lib/email/update-lists.ts).
Until a list's migration is applied, signups wait in early_access_signups under
source `<slug>_updates`; `backfill` moves them into the list before a send.
"""

from __future__ import annotations

from urllib.parse import quote


def unsubscribe_url(path: str, email: str, slug: str) -> str:
    from shared.email import app_url, sign_unsubscribe_token

    return f"{app_url()}{path}?token={quote(sign_unsubscribe_token(email, [slug]), safe='')}"


def backfill(st, table: str, slug: str) -> int:
    rows = st.table("early_access_signups").select("email,created_at,metadata").eq("source", f"{slug}_updates").execute().data or []
    if not rows:
        return 0
    st.table(table).upsert(
        [{"email": r["email"].strip().lower(), "status": "active", "source": f"{slug}_updates_backfill",
          "metadata": r.get("metadata") or {}, "created_at": r["created_at"]} for r in rows],
        on_conflict="email", ignore_duplicates=True).execute()
    return len(rows)
