#!/usr/bin/env bash
# process_telegram_updates.sh — shell wrapper for Mac Mini polling loop
#
# Example cron (every minute):
# * * * * * /path/to/swingtrader/code/analytics/scripts/process_telegram_updates.sh >> /path/to/logs/telegram_updates.log 2>&1

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ANALYTICS_DIR="$(dirname "$SCRIPT_DIR")"
VENV_PYTHON="${ANALYTICS_DIR}/.venv/bin/python"

if [[ ! -f "$VENV_PYTHON" ]]; then
  VENV_PYTHON="python3"
fi

cd "$ANALYTICS_DIR"
"$VENV_PYTHON" -m scripts.process_telegram_updates --once
