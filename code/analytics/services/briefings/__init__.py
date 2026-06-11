"""News briefing service — the free, no-account daily PDF email.

A visitor subscribes (on /briefings) to a watchlist of tickers and/or tags and
receives a structured PDF of the last 24h of news + stored sentiment/impact:

    data.py      — gather_briefing(): assemble the briefing from already-scored
                   data (no LLM). Reuses services.rag.
    render.py    — briefing → on-brand HTML → Playwright PDF bytes.
    send.py      — render + deliver via Resend with manage/unsubscribe links.
    scheduler.py — minute tick: immediate signup sends + daily 08:30 ET fan-out.
    cli.py       — tick | send | send-daily | preview | setup-cron.
"""
