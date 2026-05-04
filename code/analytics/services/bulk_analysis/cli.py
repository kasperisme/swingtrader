"""
bulk_analysis.cli — entry point for the bulk per-ticker analysis worker.

Usage:
    python -m services.bulk_analysis.cli tick [--max-concurrent N]
    python -m services.bulk_analysis.cli run <job-id>

`tick` is invoked every minute by the Mac Mini's system crontab via
scripts/run_bulk_analysis_tick.sh; it picks up queued jobs and dispatches
a subprocess per job that calls `run`.
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


def cmd_tick(args):
    from .scheduler import run_tick
    stats = run_tick(max_concurrent=args.max_concurrent)
    print(json.dumps(stats))


def cmd_run(args):
    from .worker import run_job
    with JobHeartbeat("bulk_analysis_run", expected_interval=0.25):
        result = run_job(args.job_id)
    print(json.dumps(result, indent=2, default=str))


def main():
    parser = argparse.ArgumentParser(description="Bulk Per-Ticker Analysis Worker")
    sub = parser.add_subparsers(dest="command")

    p_tick = sub.add_parser("tick", help="Run one scheduler tick (every minute)")
    p_tick.add_argument(
        "--max-concurrent",
        type=int,
        default=None,
        help="Max concurrent bulk jobs (default: BULK_ANALYSIS_MAX_CONCURRENT env, else 1)",
    )

    p_run = sub.add_parser("run", help="Run a specific bulk-analysis job")
    p_run.add_argument("job_id", help="UUID of a user_bulk_analysis_jobs row")

    args = parser.parse_args()
    if args.command == "tick":
        cmd_tick(args)
    elif args.command == "run":
        cmd_run(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
