#!/usr/bin/env bash
# run_public_bulk_analysis_tick.sh — shell wrapper for system crontab.
#
# Picks up public_screening_results rows with bulk_analysis_status='queued'
# and dispatches one subprocess per row (services.public_screening_bulk_analytics.worker).
# Per-ticker concurrency is capped inside each worker (asyncio.Semaphore).
#
# Same logic as the OpenClaw job public-bulk-analysis-tick — register one
# OR the other, never both, to avoid double-dispatching.
#
# Add to crontab (crontab -e), every minute:
#   * * * * *  /path/to/swingtrader/code/analytics/scripts/run_public_bulk_analysis_tick.sh >> /path/to/logs/public_bulk_analysis_tick.log 2>&1
#
# Use the real absolute path to this repo (not ~ unless your cron supports it).
#
# Tunables (set in code/analytics/.env):
#   PUBLIC_BULK_ANALYSIS_MAX_CONCURRENT          — concurrent passes (default 1)
#   PUBLIC_BULK_ANALYSIS_CONCURRENCY             — concurrent tickers per pass (default 2)
#   PUBLIC_BULK_ANALYSIS_TIMEOUT                 — per-ticker LLM timeout in seconds (default 90)
#   PUBLIC_BULK_ANALYSIS_BACKEND                 — ollama | anthropic | do_agent (default ollama)
#   PUBLIC_BULK_ANALYSIS_MODEL                   — override the model name (optional)
#   PUBLIC_BULK_ANALYSIS_STUCK_TIMEOUT_MINUTES   — stuck running → error (default 60)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ANALYTICS_DIR="$(dirname "$SCRIPT_DIR")"
VENV_PYTHON="${ANALYTICS_DIR}/.venv/bin/python"

if [[ ! -f "$VENV_PYTHON" ]]; then
  VENV_PYTHON="python3"
fi

cd "$ANALYTICS_DIR"

"$VENV_PYTHON" -m services.public_screening_bulk_analytics.cli tick
