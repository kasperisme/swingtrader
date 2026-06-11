#!/usr/bin/env bash
# run_briefings_tick.sh — shell wrapper for the macOS crontab (Mac Mini).
#
# Drives the free news-briefing service:
#   * immediate sends for brand-new signups (within ~1 min), and
#   * the daily fan-out at 08:30 America/New_York (1h before the open).
# Sends are claim-guarded, so overlapping every-minute ticks parallelise the
# morning fan-out safely instead of double-sending.
#
# Add to crontab (crontab -e), every minute:
#   * * * * *  /Users/kasperisme/projects/swingtrader/code/analytics/scripts/run_briefings_tick.sh >> /Users/kasperisme/projects/swingtrader/logs/briefings.log 2>&1
#
# Use the real absolute path to this repo (not ~ unless your cron supports it).
#
# Env: loaded from code/analytics/.env by the Python entrypoint. Tunables:
#   BRIEFING_MAX_PER_TICK — sends attempted per tick (default 25)
#   BRIEFING_DAILY_CRON   — daily fire (default "30 8 * * 1-5")
#   BRIEFING_TZ           — schedule timezone (default America/New_York)
#   OLLAMA_BRIEFING_MODEL — narrative model (falls back to OLLAMA_IMPACT_MODEL)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ANALYTICS_DIR="$(dirname "$SCRIPT_DIR")"
VENV_PYTHON="${ANALYTICS_DIR}/.venv/bin/python"

if [[ ! -f "$VENV_PYTHON" ]]; then
  VENV_PYTHON="python3"
fi

cd "$ANALYTICS_DIR"

"$VENV_PYTHON" -m services.briefings.cli tick
