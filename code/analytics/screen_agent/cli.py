"""
screen_agent.cli — command-line interface for the scheduled screening agent.

Usage:
    python -m screen_agent.cli run-all [--dry-run]
    python -m screen_agent.cli run <screening-id> [--dry-run]
    python -m screen_agent.cli test <screening-id>
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

_ANALYTICS = pathlib.Path(__file__).resolve().parent.parent

from dotenv import load_dotenv

load_dotenv(_ANALYTICS / ".env")
sys.path.insert(0, str(_ANALYTICS))

from src.health import JobHeartbeat
from .engine import run_screening, run_all_due, persist_and_deliver
from src.db import get_supabase_client, get_schema


def _get_screening(screening_id: str) -> dict | None:
    client = get_supabase_client()
    schema = get_schema()
    res = (
        client.schema(schema)
        .table("user_scheduled_screenings")
        .select("*")
        .eq("id", screening_id)
        .limit(1)
        .execute()
    )
    return (res.data or [None])[0]


def cmd_run_all(args):
    dry_run = args.dry_run
    if not dry_run:
        with JobHeartbeat("screen_agent", expected_interval=0.25):
            results = run_all_due(dry_run=False)
    else:
        results = run_all_due(dry_run=True)

    print(json.dumps(results, indent=2, default=str))


def cmd_run(args):
    screening = _get_screening(args.screening_id)
    if not screening:
        print(f"Screening {args.screening_id} not found", file=sys.stderr)
        sys.exit(1)

    result = run_screening(screening, dry_run=args.dry_run)
    if not args.dry_run:
        persist_and_deliver(result)

    print(json.dumps(result, indent=2, default=str))


def cmd_test(args):
    screening = _get_screening(args.screening_id)
    if not screening:
        print(f"Screening {args.screening_id} not found", file=sys.stderr)
        sys.exit(1)

    result = run_screening(screening, dry_run=True)
    print(json.dumps(result, indent=2, default=str))


def main():
    parser = argparse.ArgumentParser(description="Scheduled Screening Agent")
    sub = parser.add_subparsers(dest="command")

    p_all = sub.add_parser("run-all", help="Run all due screenings")
    p_all.add_argument("--dry-run", action="store_true")

    p_run = sub.add_parser("run", help="Run a specific screening")
    p_run.add_argument("screening_id")
    p_run.add_argument("--dry-run", action="store_true")

    p_test = sub.add_parser("test", help="Dry-run a screening (no save, no delivery)")
    p_test.add_argument("screening_id")

    args = parser.parse_args()
    if args.command == "run-all":
        cmd_run_all(args)
    elif args.command == "run":
        cmd_run(args)
    elif args.command == "test":
        cmd_test(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
