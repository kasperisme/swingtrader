"""The Arena daily digest: email the standings and the day's trades after each session.

The list is swingtrader.arena_digest_subscriptions (migration 20261122150000), filled
by /api/arena/subscribe (the signup on /arena). `run-day` calls `send` once the night's
fill -> mark -> decide is done, so every closed session mails its subscribers.

What the mail carries, all from the PUBLIC views (a creative or a mail can never show
an agent that is not published):
  * the table: rank, movement since the previous session, return, today's change,
    and the one storyline the table supports (arena_creatives.storylines);
  * "filled at the open": every order that filled on this session;
  * "queued for the next open": every order the agents placed tonight, with the thesis.

Rules:
  * one mail per session (`arena_digest_sends`, claimed BEFORE any mail goes out);
  * every active subscriber gets the current session, including someone who signed
    up an hour ago: the mail is the table as it stands, not news they missed.

    python -m services.arena.cli digest --dry-run
    python -m services.arena.cli digest [--session YYYY-MM-DD]
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

log = logging.getLogger(__name__)

SCHEMA = "swingtrader"
SLUG = "arena"
TABLE = "arena_digest_subscriptions"

EFFECT = {
    "open_long": "bought",
    "close_long": "sold",
    "open_short": "shorted",
    "cover_short": "covered",
    "flip_to_short": "flipped short",
    "flip_to_long": "flipped long",
}

_SANS = "'Plus Jakarta Sans',-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif"
_MONO = "ui-monospace,Menlo,monospace"
_TEXT, _MUTED, _BORDER, _PANEL = "#0f1729", "#546378", "#dfd6cd", "#f2eee8"
_GAIN, _LOSS = "#15803d", "#b91c1c"


def _pct(x: Optional[float], signed: bool = True) -> str:
    if x is None:
        return "–"
    return f"{x * 100:+.2f}%" if signed else f"{x * 100:.2f}%"


def _money(x: Optional[float]) -> str:
    return "–" if x is None else f"${x:,.2f}"


def _tone(x: Optional[float]) -> str:
    return _MUTED if not x else (_GAIN if x > 0 else _LOSS)


def _move(m: Optional[int]) -> str:
    if not m:
        return "&nbsp;"
    return f'<span style="color:{_GAIN};">&#9650;{m}</span>' if m > 0 else f'<span style="color:{_LOSS};">&#9660;{-m}</span>'


def _verb(o: dict) -> str:
    return EFFECT.get(o.get("position_effect") or "", "bought" if o["side"] == "buy" else "sold")


def build(session: Optional[str] = None) -> dict[str, Any]:
    """Everything the mail needs, for the latest marked session (or `session`)."""
    from services.arena_creatives import data_sources as ds
    from services.arena_creatives.storylines import headline

    standings = ds.build_standings(move_lookback=1)
    as_of = standings["asOf"]
    if session and session != as_of:
        raise LookupError(f"latest marked session is {as_of}, not {session}; the digest only goes out for the current table")
    champ = ds.resolve_championship()
    daily = {r["slug"]: r.get("daily_return") for r in ds.fetch_leaderboard(champ["id"])}
    names = {r["slug"]: r["name"] for r in standings["rows"]}
    orders = (
        ds._tbl("arena_orders_public_v")
        .select("agent_slug,ticker,side,quantity,status,thesis,stop_price,target_price,intended_for,fill_price,notional,realized_pnl,realized_pct,position_effect")
        .eq("championship_id", champ["id"])
        .gte("intended_for", as_of)
        .execute()
        .data
        or []
    )
    orders = [o for o in orders if o["agent_slug"] in names]
    filled = sorted((o for o in orders if o["intended_for"] == as_of and o["status"] == "filled"),
                    key=lambda o: (names[o["agent_slug"]], o["ticker"]))
    queued = sorted((o for o in orders if o["intended_for"] > as_of and o["status"] == "pending"),
                    key=lambda o: (names[o["agent_slug"]], o["ticker"]))
    for r in standings["rows"]:
        r["daily"] = None if daily.get(r["slug"]) is None else float(daily[r["slug"]])
    return {
        "session": as_of,
        "championship": standings["championship"],
        "headline": headline(standings),
        "rows": standings["rows"],
        "names": names,
        "filled": filled,
        "queued": queued,
        "next_session": min((o["intended_for"] for o in queued), default=None),
    }


def render(d: dict[str, Any], unsub: str) -> tuple[str, str, str]:
    from shared.email import _hesc, app_url, cta_primary

    url = f"{app_url()}/arena"
    names = d["names"]
    hl = d["headline"]
    subject = f"Arena, {d['session']}: {hl['headline']}"

    table = "".join(
        f'<tr><td style="padding:7px 4px;font-family:{_MONO};color:{_MUTED};width:22px;">{r["rank"]}</td>'
        f'<td style="padding:7px 4px;font-family:{_MONO};font-size:11px;width:30px;">{_move(r.get("move"))}</td>'
        f'<td style="padding:7px 4px;color:{_TEXT};font-weight:600;">'
        f'<a href="{_hesc(app_url())}/agent/{_hesc(r["slug"])}" style="color:{_TEXT};text-decoration:none;">{_hesc(r["name"])}</a></td>'
        f'<td style="padding:7px 4px;text-align:right;font-family:{_MONO};color:{_tone(r["return"])};">{_pct(r["return"])}</td>'
        f'<td style="padding:7px 4px;text-align:right;font-family:{_MONO};font-size:12px;color:{_tone(r.get("daily"))};">{_pct(r.get("daily"))}</td></tr>'
        for r in d["rows"])

    def trade_rows(orders: list[dict], queued: bool) -> str:
        if not orders:
            return f'<p style="font-size:13px;color:{_MUTED};margin:6px 0 0 0;">{"No new orders." if queued else "Nothing filled."}</p>'
        out = []
        for o in orders:
            who = _hesc(names[o["agent_slug"]])
            qty = f'{float(o["quantity"]):,.0f}'
            if queued:
                what = f'{"buy" if o["side"] == "buy" else "sell"} {qty} {_hesc(o["ticker"])}'
                thesis = (o.get("thesis") or "").strip()
                thesis = thesis[:180] + ("…" if len(thesis) > 180 else "")
                extra = f'<div style="font-size:12px;color:{_MUTED};margin-top:2px;">{_hesc(thesis)}</div>' if thesis else ""
            else:
                what = f'{_verb(o)} {qty} {_hesc(o["ticker"])} at {_money(o.get("fill_price"))}'
                pnl = o.get("realized_pnl")
                extra = (f'<div style="font-size:12px;color:{_tone(pnl)};margin-top:2px;">realised {_money(pnl)} ({_pct(o.get("realized_pct"))})</div>'
                         if pnl not in (None, 0) else "")
            out.append(f'<div style="padding:8px 0;border-bottom:1px solid {_BORDER};font-size:14px;color:{_TEXT};">'
                       f'<strong>{who}</strong> {what}{extra}</div>')
        return "".join(out)

    h3 = f"font-family:{_MONO};font-size:10px;letter-spacing:.16em;text-transform:uppercase;color:{_MUTED};margin:24px 0 4px 0;"
    nxt = f" ({_hesc(d['next_session'])})" if d.get("next_session") else ""
    html = f"""<!doctype html><html><body style="margin:0;padding:0;background:#f1ece4;">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;">{_hesc(hl.get('detail') or '')}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f1ece4;padding:32px 16px;"><tr><td align="center">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:560px;background:#fefdfb;border:1px solid {_BORDER};border-radius:12px;">
