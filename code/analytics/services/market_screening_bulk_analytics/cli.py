"""
market_screening_bulk_analytics.cli — entry point for the post-screening LLM pass.

Usage:
    python -m services.market_screening_bulk_analytics.cli tick [--max-concurrent N]
    python -m services.market_screening_bulk_analytics.cli run <result-id>

`tick` is invoked every minute by the OpenClaw cron registered via
`services.market_screening_bulk_analytics.sync_crons`; it picks up queued
`market_screening_results` rows and dispatches a subprocess per row that
calls `run`.
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


def cmd_tick(args: argparse.Namespace) -> None:
    from .scheduler import run_tick

    stats = run_tick(max_concurrent=args.max_concurrent)
    print(json.dumps(stats))


def cmd_run(args: argparse.Namespace) -> None:
    from .worker import run_pass

    with JobHeartbeat("market_bulk_analysis_run", expected_interval=0.25):
        result = run_pass(args.result_id)
    print(json.dumps(result, indent=2, default=str))


def cmd_setup_cron(_args: argparse.Namespace) -> None:
    from .sync_crons import setup_market_bulk_analysis_tick_cron

    result = setup_market_bulk_analysis_tick_cron()
    print(json.dumps(result))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Market-screening bulk LLM analytics worker",
    )
    sub = parser.add_subparsers(dest="command")

    p_tick = sub.add_parser("tick", help="Run one scheduler tick (every minute)")
    p_tick.add_argument(
        "--max-concurrent",
        type=int,
        default=None,
        help="Max concurrent passes (default: PUBLIC_BULK_ANALYSIS_MAX_CONCURRENT, else 1)",
    )

    p_run = sub.add_parser(
        "run", help="Run one bulk-analysis pass for a market_screening_results row"
    )
    p_run.add_argument("result_id", help="UUID of a market_screening_results row")

    sub.add_parser(
        "setup-cron",
        help="Register the public-bulk-analysis-tick OpenClaw cron",
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
