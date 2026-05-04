#!/usr/bin/env bash
# run_bulk_analysis_tick.sh — shell wrapper for Mac Mini cron.
#
# Picks up queued user_bulk_analysis_jobs rows and dispatches one subprocess
# per job (services.bulk_analysis.worker). Per-ticker concurrency is capped
# inside each worker (asyncio.Semaphore).
#
# Add to crontab (crontab -e):
#   * * * * *  /path/to/swingtrader/code/analytics/scripts/run_bulk_analysis_tick.sh >> /path/to/logs/bulk_analysis_tick.log 2>&1
#
# Tunables (set in code/analytics/.env):
#   BULK_ANALYSIS_MAX_CONCURRENT — concurrent jobs (default 1)
#   BULK_ANALYSIS_CONCURRENCY    — concurrent tickers per job (default 2)
#   BULK_ANALYSIS_TIMEOUT        — per-ticker Ollama timeout in seconds (default 90)
#   BULK_ANALYSIS_MODEL          — override the Ollama model (optional)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ANALYTICS_DIR="$(dirname "$SCRIPT_DIR")"
VENV_PYTHON="${ANALYTICS_DIR}/.venv/bin/python"

if [[ ! -f "$VENV_PYTHON" ]]; then
  VENV_PYTHON="python3"
fi

cd "$ANALYTICS_DIR"

"$VENV_PYTHON" -m services.bulk_analysis.cli tick
