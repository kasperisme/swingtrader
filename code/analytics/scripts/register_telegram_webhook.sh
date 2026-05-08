#!/usr/bin/env bash
set -euo pipefail

WEBHOOK_URL="https://www.newsimpactscreener.com/api/telegram-webhook"

if [[ -z "${TELEGRAM_BOT_TOKEN:-}" ]]; then
  echo "TELEGRAM_BOT_TOKEN is not set." >&2
  exit 1
fi

if [[ -z "${TELEGRAM_WEBHOOK_SECRET:-}" ]]; then
  echo "TELEGRAM_WEBHOOK_SECRET is not set." >&2
  exit 1
fi

if [[ -n "${TELEGRAM_WEBHOOK_SECRET:-}" ]]; then
  curl -sS "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/setWebhook" \
    -H "Content-Type: application/json" \
    -d "{
      \"url\": \"${WEBHOOK_URL}\",
      \"secret_token\": \"${TELEGRAM_WEBHOOK_SECRET}\"
    }"
else
  curl -sS "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/setWebhook" \
    -H "Content-Type: application/json" \
    -d "{
      \"url\": \"${WEBHOOK_URL}\"
    }"
fi
