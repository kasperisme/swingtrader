"""
screen_agent.cli — command-line interface for the scheduled screening agent.

OpenClaw handles scheduling. This CLI runs individual screenings.

Usage:
    python -m services.agent.cli run <screening-id> [--dry-run]
    python -m services.agent.cli sync
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
from .engine import run_screening, persist_and_deliver
from shared.db import get_supabase_client


def _get_screening(screening_id: str) -> dict | None:
    client = get_supabase_client()
    schema = "swingtrader"
    res = (
        client.schema(schema)
        .table("user_scheduled_screenings")
        .select("*")
        .eq("id", screening_id)
        .limit(1)
        .execute()
    )
    return (res.data or [None])[0]


def cmd_run(args):
    screening = _get_screening(args.screening_id)
    if not screening:
        print(f"Screening {args.screening_id} not found", file=sys.stderr)
        sys.exit(1)

    is_test = bool(screening.get("run_requested_at"))

    with JobHeartbeat("screen_agent_run", expected_interval=0.25):
        result = run_screening(screening, dry_run=args.dry_run, is_test=is_test)
        if not args.dry_run:
            persist_and_deliver(result)

    print(json.dumps(result, indent=2, default=str))


def cmd_sync(args):
    from .sync_crons import run_sync
    stats = run_sync()
    print(json.dumps(stats))


def main():
    parser = argparse.ArgumentParser(description="Scheduled Screening Agent")
    sub = parser.add_subparsers(dest="command")

    p_run = sub.add_parser("run", help="Run a specific screening")
    p_run.add_argument("screening_id")
    p_run.add_argument("--dry-run", action="store_true")

    p_sync = sub.add_parser("sync", help="Sync screenings to OpenClaw cron jobs")

    args = parser.parse_args()
    if args.command == "run":
        cmd_run(args)
    elif args.command == "sync":
        cmd_sync(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
