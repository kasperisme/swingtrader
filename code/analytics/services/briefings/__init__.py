"""News briefing service — the free, no-account daily PDF email.

A visitor subscribes (on /briefings) to a watchlist of tickers and/or tags and
receives a structured PDF of the last 24h of news + stored sentiment/impact:

    data.py      — gather_briefing(): assemble the briefing from already-scored
                   data (no LLM). Reuses services.rag.
    action.py    — the ONE account-requiring ask per send, derived from this
                   reader's own watchlist. Until this existed the email's calls
                   to action pointed at /marketscreenings and /pricing, both of
                   which resolve while logged out — so the only surface that
                   reaches every subscriber on a schedule never once created
                   the conditions for an account (105 addresses, 19 accounts).
    render.py    — briefing → on-brand HTML → Playwright PDF bytes.
    send.py      — render + deliver via Resend with manage/unsubscribe links,
                   plus the signed one-click sign-in link the action points at
                   (verified by code/ui/app/auth/briefing/route.ts, which trades
                   it for a real session and creates the account if absent —
                   they proved the address when they subscribed, so a password
                   would re-verify a fact we already hold).
    scheduler.py — minute tick: immediate signup sends + daily 08:30 ET fan-out.
    cli.py       — tick | send | send-daily | preview | preview-email | setup-cron.
"""
