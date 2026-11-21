"""
Run any command under JobHeartbeat — for jobs that live outside this venv.

The priced-in batch runs in strategylab's own Python, which cannot import
``shared.health``. Wrapping the command here gets it into ``job_health`` /
``job_runs`` and the watchdog without coupling the two environments.

    python -m shared.heartbeat_run --job priced_in_batch --interval 24 -- \\
        /path/to/other/.venv/bin/python -m some.cli batch

Exit-code contract with the wrapped command:
    0  → success
    3  → partial_fail (alert, but the wrapper exits 0)
    *  → failed (alert, and the wrapper exits with the same code)

The child's stdout/stderr pass straight through, so cron logs are unchanged.
"""

from __future__ import annotations

import argparse
import subprocess
import sys

from shared.health import JobHeartbeat, PartialJobFailure

PARTIAL_EXIT = 3


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="shared.heartbeat_run")
    p.add_argument("--job", required=True, help="stable job_health.job_name")
    p.add_argument("--interval", type=float, default=None,
                   help="expected cadence in hours")
    p.add_argument("--cwd", default=None,
                   help="working directory for the command")
    p.add_argument("cmd", nargs=argparse.REMAINDER,
                   help="command to run, after --")
    args = p.parse_args(argv)
    cmd = args.cmd[1:] if args.cmd[:1] == ["--"] else args.cmd
    if not cmd:
        p.error("no command given (put it after --)")

    rc = 0
    with JobHeartbeat(args.job, expected_interval=args.interval):
        rc = subprocess.call(cmd, cwd=args.cwd)
        if rc == PARTIAL_EXIT:
            raise PartialJobFailure(f"{cmd[-1]!s}: partial failure (exit {rc})")
        if rc != 0:
            raise RuntimeError(f"command exited {rc}: {' '.join(cmd)}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except RuntimeError as exc:
        # JobHeartbeat already recorded + alerted; keep the traceback out of
        # the cron log and preserve a non-zero exit for set -e callers.
        print(f"[heartbeat_run] {exc}", file=sys.stderr)
        sys.exit(1)
