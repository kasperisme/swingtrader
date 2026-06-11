"""services.briefings.cli — command line for the news-briefing service.

    python -m services.briefings.cli tick [--max-per-tick N]
    python -m services.briefings.cli send <subscription-id> [--welcome]
    python -m services.briefings.cli send-daily            # force the daily fan-out now
    python -m services.briefings.cli preview --tickers AAPL,MSFT --tags ai [--out FILE]
    python -m services.briefings.cli setup-cron            # register briefing-tick in OpenClaw
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from datetime import datetime, timezone

_ANALYTICS = pathlib.Path(__file__).resolve().parent.parent.parent

from dotenv import load_dotenv

load_dotenv(_ANALYTICS / ".env")
sys.path.insert(0, str(_ANALYTICS))


def cmd_tick(args):
    from .scheduler import run_tick
    print(json.dumps(run_tick(max_per_tick=args.max_per_tick)))


def cmd_send(args):
    from shared.db import get_supabase_client
    from .send import send_briefing

    client = get_supabase_client()
    res = (
        client.schema("swingtrader")
        .table("news_briefing_subscriptions")
        .select("*")
        .eq("id", args.subscription_id)
        .limit(1)
        .execute()
    )
    sub = (res.data or [None])[0]
    if not sub:
        print(f"Subscription {args.subscription_id} not found", file=sys.stderr)
        sys.exit(1)
    ok, info = send_briefing(sub, is_welcome=args.welcome)
    print(json.dumps({"ok": ok, "info": info}))
    sys.exit(0 if ok else 1)


def cmd_send_daily(args):
    """Force the daily fan-out immediately (ignores the schedule window)."""
    from shared.db import get_supabase_client
    from .scheduler import _send_daily, MAX_PER_TICK
    from datetime import datetime, timezone

    client = get_supabase_client()
    # A fire "now" means: serve everyone whose last send predates this moment.
    sent = _send_daily(client, datetime.now(timezone.utc), args.max_per_tick or MAX_PER_TICK)
    print(json.dumps({"daily": sent}))


def cmd_preview(args):
    """Render a briefing PDF to a file without sending — for design iteration."""
    from .data import gather_briefing
    from .narrative import add_narratives
    from .render import render_briefing_pdf

    tickers = [t for t in (args.tickers or "").split(",") if t.strip()]
    tags = [t for t in (args.tags or "").split(",") if t.strip()]
    if not tickers and not tags:
        print("Provide --tickers and/or --tags", file=sys.stderr)
        sys.exit(1)

    briefing = gather_briefing(tickers, tags, hours=args.hours)
    if not args.no_narrative:
        add_narratives(briefing)
    pdf = render_briefing_pdf(briefing)
    out = args.out or str(
        _ANALYTICS / "output" / "briefings" / f"preview-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.pdf"
    )
    path = pathlib.Path(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(pdf)
    print(json.dumps({
        "out": str(path),
        "total_articles": briefing["total_articles"],
        "tickers": len(briefing["tickers"]),
        "tags": len(briefing["tags"]),
    }, indent=2))


def cmd_setup_cron(_args):
    from .sync_crons import setup_briefing_tick_cron
    print(json.dumps(setup_briefing_tick_cron()))


def main():
    parser = argparse.ArgumentParser(description="News Briefing service")
    sub = parser.add_subparsers(dest="command")

    p_tick = sub.add_parser("tick", help="Run one scheduler tick (called every minute by cron)")
    p_tick.add_argument("--max-per-tick", type=int, default=None)

    p_send = sub.add_parser("send", help="Send one subscription's briefing now")
    p_send.add_argument("subscription_id")
    p_send.add_argument("--welcome", action="store_true", help="Use first-briefing copy")

    p_daily = sub.add_parser("send-daily", help="Force the daily fan-out now")
    p_daily.add_argument("--max-per-tick", type=int, default=None)

    p_prev = sub.add_parser("preview", help="Render a PDF to a file without sending")
    p_prev.add_argument("--tickers", default="", help="Comma-separated tickers, e.g. AAPL,MSFT")
    p_prev.add_argument("--tags", default="", help="Comma-separated tags, e.g. ai,energy")
    p_prev.add_argument("--hours", type=int, default=24)
    p_prev.add_argument("--out", default=None)
    p_prev.add_argument("--no-narrative", action="store_true", help="Skip Ollama tag narratives")

    sub.add_parser("setup-cron", help="Register the briefing-tick OpenClaw cron")

    args = parser.parse_args()
    dispatch = {
        "tick": cmd_tick,
        "send": cmd_send,
        "send-daily": cmd_send_daily,
        "preview": cmd_preview,
        "setup-cron": cmd_setup_cron,
    }
    fn = dispatch.get(args.command)
    if not fn:
        parser.print_help()
        return
    fn(args)


if __name__ == "__main__":
    main()
