"""
screen_agent.cli — command-line interface for the scheduled screening agent.

A single OpenClaw cron calls `tick` every minute; it evaluates due user
screenings and launches individual `run` subprocesses. Public script
screenings use a separate OpenClaw cron → `services.market_screenings.cli tick`.

Usage:
    python -m services.agent.cli tick [--max-concurrent N]
    python -m services.agent.cli run <screening-id> [--result-id UUID] [--is-test] [--dry-run]
    python -m services.agent.cli setup-cron        # register screening-tick + market-screening-tick in OpenClaw
    python -m services.agent.cli fmp-test
"""

from __future__ import annotations

import argparse
import json
import logging
import pathlib
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

_ANALYTICS = pathlib.Path(__file__).resolve().parent.parent.parent

from dotenv import load_dotenv

load_dotenv(_ANALYTICS / ".env")
sys.path.insert(0, str(_ANALYTICS))

from shared.health import JobHeartbeat
from .engine import run_screening, persist_and_deliver, _FMP_ENABLED
from shared.db import get_supabase_client


def _get_screening(screening_id: str) -> dict | None:
    client = get_supabase_client()
    res = (
        client.schema("swingtrader")
        .table("user_scheduled_screenings")
        .select("*")
        .eq("id", screening_id)
        .limit(1)
        .execute()
    )
    return (res.data or [None])[0]


def cmd_tick(args):
    from .scheduler import run_tick
    stats = run_tick(max_concurrent=args.max_concurrent)
    print(json.dumps(stats))


def cmd_run(args):
    screening = _get_screening(args.screening_id)
    if not screening:
        print(f"Screening {args.screening_id} not found", file=sys.stderr)
        sys.exit(1)

    # --is-test flag is set by the scheduler for manual triggers; fallback to
    # the run_requested_at field for backward-compat direct invocations.
    is_test = args.is_test or bool(screening.get("run_requested_at"))

    with JobHeartbeat("screen_agent_run", expected_interval=0.25):
        result = run_screening(screening, dry_run=args.dry_run, is_test=is_test)
        if not args.dry_run:
            persist_and_deliver(result, result_id=args.result_id)

    print(json.dumps(result, indent=2, default=str))


def cmd_setup_cron(_args):
    from .sync_crons import setup_tick_cron
    result = setup_tick_cron()
    print(json.dumps(result))


def cmd_fmp_test(args):
    from .fmp_tools import test_fmp_connection
    print(f"FMP enabled: {_FMP_ENABLED}")
    test_fmp_connection()


def _resolve_ollama() -> tuple[str, str]:
    import os
    base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    model = (
        os.environ.get("OLLAMA_TIKTOK_MODEL")
        or os.environ.get("OLLAMA_BLOG_MODEL")
        or "gemma4:e4b"
    )
    return base_url, model


def cmd_validate_skills(args):
    """Check every skill's tool plan against a live registry.

    Reports, per skill: whether its required internal tools are present, which
    FMP tools resolve, and (with --probe) which FMP calls actually succeed under
    the current API plan. Run this after an FMP plan change.
    """
    import asyncio

    from .engine import _build_registry
    from .skills import SKILLS, _INTERNAL_TOOLS
    from .multi_ticker import _trial_run_plan, _result_unavailable

    registry = _build_registry(args.user_id or None)
    known = set(registry.names())
    print(f"Registry: {len(known)} tools (user_id={'set' if args.user_id else 'none'})\n")

    overall_ok = True
    for skill in SKILLS:
        missing_req = [t for t in skill.requires if t not in known]
        unknown_tools = [e["name"] for e in skill.tool_plan if e["name"] not in known]
        fmp = skill.fmp_tools()
        fmp_known = [t for t in fmp if t in known]
        fmp_unknown = [t for t in fmp if t not in known]

        status = "OK" if not missing_req else "DISQUALIFIED"
        if missing_req:
            overall_ok = False
        print(f"[{status}] {skill.id}")
        print(f"    requires:     {list(skill.requires)}" + (f"  MISSING={missing_req}" if missing_req else ""))
        print(f"    tools:        {[e['name'] for e in skill.tool_plan]}")
        if unknown_tools:
            print(f"    unknown:      {unknown_tools}  (dropped at runtime → internal floor)")
        if fmp:
            print(f"    fmp known:    {fmp_known or '—'}   fmp unknown: {fmp_unknown or '—'}")

        if args.probe and fmp_known:
            entries = [e for e in skill.tool_plan if e["name"] in fmp_known]
            unavailable, results = asyncio.run(_trial_run_plan(registry, entries, args.ticker))
            live = [n for n in fmp_known if n not in unavailable]
            print(f"    probe[{args.ticker}]: live={live or '—'}  unavailable={sorted(unavailable) or '—'}")
        print()

    print("All skills runnable on their internal floor." if overall_ok
          else "Some skills are DISQUALIFIED — required internal tools missing.")
    sys.exit(0 if overall_ok else 1)


def cmd_classify(args):
    """Show which skill a prompt routes to (debug the classifier)."""
    import asyncio
    import httpx

    from .skills import classify_skill

    base_url, model = _resolve_ollama()

    async def _go():
        async with httpx.AsyncClient() as client:
            return await classify_skill(
                client,
                base_url=base_url,
                model=model,
                prompt=args.prompt,
                trigger_condition=args.condition,
            )

    skill = asyncio.run(_go())
    print(json.dumps({
        "prompt": args.prompt,
        "skill": skill.id if skill else None,
        "route": "skill" if skill else "dynamic_planner",
    }, indent=2))


def main():
    parser = argparse.ArgumentParser(description="Scheduled Screening Agent")
    sub = parser.add_subparsers(dest="command")

    p_tick = sub.add_parser("tick", help="Run one scheduler tick (called every minute by cron)")
    p_tick.add_argument("--max-concurrent", type=int, default=None,
                        help="Max concurrent screenings (default: SCREENING_MAX_CONCURRENT env, else 1)")

    p_run = sub.add_parser("run", help="Run a specific screening")
    p_run.add_argument("screening_id")
    p_run.add_argument("--result-id", default=None,
                       help="UUID of a pre-inserted user_screening_results row to update")
    p_run.add_argument("--is-test", action="store_true",
                       help="Mark this run as a test (clears run_requested_at)")
    p_run.add_argument("--dry-run", action="store_true")

    sub.add_parser(
        "setup-cron",
        help="Register OpenClaw crons: screening-tick (agent) + market-screening-tick",
    )
    sub.add_parser("fmp-test", help="Test FMP MCP connectivity and list available tools")

    p_vs = sub.add_parser(
        "validate-skills",
        help="Check each predefined skill's tool plan against a live registry",
    )
    p_vs.add_argument("--user-id", default=None,
                      help="Validate user-scoped skills (portfolio_rundown) against this user's tools")
    p_vs.add_argument("--probe", action="store_true",
                      help="Actually call each skill's FMP tools to check API-plan availability")
    p_vs.add_argument("--ticker", default="AAPL", help="Probe ticker (default: AAPL)")

    p_cl = sub.add_parser("classify", help="Show which skill a prompt routes to")
    p_cl.add_argument("prompt")
    p_cl.add_argument("--condition", default=None, help="Optional trigger condition")

    args = parser.parse_args()
    if args.command == "tick":
        cmd_tick(args)
    elif args.command == "run":
        cmd_run(args)
    elif args.command == "setup-cron":
        cmd_setup_cron(args)
    elif args.command == "fmp-test":
        cmd_fmp_test(args)
    elif args.command == "validate-skills":
        cmd_validate_skills(args)
    elif args.command == "classify":
        cmd_classify(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
