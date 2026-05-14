#!/usr/bin/env bash
# run_public_screenings_tick.sh — shell wrapper for system crontab.
#
# Queues due public_screenings and dispatches public_screening_results jobs
# (same logic as OpenClaw job public-screening-tick).
#
# Add to crontab (crontab -e), every minute:
#   * * * * *  /path/to/swingtrader/code/analytics/scripts/run_public_screenings_tick.sh >> /path/to/logs/public_screenings_tick.log 2>&1
#
# Use the real absolute path to this repo (not ~ unless your cron supports it).
#
# Env: load code/analytics/.env automatically via the Python entrypoint.
# Tunables in .env:
#   PUBLIC_SCREENING_MAX_CONCURRENT — parallel public runs (falls back to SCREENING_MAX_CONCURRENT)
#   SCREENING_MAX_CONCURRENT        — fallback default 1
#   SCREENING_STUCK_TIMEOUT_MINUTES — stuck running → error (default 20)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ANALYTICS_DIR="$(dirname "$SCRIPT_DIR")"
VENV_PYTHON="${ANALYTICS_DIR}/.venv/bin/python"

if [[ ! -f "$VENV_PYTHON" ]]; then
  VENV_PYTHON="python3"
fi

cd "$ANALYTICS_DIR"

"$VENV_PYTHON" -m services.public_screenings.cli tick
