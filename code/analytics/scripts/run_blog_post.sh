#!/usr/bin/env bash
# run_blog_post.sh — wrapper for generate_blog_post.py used by launchd.
# Usage: run_blog_post.sh [pre-market|intra-market]

set -euo pipefail

ANALYTICS_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="$ANALYTICS_DIR/output/blog_post_logs"
mkdir -p "$LOG_DIR"

MODE="${1:-pre-market}"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/${MODE}_${TIMESTAMP}.log"

# Skip weekends (launchd StartCalendarInterval doesn't support weekday arrays)
DOW="$(date +%u)"  # 1=Mon ... 7=Sun
if [ "$DOW" -ge 6 ]; then
    echo "[$TIMESTAMP] Weekend — skipping." | tee -a "$LOG_FILE"
    exit 0
fi

echo "[$TIMESTAMP] Starting blog post: $MODE" | tee -a "$LOG_FILE"

# Use venv Python if present, otherwise fall back to system python3
if [ -f "$ANALYTICS_DIR/.venv/bin/python3" ]; then
    PYTHON="$ANALYTICS_DIR/.venv/bin/python3"
else
    PYTHON="python3"
fi

cd "$ANALYTICS_DIR"

"$PYTHON" scripts/generate_blog_post.py --mode "$MODE" 2>&1 | tee -a "$LOG_FILE"

echo "[$(date +%Y%m%d_%H%M%S)] Done." | tee -a "$LOG_FILE"
