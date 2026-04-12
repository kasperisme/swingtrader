#!/usr/bin/env bash
# run_daily_narrative.sh — shell wrapper for Mac Mini cron
# Requires: TELEGRAM_BOT_TOKEN in .env and telegram_chat_id set per user in DB
#
# Add to crontab (crontab -e):
#   30 12 * * 1-5  /path/to/swingtrader/code/analytics/scripts/run_daily_narrative.sh >> /path/to/logs/narrative.log 2>&1
#
# 12:30 UTC = 08:30 US Eastern (EST). Adjust to 11:30 UTC during EDT (summer).
# A smarter approach: use launchd on macOS and set it via TZ=America/New_York.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ANALYTICS_DIR="$(dirname "$SCRIPT_DIR")"
VENV_PYTHON="${ANALYTICS_DIR}/.venv/bin/python"

# Fall back to system python if venv not found
if [[ ! -f "$VENV_PYTHON" ]]; then
  VENV_PYTHON="python3"
fi

cd "$ANALYTICS_DIR"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting daily narrative generation"

"$VENV_PYTHON" -m scripts.run_daily_narrative --deliver

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Daily narrative complete"
