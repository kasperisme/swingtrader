# Swingtrader

A swing trading research and analysis platform combining news sentiment scoring, technical screening, and AI-driven insights.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                        Mac Mini                             │
│                  (Data Orchestrator)                        │
│                                                             │
│  ┌──────────────────┐    ┌──────────────────────────────┐  │
│  │   FMP Fetcher    │    │    News Ingester / Scorer    │  │
│  │  (periodic pull) │    │   (runs every hour via cron) │  │
│  └────────┬─────────┘    └───────────┬────────────────────┘  │
│           │                          │                        │
│           │              ┌───────────▼───────────┐            │
│           │              │ Ollama (local LLM)    │            │
│           │              │ — article analysis    │            │
│           │              └───────────┬───────────┘            │
│           │                          │                        │
└───────────┼─────────────────────────────┼───────────────────┘
            │                          │
            ▼                          ▼
┌─────────────────────────────────────────────────────────────┐
│                        Supabase                             │
│               (Backend / Data Layer / Postgres)             │
│                                                             │
│   - Ticker data & fundamentals (from FMP)                   │
│   - Screenings & technical scores                           │
│   - News articles & impact scores                           │
│   - User auth & profiles                                    │
└───────────────────────────────┬─────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────┐
│                   Vercel / Next.js UI                       │
│              (code/ui — App Router, TypeScript)             │
│                                                             │
│   - Protected dashboard (screenings, articles, watchlists)  │
│   - Public blog & docs                                      │
│   - API routes (code/ui/app/api)                            │
│   - Sanity Studio (content management)                      │
└─────────────────────────────────────────────────────────────┘
```

## Components

### Mac Mini — Data Orchestrator (`code/analytics/`)

Runs two main periodic jobs:

| Job             | Frequency                   | Purpose                                                                                                                                                                                                        |
| --------------- | --------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| FMP data pull   | Periodic                    | Fetches price, fundamental, and technical data from Financial Modeling Prep (FMP) and writes to Supabase                                                                                                       |
| News scoring    | Every hour                  | Ingests news articles, scores them for market impact with **Ollama** (local LLM on the Mac Mini), and stores results in Supabase                                                                               |
| Daily Narrative | 08:30 ET weekdays (crontab) | Queries portfolio positions + active screening candidates, cross-references with overnight news, synthesises a personalised pre-market briefing via Ollama, saves to `daily_narratives`, delivers via Telegram |

Key modules:

- `src/fmp.py` — FMP API client
- `news_impact/news_ingester.py` — Article ingestion pipeline
- `news_impact/impact_scorer.py` — AI-based news scoring
- `news_impact/score_news_cli.py` — CLI entrypoint for the hourly news job
- `scripts/run_screener.py` — Screening runner
- `news_impact/narrative_generator.py` — Daily Narrative synthesis (Ollama)
- `scripts/run_daily_narrative.py` — CLI/cron entry point for the daily narrative
- `scripts/run_daily_narrative.sh` — Shell wrapper for cron

### Supabase — Backend / Data Layer

Postgres-backed BaaS providing:

- Database (tickers, screenings, articles, news scores)
- Auth (user sessions)
- Row-level security

### Vercel / Next.js — UI (`code/ui/`)

Next.js App Router application with:

- `/protected` — authenticated dashboard (screenings, news, watchlists)
- `/app/api` — API routes consumed by the dashboard
- `/blog`, `/docs` — public-facing content
- `/studio` — Sanity Studio for content management

Content (blog posts, docs) is managed via **Sanity** (project: `newsimpactscreener`, ID: `y2lg8a3c`).

## Data Sources

- **FMP (Financial Modeling Prep)** — price data, fundamentals, technical indicators
- **News feeds** — ingested and scored hourly by the Mac Mini job
- **Federal Reserve (H.6)** — money supply data

## Scheduling (Mac Mini crontab)

All periodic jobs run via crontab on the Mac Mini. To edit:

```bash
crontab -e
```

Current schedule:

```
# News scoring — every hour
0 * * * *    /path/to/analytics/scripts/run_score_news.sh >> /path/to/logs/news.log 2>&1

# Daily Narrative — 08:30 ET weekdays (12:30 UTC = EST; change to 11:30 UTC in summer EDT)
30 12 * * 1-5  /path/to/analytics/scripts/run_daily_narrative.sh >> /path/to/logs/narrative.log 2>&1

```

Make the log directory if it doesn't exist:

```bash
mkdir -p /path/to/swingtrader/logs
```

> **DST note:** crontab runs in UTC. EST = UTC-5 (use `30 12`), EDT = UTC-4 (use `30 11`). Adjust manually twice a year or migrate to launchd with `TZ=America/New_York`.

## Telegram Setup (Daily Narrative delivery)

### One-time bot creation

1. Message [@BotFather](https://t.me/BotFather) → `/newbot` → copy the token and username
2. Add to Vercel environment variables (and `code/analytics/.env` for the Mac Mini sender):
   ```
   TELEGRAM_BOT_TOKEN=123456789:AAF...
   TELEGRAM_BOT_USERNAME=YourBotName    # without @, used to build the deep link
   TELEGRAM_WEBHOOK_SECRET=any-random-string-you-choose
   ```

### Register the webhook (run once after deploying to Vercel)

```bash
curl "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/setWebhook" \
  -d "url=https://www.newsimpactscreener.com/api/telegram-webhook" \
  -d "secret_token=${TELEGRAM_WEBHOOK_SECRET}" \
  -d "allowed_updates=[\"message\"]"
```

No bot process needed on the Mac Mini — Telegram pushes updates directly to Vercel.

### Register bot command options

```bash
cd code/analytics
chmod +x scripts/register_telegram_commands.sh
./scripts/register_telegram_commands.sh
```

This registers `/start`, `/update`, `/search`, and `/health` in the Telegram command menu for private chats.

### User connection flow

Each user connects their own Telegram account via the UI:

1. Go to `/protected/daily-narrative` in the app
2. Click **Connect Telegram** — a one-time deep link is generated (expires in 15 min)
3. Tap the link → Telegram opens → press **START**
4. Telegram POSTs the update to `/api/user/telegram/webhook` on Vercel
5. The webhook looks up the token, saves the user's personal `chat_id`, sends a confirmation
6. The UI detects connection and updates automatically

Messages are always sent to the individual user's personal chat — never to a group or channel.

## Local Development

- UI: `cd code/ui && npm run dev`
- Analytics/scripting: `cd code/analytics && python -m ...`
- Test narrative generation: `cd code/analytics && .venv/bin/python -m scripts.run_daily_narrative --user-id <uuid> --deliver`
