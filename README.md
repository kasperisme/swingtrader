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

| Job | Frequency | Purpose |
|-----|-----------|---------|
| FMP data pull | Periodic | Fetches price, fundamental, and technical data from Financial Modeling Prep (FMP) and writes to Supabase |
| News scoring | Every hour | Ingests news articles, scores them for market impact with **Ollama** (local LLM on the Mac Mini), and stores results in Supabase |
| Daily Narrative | 08:30 ET weekdays | Queries portfolio positions + active screening candidates, cross-references with overnight news, synthesises a personalised pre-market briefing via Ollama, saves to `daily_narratives`, optionally delivers by email |

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

## Local Development

- UI: `cd code/ui && npm run dev`
- Analytics/scripting: `cd code/analytics && python -m ...`
