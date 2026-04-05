"""
Run a screening script to completion and update scan_jobs in Supabase (finish_scan_job).

Invoked by the MCP server as:
  python -m swingtrader_mcp.job_runner <job_id> <script_rel> [script_args...]

Do not run directly unless debugging.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_db():
    path = _REPO_ROOT / "src" / "db.py"
    spec = importlib.util.spec_from_file_location("swingtrader_db", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> None:
    if len(sys.argv) < 3:
        print("usage: python -m swingtrader_mcp.job_runner <job_id> <script_rel> [args...]", file=sys.stderr)
        sys.exit(2)

    job_id = int(sys.argv[1])
    script_rel = sys.argv[2]
    script_args = sys.argv[3:]

    db = _load_db()
    script_path = _REPO_ROOT / script_rel
    if not script_path.is_file():
        db.finish_scan_job(job_id, 1, error_message=f"script not found: {script_path}")
        sys.exit(1)

    env = os.environ.copy()
    env.setdefault("PYTHONUNBUFFERED", "1")
    env["SWINGTRADER_JOB_ID"] = str(job_id)

    proc = subprocess.run(
        [sys.executable, str(script_path)] + script_args,
        cwd=str(_REPO_ROOT),
        env=env,
    )
    err = None
    if proc.returncode != 0:
        err = f"process exited with code {proc.returncode}"
    db.finish_scan_job(job_id, proc.returncode, error_message=err)
    sys.exit(proc.returncode)


if __name__ == "__main__":
    main()
