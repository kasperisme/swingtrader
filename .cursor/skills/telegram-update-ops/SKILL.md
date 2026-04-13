---
name: telegram-update-ops
description: Operates and troubleshoots Swingtrader Telegram updates, including Bot API command registration, webhook checks, `/update` queue flow, and Mac worker processing. Use when working on Telegram bot commands, `/update` delivery, webhook issues, or queued Telegram update jobs in this project.
---

# Telegram Update Ops (Swingtrader)

Use this skill for Telegram bot work in this repo, especially `/update`.

## Project-specific architecture

- **Webhook endpoint:** `code/ui/app/api/telegram-webhook/route.ts`
- **Queue table:** `swingtrader.telegram_update_requests`
- **Daily narrative generator:** `code/analytics/news_impact/narrative_generator.py`
- **Telegram worker:** `code/analytics/scripts/process_telegram_updates.py`
- **Cron wrapper:** `code/analytics/scripts/process_telegram_updates.sh`
- **Delivery formatter/sender helpers:** `code/analytics/scripts/run_daily_narrative.py`

Expected flow:
1. User sends `/update` in Telegram.
2. Webhook validates/links user and inserts `pending` row in `telegram_update_requests`.
3. Mac worker claims row (`processing`), generates narrative, sends Telegram message.
4. Worker updates row to `completed` or `failed`.

## Telegram Bot API essentials (official behavior)

- `setMyCommands`: register visible slash commands in chat command menu.
- `getMyCommands`: verify currently active commands.
- `deleteMyCommands`: clear command list for a scope/language.
- `setWebhook`: configure webhook URL and optional `secret_token`.
- `getWebhookInfo`: inspect webhook health (`url`, pending count, last error).
- `drop_pending_updates` can be used when resetting webhook to discard stale backlog.
- `allowed_updates` limits delivered update types.
- For webhook authenticity checks, Telegram sends `X-Telegram-Bot-Api-Secret-Token` when `secret_token` is set.
- Command visibility can be scoped (`default`, `all_private_chats`, chat-specific scopes, etc.).

## Standard operations

### 1) Ensure commands appear in Telegram chat

Register commands (recommended for private chats):

```bash
curl -s "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/setMyCommands" \
  -H "Content-Type: application/json" \
  -d '{
    "scope": { "type": "all_private_chats" },
    "commands": [
      { "command": "start", "description": "Connect your NewsImpactScreener account" },
      { "command": "update", "description": "Get a personalised news update now" }
    ]
  }'
```

Verify:

```bash
curl -s "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getMyCommands"
```

### 2) Verify webhook configuration

```bash
curl -s "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getWebhookInfo"
```

Check:
- `url` matches deployed `/api/telegram-webhook`.
- `pending_update_count` is not growing without processing.
- `last_error_message` is empty.

### 3) Validate queue state in Supabase

Inspect recent `/update` requests:

```sql
select id, user_id, status, requested_at, started_at, completed_at, error_text
from swingtrader.telegram_update_requests
order by requested_at desc
limit 50;
```

Healthy pattern: `pending -> processing -> completed`.

### 4) Run worker manually on Mac

Single cycle:

```bash
cd code/analytics
./scripts/process_telegram_updates.sh
```

Continuous loop (for low latency):

```bash
cd code/analytics
python -m scripts.process_telegram_updates
```

### 5) Recommended schedule

For cron with one-shot worker:

```cron
* * * * * /Users/kkr/projects/swingtrader/code/analytics/scripts/process_telegram_updates.sh >> /Users/kkr/projects/swingtrader/code/analytics/logs/telegram_updates.log 2>&1
```

## Troubleshooting checklist

- Command not visible in chat:
  - Re-run `setMyCommands` for correct scope (`all_private_chats`).
  - Confirm the user opened a private chat with the bot.
- Webhook receives nothing:
  - Check `getWebhookInfo` for URL/errors.
  - Verify webhook secret handling matches `X-Telegram-Bot-Api-Secret-Token`.
- `/update` acknowledged but no final message:
  - Check queue rows for `failed` and `error_text`.
  - Run worker once manually and inspect logs.
  - Confirm `TELEGRAM_BOT_TOKEN` is set on Mac worker env.
- Wrong tickers in narrative sections:
  - Re-check `narrative_generator.py` post-processing guards and latest-run screening logic.
  - Validate user positions in `swingtrader.user_trades`.

## Guardrails

- Never expose bot token in responses or committed files.
- Do not commit `.env` or credentials.
- Prefer DB-backed verification (`telegram_update_requests`, `daily_narratives`, `telegram_message_log`) over assumptions.
