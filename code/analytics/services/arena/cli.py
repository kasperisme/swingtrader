#!/usr/bin/env python3
"""
arena CLI — run and inspect the competing paper-trading agents.

    # One-time: write roster.py into the DB and open the $100k accounts
    python -m services.arena.cli sync-roster

    # The nightly job (fill -> mark -> decide). This is what cron runs.
    python -m services.arena.cli run-day

    # Individual passes, for debugging or backfill
    python -m services.arena.cli fill   [--session 2026-09-02]
    python -m services.arena.cli mark   [--session 2026-09-02]
    python -m services.arena.cli decide [--only headline-hunter] [--dry-run]

    # Inspect
    python -m services.arena.cli standings
    python -m services.arena.cli show headline-hunter
    python -m services.arena.cli orders [--slug headline-hunter] [--limit 20]

    # Wipe one agent's trading history back to cash (keeps its definition)
    python -m services.arena.cli reset --slug the-coinflip --yes
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date, datetime, timedelta
from typing import Optional

from shared.db import get_supabase_client

from . import backtest as backtest_mod, championships, scheduler, store
from .marks import PriceBook

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
)
log = logging.getLogger("arena")


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value)


def _fmt_money(v) -> str:
    try:
        return f"${float(v):,.0f}"
    except (TypeError, ValueError):
        return "—"


def _fmt_pct(v, digits: int = 2) -> str:
    try:
        return f"{float(v) * 100:+.{digits}f}%"
    except (TypeError, ValueError):
        return "—"


# ── Commands ─────────────────────────────────────────────────────────────────


def _bind(args) -> Optional[dict]:
    """Activate the championship this invocation writes into.

    Returns None and prints guidance if there is none — every command below
    touches a book, and a book only exists inside a championship.
    """
    try:
        return scheduler.bind_championship(getattr(args, "championship", None))
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return None


def cmd_championship(args) -> int:
    action = args.action

    if action == "list":
        rows = championships.list_all()
        if not rows:
            print("No championships yet. Create one:\n"
                  "  arena championship create --slug season-1 --name 'Season 1' "
                  "--start 2026-09-04 --end 2026-10-30")
            return 0
        print(f"\n{'SLUG':<18} {'STATUS':<10} {'WINDOW':<25} {'CHAMPION':<18}")
        print("-" * 74)
        for c in rows:
            champ = ""
            if c.get("champion_agent_id"):
                a = _agent_name(c["champion_agent_id"])
                champ = f"{a} ({_fmt_pct(c.get('champion_return'))})"
            window = f"{c['starts_on']} → {c['ends_on']}"
            flag = " [replay]" if c.get("is_backtest") else ""
            print(f"{c['slug']:<18} {c['status'] + flag:<10} {window:<25} {champ:<18}")
        return 0

    if action == "current":
        c = championships.current()
        if not c:
            print("No championship running.")
            return 0
        print(f"{c['name']}  ({c['slug']})")
        print(f"  {c['starts_on']} → {c['ends_on']}   ${float(c['starting_cash']):,.0f} each")
        for i, r in enumerate(championships.standings(c["id"]), 1):
            print(f"   {i}. {r['name']:<20} {_fmt_pct(r.get('total_return'))}")
        return 0

    if action == "title":
        lineage = championships.title_lineage()
        if not lineage:
            print("No championship has been concluded yet — the title is vacant.")
            return 0
        print(f"\n{'REIGN':<6} {'CHAMPION':<20} {'FROM':<12} {'THROUGH':<12} {'WON':>4} {'DEF':>4}")
        print("-" * 62)
        for r in lineage:
            mark = "  <- current" if r.get("is_current_holder") else ""
            print(f"{r['reign_no']:<6} {r['agent_name']:<20} {str(r['held_from']):<12} "
                  f"{str(r['held_through']):<12} {r['championships_won']:>4} "
                  f"{r['successful_defences']:>4}{mark}")
        return 0

    if action == "create":
        starts = _parse_date(args.start) or scheduler.last_closed_session() or date.today()
        ends = _parse_date(args.end)
        if ends is None:
            ends = championships.add_months(starts, args.months) - timedelta(days=1)
        c = championships.create(
            args.slug, args.name or args.slug.replace("-", " ").title(),
            starts, ends,
            description=args.description,
            starting_cash=args.starting_cash,
            is_backtest=args.backtest,
        )
        print(f"Created {c['slug']} ({c['starts_on']} → {c['ends_on']}), status={c['status']}.")
        print(f"  {args.months}-month window, ${float(c['starting_cash']):,.0f} per agent.")
        print("Start it with:  arena championship start --slug " + c["slug"])
        return 0

    if action == "start":
        try:
            c = championships.start(args.slug, entrants=args.only.split(",") if args.only else None)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(f"Started {c['slug']} — {len(c.get('entrants', []))} agents funded at "
              f"${float(c['starting_cash']):,.0f} each.")
        return 0

    if action == "conclude":
        try:
            r = championships.conclude(args.slug)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        if r.get("champion"):
            print(f"{r['champion']} wins {r['slug']} with {_fmt_pct(r['champion_return'])}"
                  f" over {r['entrants']} entrants.")
            if r.get("runner_up"):
                print(f"Runner-up: {r['runner_up']}")
            holder = championships.reigning_champion()
            if holder:
                d = holder["successful_defences"]
                print(f"Title: {holder['agent_name']} — {holder['championships_won']} "
                      f"championship(s), {d} defence(s).")
        return 0

    if action == "abandon":
        print(championships.abandon(args.slug, args.reason))
        return 0

    print(f"Unknown action {action!r}", file=sys.stderr)
    return 1


def _agent_name(agent_id: str) -> str:
    r = (
        get_supabase_client().schema("swingtrader").table("arena_agents")
        .select("name").eq("id", agent_id).limit(1).execute().data or []
    )
    return r[0]["name"] if r else agent_id[:8]


def cmd_sync_roster(args) -> int:
    rows = scheduler.sync_roster(fund=not args.no_fund, funded_on=_parse_date(args.funded_on))
    for r in rows:
        print(f"  {r['slug']:<20} {r['engine']:<14} {r['id']}")
    print(f"\n{len(rows)} agents synced.")
    return 0


def cmd_run_day(args) -> int:
    if _bind(args) is None:
        return 1
    result = scheduler.run_day(
        session=_parse_date(args.session),
        only=args.only.split(",") if args.only else None,
        skip_decide=args.skip_decide,
        dry_run=args.dry_run,
    )
    print(json.dumps(result, indent=2, default=str))
    return 1 if result.get("error") else 0


def cmd_fill(args) -> int:
    if _bind(args) is None:
        return 1
    prices = PriceBook()
    session = _parse_date(args.session) or scheduler.last_closed_session()
    if session is None:
        print("No closed session found.", file=sys.stderr)
        return 1
    print(json.dumps(scheduler.run_fill(session, prices), indent=2))
    return 0


def cmd_mark(args) -> int:
    if _bind(args) is None:
        return 1
    prices = PriceBook()
    session = _parse_date(args.session) or scheduler.last_closed_session()
    if session is None:
        print("No closed session found.", file=sys.stderr)
        return 1
    for row in scheduler.run_mark(session, prices):
        print(f"  {row['slug']:<20} {_fmt_money(row['nav'])}")
    return 0


def cmd_decide(args) -> int:
    if _bind(args) is None:
        return 1
    prices = PriceBook()
    session = _parse_date(args.session) or scheduler.last_closed_session(book=prices)
    if session is None:
        print("No closed session found.", file=sys.stderr)
        return 1
    intended = _parse_date(args.intended_for) or scheduler.next_session_after(session)

    results = scheduler.run_decide(
        session,
        intended,
        prices,
        only=args.only.split(",") if args.only else None,
        dry_run=args.dry_run,
        concurrency=args.concurrency,
    )
    for r in results:
        if r.get("dry_run"):
            print(f"\n=== {r['slug']} (dry run) ===")
            print(f"  model: {r.get('model')}")
            print(f"  tools: {', '.join(r.get('tools') or [])}")
            if r.get("intents"):
                print(f"  intents: {r['intents']}")
            continue
        status = r.get("status")
        line = f"  {r['slug']:<20} {status:<7}"
        if status == "ok":
            line += (
                f" {r.get('orders_accepted', 0)} filled-pending / "
                f"{r.get('orders_rejected', 0)} rejected"
            )
            if r.get("duration_s"):
                line += f"  ({r['duration_s']}s)"
        else:
            line += f" {r.get('error', '')[:80]}"
        print(line)
        if r.get("narrative"):
            print(f"      {r['narrative'][:200]}")
    return 0


def cmd_standings(args) -> int:
    if _bind(args) is None:
        return 1
    rows = (
        get_supabase_client()
        .schema("swingtrader")
        .table("arena_leaderboard_v")
        .select("*")
        .execute()
        .data
        or []
    )
    if not rows:
        print("No standings yet — run `sync-roster` then `run-day`.")
        return 0

    rows.sort(key=lambda r: (r.get("total_return") is None, -(r.get("total_return") or 0)))
    print(
        f"\n{'#':<3} {'AGENT':<22} {'NAV':>12} {'RETURN':>9} {'MAX DD':>8} "
        f"{'SHARPE':>7} {'POS':>4} {'TRADES':>7} {'WIN%':>6}"
    )
    print("-" * 88)
    for i, r in enumerate(rows, 1):
        sharpe = r.get("sharpe")
        print(
            f"{i:<3} {r['name'][:22]:<22} {_fmt_money(r.get('nav')):>12} "
            f"{_fmt_pct(r.get('total_return')):>9} {_fmt_pct(r.get('max_drawdown'), 1):>8} "
            f"{(f'{float(sharpe):.2f}' if sharpe is not None else '—'):>7} "
            f"{r.get('n_positions') or 0:>4} {r.get('filled_orders') or 0:>7} "
            f"{(f'{float(r['win_rate']) * 100:.0f}' if r.get('win_rate') is not None else '—'):>6}"
        )
    as_of = next((r.get("as_of") for r in rows if r.get("as_of")), None)
    print(f"\nAs of {as_of or 'never marked'}.")
    return 0


def cmd_show(args) -> int:
    if _bind(args) is None:
        return 1
    agent = store.get_agent(args.slug)
    if not agent:
        print(f"No agent {args.slug!r}.", file=sys.stderr)
        return 1

    portfolio = store.load_portfolio(agent)
    nav = portfolio.nav
    starting = float(agent.get("starting_cash") or 0)

    print(f"\n{agent['name']}  ({agent['slug']})")
    print(f"  {agent.get('tagline') or ''}")
    print(f"\n  NAV     {_fmt_money(nav)}   ({_fmt_pct(nav / starting - 1 if starting else None)})")
    print(f"  Cash    {_fmt_money(portfolio.cash)}")
    print(f"  Engine  {agent.get('engine')}   Shorts: {agent.get('allow_shorts')}")

    if portfolio.positions:
        print(f"\n  {'TICKER':<8} {'QTY':>10} {'COST':>10} {'MARK':>10} {'VALUE':>12} {'P&L':>10}")
        for p in sorted(portfolio.positions, key=lambda x: abs(x.market_value), reverse=True):
            print(
                f"  {p.ticker:<8} {p.quantity:>10,.0f} {p.avg_cost:>10,.2f} "
                f"{p.mark:>10,.2f} {p.market_value:>12,.0f} "
                f"{_fmt_pct(p.unrealized_pct):>10}"
            )
    else:
        print("\n  No open positions.")

    decision = store.get_decision(agent["id"], date.today()) or _latest_decision(agent["id"])
    if decision and decision.get("narrative"):
        print(f"\n  Latest reasoning ({decision['decision_date']}):")
        for line in _wrap(decision["narrative"], 76):
            print(f"    {line}")
    return 0


def _latest_decision(agent_id: str):
    rows = (
        get_supabase_client()
        .schema("swingtrader")
        .table("arena_decisions")
        .select("*")
        .eq("agent_id", agent_id)
        .order("decision_date", desc=True)
        .limit(1)
        .execute()
        .data
        or []
    )
    return rows[0] if rows else None


def _wrap(text: str, width: int) -> list[str]:
    import textwrap

    return textwrap.wrap(text, width=width) or [""]


def cmd_orders(args) -> int:
    if _bind(args) is None:
        return 1
    q = (
        get_supabase_client()
        .schema("swingtrader")
        .table("arena_orders_public_v")
        .select("*")
    )
    if args.slug:
        q = q.eq("agent_slug", args.slug)
    rows = q.order("submitted_at", desc=True).limit(args.limit).execute().data or []
    if not rows:
        print("No orders.")
        return 0
    for r in rows:
        pnl = r.get("realized_pnl")
        print(
            f"  {str(r.get('submitted_at'))[:10]}  {r['agent_slug']:<18} "
            f"{r['side']:<4} {r['ticker']:<6} x{float(r['quantity']):<8,.0f} "
            f"{r['status']:<9} "
            f"{('@ $' + format(float(r['fill_price']), ',.2f')) if r.get('fill_price') else '':<14}"
            f"{(f'P&L {pnl:+,.0f}' if pnl is not None else '')}"
        )
        if r.get("reject_reason"):
            print(f"       ! {r['reject_reason'][:100]}")
        elif r.get("thesis"):
            print(f"       {r['thesis'][:100]}")
    return 0


def cmd_backtest(args) -> int:
    if _bind(args) is None:
        return 1
    start = _parse_date(args.start)
    end = _parse_date(args.end) or scheduler.last_closed_session()
    if start is None:
        print("--start is required (YYYY-MM-DD).", file=sys.stderr)
        return 1
    if end is None:
        print("No closed session found for --end.", file=sys.stderr)
        return 1

    slugs = args.only.split(",") if args.only else None

    if args.wipe and not args.yes and not args.dry_run:
        print(
            "--wipe DELETES every order, position, decision and NAV row for the\n"
            "agents in scope, including trades already placed live, and re-funds\n"
            "them at the replay start date. Re-run with --yes to confirm.",
            file=sys.stderr,
        )
        return 1

    result = backtest_mod.run_backtest(
        start,
        end,
        slugs=slugs,
        decide_every=args.decide_every,
        wipe=args.wipe,
        resume=not args.no_resume,
        point_in_time=args.point_in_time,
        concurrency=args.concurrency,
        dry_run=args.dry_run,
    )
    print(json.dumps(result, indent=2, default=str))
    if result.get("status") == "dry_run":
        print(
            f"\nWould replay {result['sessions']} sessions "
            f"({result['first']} -> {result['last']}), "
            f"{result['decision_days']} decision days, ~{result['estimated_hours']}h of LLM time.",
            file=sys.stderr,
        )
    return 1 if result.get("error") else 0


def cmd_backtest_delete(args) -> int:
    out = backtest_mod.delete_run(args.run_id)
    print(json.dumps(out, indent=2))
    return 0


def cmd_reset(args) -> int:
    if _bind(args) is None:
        return 1
    agent = store.get_agent(args.slug)
    if not agent:
        print(f"No agent {args.slug!r}.", file=sys.stderr)
        return 1
    if not args.yes:
        print(
            f"This deletes every order, position, decision and NAV row for "
            f"{agent['name']} and returns it to "
            f"{_fmt_money(agent.get('starting_cash'))} cash.\n"
            f"Re-run with --yes to confirm.",
            file=sys.stderr,
        )
        return 1

    sb = get_supabase_client().schema("swingtrader")
    for table in ("arena_orders", "arena_positions", "arena_decisions", "arena_nav_history"):
        sb.table(table).delete().eq("agent_id", agent["id"]).execute()
    store.set_cash(agent["id"], float(agent.get("starting_cash") or 100_000))
    sb.table("arena_agents").update(
        {"funded_on": datetime.now().date().isoformat()}
    ).eq("id", agent["id"]).execute()
    print(f"Reset {agent['name']}.")
    return 0


# ── Wiring ───────────────────────────────────────────────────────────────────


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="arena", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("sync-roster", help="write roster.py to the DB (definitions only)")
    p.add_argument("--no-fund", action="store_true", help="(deprecated: funding happens on championship start)")
    p.add_argument("--funded-on", help="(deprecated)")
    p.set_defaults(func=cmd_sync_roster)

    # ── championships ───────────────────────────────────────────────────────
    p = sub.add_parser("championship", help="create / start / conclude a championship")
    p.add_argument(
        "action",
        choices=["list", "current", "title", "create", "start", "conclude", "abandon"],
        help="'title' prints the belt lineage: who holds it and how many defences",
    )
    p.add_argument("--slug")
    p.add_argument("--name")
    p.add_argument("--start", help="YYYY-MM-DD (default: last closed session)")
    p.add_argument(
        "--end",
        help=f"YYYY-MM-DD. Omit to use the standard "
             f"{championships.DEFAULT_DURATION_MONTHS}-month window from --start.",
    )
    p.add_argument(
        "--months", type=int, default=championships.DEFAULT_DURATION_MONTHS,
        help=f"window length when --end is omitted (default: "
             f"{championships.DEFAULT_DURATION_MONTHS})",
    )
    p.add_argument("--description")
    p.add_argument("--starting-cash", type=float, default=100000.0)
    p.add_argument("--backtest", action="store_true",
                   help="mark the whole championship as a historical replay")
    p.add_argument("--only", help="comma-separated slugs to enter (default: all active)")
    p.add_argument("--reason", help="abandon reason")
    p.set_defaults(func=cmd_championship)

    p = sub.add_parser("run-day", help="the nightly job: fill, mark, decide")
    p.add_argument("--session", help="YYYY-MM-DD (default: last closed session)")
    p.add_argument("--only", help="comma-separated slugs")
    p.add_argument("--skip-decide", action="store_true")
    p.add_argument("--dry-run", action="store_true", help="no orders, no LLM calls")
    p.add_argument("--championship", help="slug (default: the running one)")
    p.set_defaults(func=cmd_run_day)

    p = sub.add_parser("fill", help="execute pending orders at a session's open")
    p.add_argument("--session", help="YYYY-MM-DD")
    p.add_argument("--championship", help="slug (default: the running one)")
    p.set_defaults(func=cmd_fill)

    p = sub.add_parser("mark", help="mark books to a session's close, append NAV")
    p.add_argument("--session", help="YYYY-MM-DD")
    p.add_argument("--championship", help="slug (default: the running one)")
    p.set_defaults(func=cmd_mark)

    p = sub.add_parser("decide", help="run agent decisions")
    p.add_argument("--session", help="YYYY-MM-DD of the closed session")
    p.add_argument("--intended-for", help="YYYY-MM-DD the orders fill in")
    p.add_argument("--only", help="comma-separated slugs")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--championship", help="slug (default: the running one)")
    p.add_argument(
        "--concurrency", type=int, default=scheduler.DEFAULT_CONCURRENCY,
        help="LLM agents in flight at once",
    )
    p.set_defaults(func=cmd_decide)

    p = sub.add_parser("standings", help="the leaderboard")
    p.add_argument("--championship", help="slug (default: the running one)")
    p.set_defaults(func=cmd_standings)

    p = sub.add_parser("show", help="one agent's book and latest reasoning")
    p.add_argument("slug")
    p.add_argument("--championship", help="slug (default: the running one)")
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("orders", help="recent orders")
    p.add_argument("--slug")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--championship", help="slug (default: the running one)")
    p.set_defaults(func=cmd_orders)

    p = sub.add_parser("backtest", help="replay the arena over past sessions")
    p.add_argument("--start", required=True, help="YYYY-MM-DD, first session to replay")
    p.add_argument("--end", help="YYYY-MM-DD (default: last closed session)")
    p.add_argument("--only", help="comma-separated slugs (default: whole roster)")
    p.add_argument(
        "--decide-every", type=int, default=1, metavar="N",
        help="run LLM decisions every N sessions; fills and marks still run every "
             "session. N=5 (weekly) cuts a 67-session replay from ~19h to ~4h.",
    )
    p.add_argument("--wipe", action="store_true",
                   help="DELETE existing history and re-fund at the start date")
    p.add_argument("--yes", action="store_true", help="confirm --wipe")
    p.add_argument("--no-resume", action="store_true",
                   help="ignore existing NAV rows instead of continuing after them")
    p.add_argument(
        "--concurrency", type=int, default=scheduler.DEFAULT_CONCURRENCY, metavar="N",
        help=f"LLM agents in flight at once (default {scheduler.DEFAULT_CONCURRENCY}). "
             "Sessions are always sequential — only agents within a session run "
             "in parallel.",
    )
    p.add_argument("--point-in-time", action="store_true",
                   help="gate the sources that can be rewound honestly (off by "
                        "default: applying it unevenly makes agents non-comparable)")
    p.add_argument("--dry-run", action="store_true",
                   help="print the plan and cost estimate without running")
    p.add_argument("--championship", help="slug (default: the running one)")
    p.set_defaults(func=cmd_backtest)

    p = sub.add_parser("backtest-delete", help="remove every row a replay wrote")
    p.add_argument("run_id")
    p.set_defaults(func=cmd_backtest_delete)

    p = sub.add_parser("reset", help="wipe one agent's trading history")
    p.add_argument("--slug", required=True)
    p.add_argument("--yes", action="store_true")
    p.add_argument("--championship", help="slug (default: the running one)")
    p.set_defaults(func=cmd_reset)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
