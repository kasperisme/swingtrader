#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${TELEGRAM_BOT_TOKEN:-}" ]]; then
  echo "TELEGRAM_BOT_TOKEN is not set."
  echo "Export it first, then run this script again."
  exit 1
fi

echo "Registering Telegram bot commands for private chats..."
curl -sS "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/setMyCommands" \
  -H "Content-Type: application/json" \
  -d '{
    "scope": { "type": "all_private_chats" },
    "commands": [
      { "command": "start", "description": "Connect your SwingTrader account" },
      { "command": "update", "description": "Get a personalized news update now" },
      { "command": "search", "description": "Search latest news by keyword" },
      { "command": "health", "description": "Show pipeline and job health status" }
    ]
  }'

echo ""
echo "Current command list:"
curl -sS "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getMyCommands"
echo ""
