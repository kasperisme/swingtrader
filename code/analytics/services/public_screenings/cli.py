"""
public_screenings.cli — script-backed public screenings.

``tick`` is invoked every minute by the ``public-screening-tick`` OpenClaw cron.
``run`` executes one screening (queued by ``tick`` or invoked manually).

Usage:
    python -m services.public_screenings.cli tick [--max-concurrent N]
    python -m services.public_screenings.cli run <public-screening-id> \\
        [--result-id UUID] [--is-test] [--dry-run]
    python -m services.public_screenings.cli setup-cron
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

from shared.db import get_supabase_client
from shared.health import JobHeartbeat


def _get_public_screening(screening_id: str) -> dict | None:
    client = get_supabase_client()
    res = (
        client.schema("swingtrader")
        .table("public_screenings")
        .select("*")
        .eq("id", screening_id)
        .limit(1)
        .execute()
    )
    return (res.data or [None])[0]


def cmd_tick(args: argparse.Namespace) -> None:
    from .scheduler import run_tick

    stats = run_tick(max_concurrent=args.max_concurrent)
    print(json.dumps(stats))


def cmd_run(args: argparse.Namespace) -> None:
    from .runner import persist_and_deliver_public, run_public_screening

    screening = _get_public_screening(args.screening_id)
    if not screening:
        print(f"Public screening {args.screening_id} not found", file=sys.stderr)
        sys.exit(1)

    is_test = args.is_test or bool(screening.get("run_requested_at"))

    with JobHeartbeat("public_screening_run", expected_interval=0.25):
        result = run_public_screening(screening, dry_run=args.dry_run, is_test=is_test)
        if not args.dry_run:
            persist_and_deliver_public(result, result_id=args.result_id)

    print(json.dumps(result, indent=2, default=str))


def cmd_setup_cron(_args: argparse.Namespace) -> None:
    from .sync_crons import setup_public_screening_tick_cron

    result = setup_public_screening_tick_cron()
    print(json.dumps(result))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Public screenings — script-backed shared runs",
    )
    sub = parser.add_subparsers(dest="command")

    p_tick = sub.add_parser(
        "tick",
        help="Run one scheduler tick (called every minute by OpenClaw public-screening-tick)",
    )
    p_tick.add_argument(
        "--max-concurrent",
        type=int,
        default=None,
        help="Max concurrent runs (default: PUBLIC_SCREENING_MAX_CONCURRENT or SCREENING_MAX_CONCURRENT, else 1)",
    )

    p_run = sub.add_parser(
        "run",
        help="Run one public screening (normally invoked by tick)",
    )
    p_run.add_argument("screening_id", help="UUID of the public_screenings row")
    p_run.add_argument(
        "--result-id",
        default=None,
        help="UUID of a pre-inserted public_screening_results row to update",
    )
    p_run.add_argument(
        "--is-test",
        action="store_true",
        help="Mark this run as a test (clears run_requested_at on the screening)",
    )
    p_run.add_argument("--dry-run", action="store_true")

    sub.add_parser(
        "setup-cron",
        help="Register only the public-screening-tick OpenClaw cron",
    )

    args = parser.parse_args()
    if args.command == "tick":
        cmd_tick(args)
    elif args.command == "run":
        cmd_run(args)
    elif args.command == "setup-cron":
        cmd_setup_cron(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