<tr><td style="padding:28px 28px 8px 28px;font-family:{_SANS};">
<div style="font-family:{_MONO};font-size:11px;letter-spacing:.18em;text-transform:uppercase;color:#b45309;">The Arena &middot; {_hesc(d['championship'].get('name') or '')} &middot; {_hesc(d['session'])}</div>
<h1 style="font-size:21px;line-height:1.3;color:{_TEXT};margin:14px 0 0 0;">{_hesc(hl['headline'])}</h1>
<p style="font-size:14px;line-height:1.6;color:{_MUTED};margin:8px 0 0 0;">{_hesc(hl.get('detail') or '')}</p>
<div style="{h3}">The table</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="font-size:14px;background:{_PANEL};border-radius:8px;">
<tr><td colspan="3"></td><td style="padding:6px 4px 0;text-align:right;font-size:10px;color:{_MUTED};">season</td><td style="padding:6px 4px 0;text-align:right;font-size:10px;color:{_MUTED};">today</td></tr>
{table}</table>
<div style="{h3}">Filled at the open</div>{trade_rows(d['filled'], False)}
<div style="{h3}">Queued for the next open{nxt}</div>{trade_rows(d['queued'], True)}
</td></tr>
<tr><td style="padding:22px 28px 28px 28px;">{cta_primary("Open the Arena", url)}</td></tr>
<tr><td style="padding:18px 28px;border-top:1px solid {_BORDER};font-family:{_SANS};">
<p style="font-size:11px;line-height:1.6;color:{_MUTED};margin:0;">Paper trading with $100,000 per agent, not investment advice. Orders fill at the next session's open. You're receiving this because you asked for the Arena's daily digest. <a href="{_hesc(unsub)}" style="color:{_MUTED};">Unsubscribe</a>.</p>
</td></tr></table></td></tr></table></body></html>"""

    def tline(o: dict, queued: bool) -> str:
        n = names[o["agent_slug"]]
        if queued:
            return f"  {n}: {'buy' if o['side'] == 'buy' else 'sell'} {float(o['quantity']):,.0f} {o['ticker']}"
        return f"  {n}: {_verb(o)} {float(o['quantity']):,.0f} {o['ticker']} at {_money(o.get('fill_price'))}"

    text = "\n".join([
        f"The Arena, {d['session']}: {hl['headline']}", hl.get("detail") or "", "",
        *[f"{r['rank']}. {r['name']}  {_pct(r['return'])} (today {_pct(r.get('daily'))})" for r in d["rows"]], "",
        "Filled at the open:", *([tline(o, False) for o in d["filled"]] or ["  nothing"]), "",
        f"Queued for the next open{' (' + d['next_session'] + ')' if d.get('next_session') else ''}:",
        *([tline(o, True) for o in d["queued"]] or ["  nothing"]), "",
        f"Open the Arena: {url}", "", "Paper trading, not investment advice.", f"Unsubscribe: {unsub}",
    ])
    return subject, html, text


def send(session: Optional[str] = None, dry_run: bool = False, sb=None) -> dict:
    from shared.db import get_supabase_client
    from shared.email import send_email
    from shared.update_lists import backfill, unsubscribe_url

    d = build(session)
    st = (sb or get_supabase_client()).schema(SCHEMA)
    try:
        st.table(TABLE).select("email").limit(1).execute()
    except Exception as exc:  # noqa: BLE001
        if "PGRST205" not in str(exc) and "does not exist" not in str(exc):
            raise
        waiting = st.table("early_access_signups").select("email").eq("source", f"{SLUG}_updates").execute().data or []
        out = {"ok": not dry_run, "session": d["session"], "skipped": "migration 20261122150000 not applied",
               "waiting_signups": len(waiting)}
        if dry_run:
            out["ok"] = True
            out["preview"] = render(d, "https://example.com/unsubscribe")[2]
        return out
    if not dry_run and st.table("arena_digest_sends").select("session").eq("session", d["session"]).execute().data:
        return {"ok": True, "session": d["session"], "skipped": "already sent"}
    backfilled = 0 if dry_run else backfill(st, TABLE, SLUG)
    subs = st.table(TABLE).select("email,created_at,last_sent_session").eq("status", "active").execute().data or []
    # Unlike the correction list there is no "signed up after" rule: tonight's mail is
    # the current table, which is what a new subscriber asked for.
    subs = [s for s in subs if not s.get("last_sent_session") or s["last_sent_session"] < d["session"]]
    if dry_run:
        subject, _html, text = render(d, "https://example.com/unsubscribe")
        return {"ok": True, "session": d["session"], "dry_run": True, "recipients": len(subs), "subject": subject,
                "filled": len(d["filled"]), "queued": len(d["queued"]), "preview": text}
    st.table("arena_digest_sends").insert({"session": d["session"], "recipients": len(subs)}).execute()
    sent = failed = 0
    for s in subs:
        subject, html, text = render(d, unsubscribe_url("/api/arena/unsubscribe", s["email"], SLUG))
        ok, info = send_email(to=s["email"], subject=subject, html=html, text=text,
                              tags=[{"name": "type", "value": "arena_daily_digest"}])
        if ok:
            sent += 1
            st.table(TABLE).update({"last_sent_session": d["session"]}).eq("email", s["email"]).execute()
        else:
            failed += 1
            log.warning("arena digest %s: %s", s["email"], info)
    st.table("arena_digest_sends").update(
        {"finished_at": datetime.now(timezone.utc).isoformat(), "sent": sent, "failed": failed}).eq("session", d["session"]).execute()
    return {"ok": True, "session": d["session"], "recipients": len(subs), "sent": sent, "failed": failed, "backfilled": backfilled}
