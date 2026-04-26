#!/usr/bin/env bash
# swingtrader_status.sh — Quick health check for all pipelines
# Usage: ./scripts/swingtrader_status.sh

set -euo pipefail

LOGS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)/logs"

echo "╔═══════════════════════════════════════════════════════════╗"
echo "║           SwingTrader Pipeline Status                     ║"
echo "╚═══════════════════════════════════════════════════════════╝"
echo ""

# Colors (if terminal supports it)
if [[ -t 1 ]]; then
    RED='\033[0;31m'
    GREEN='\033[0;32m'
    YELLOW='\033[1;33m'
    NC='\033[0m' # No Color
else
    RED=''
    GREEN=''
    YELLOW=''
    NC=''
fi

# Check watchdog for alerts
if [[ -f "$LOGS_DIR/watchdog.log" ]]; then
    last_watchdog=$(tail -5 "$LOGS_DIR/watchdog.log" | grep -c "alert(s)" || true)
    if [[ "$last_watchdog" -gt 0 ]]; then
        echo -e "${RED}⚠️  WATCHDOG: ALERTS DETECTED${NC}"
        tail -30 "$LOGS_DIR/watchdog.log" | grep -E "^202|→" | tail -15
    else
        echo -e "${GREEN}✓ Watchdog: No alerts${NC}"
    fi
else
    echo "⚠️  No watchdog log found"
fi

echo ""
echo "--- Recent Pipeline Activity ---"
echo ""

# Check each log file
check_log() {
    local label=$1
    local filepath=$2
    
    if [[ ! -f "$filepath" ]]; then
        echo -e "${YELLOW}$label: no log found${NC}"
        return
    fi
    
    local last_line
    last_line=$(tail -1 "$filepath" 2>/dev/null || echo "empty")
    
    # Check for errors in last 50 lines
    local errors
    errors=$(tail -50 "$filepath" 2>/dev/null | grep -ciE "ERROR|CRITICAL|FAILED|Traceback" || true)
    
    if [[ "$errors" -gt 0 ]]; then
        echo -e "${RED}$label: $errors errors recently${NC}"
    else
        echo -e "${GREEN}$label: OK${NC}"
    fi
}

check_log "news_ingest"    "$LOGS_DIR/swingtrader-news.log"
check_log "embeddings"      "$LOGS_DIR/embeddings.log"
check_log "blog_post"       "$LOGS_DIR/generate_blog_post.log"
check_log "narrative"       "$LOGS_DIR/narrative.log"
check_log "telegram"        "$LOGS_DIR/telegram_updates.log"

echo ""
echo "Run './scripts/watchdog' for full health check"