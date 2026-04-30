"""
screen_agent.cli — command-line interface for the scheduled screening agent.

A single OpenClaw cron calls `tick` every minute; it evaluates due screenings
and launches individual `run` subprocesses to execute them.

Usage:
    python -m services.agent.cli tick [--max-concurrent N]
    python -m services.agent.cli run <screening-id> [--result-id UUID] [--is-test] [--dry-run]
    python -m services.agent.cli setup-cron        # register the single tick cron in OpenClaw
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

    sub.add_parser("setup-cron", help="Register the single tick cron in OpenClaw")
    sub.add_parser("fmp-test", help="Test FMP MCP connectivity and list available tools")

    args = parser.parse_args()
    if args.command == "tick":
        cmd_tick(args)
    elif args.command == "run":
        cmd_run(args)
    elif args.command == "setup-cron":
        cmd_setup_cron(args)
    elif args.command == "fmp-test":
        cmd_fmp_test(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
