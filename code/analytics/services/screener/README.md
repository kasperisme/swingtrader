# Full-Market Screener

Full-market scan over NYSE + NASDAQ using the Minervini trend template. Pulls fundamentals + technicals from FMP, runs them through a series of trend-template filters, and uploads the qualifying tickers (plus a market-wide regime read) to the screenings API.

This service is **independent of the news pipeline**. It produces `scan_jobs` rows that other services (the screening agent, bulk analysis worker, podcast research agent) consume — but the scan itself doesn't touch news data.

---

## Architecture

```
python -m services.screener.engine.run
        │
        ▼
fmp.py                  ← API wrapper for FMP (quotes, fundamentals, technicals)
        │
        ▼
fundamentals.py         ← screen on EPS growth, ROE, debt, sales acceleration
        │
        ▼
technical.py            ← Minervini trend template:
                         - price > 50 SMA > 150 SMA > 200 SMA
                         - 200 SMA trending up ≥ 1 month
                         - price within 25% of 52w high
                         - RS rank ≥ 70
        │
        ▼
engine.py               ← orchestrates the run, computes market-wide regime,
                         emits progress to scan_jobs throughout
        │
        ▼
api_client.py           ← upload qualifying rows + market_json regime
                         POST → newsimpactscreener.com/api/v1/screenings
```

---

## Job lifecycle

Two ways to launch:

### 1. Via the MCP `job_runner` (recommended)

Job_runner sets `SWINGTRADER_JOB_ID` in the environment and manages the `scan_jobs` row's `pid`, status transitions, and exit code. The engine just emits progress.

### 2. Direct invocation

```bash
python -m services.screener.engine
```

The engine creates its own `scan_jobs` row so the run still appears in Supabase. Progress and exit code are persisted so the UI can surface live status.

---

## Key files

| File | Role |
|---|---|
| `engine.py` | Orchestrates the scan. Pulls eligible tickers, runs fundamentals + technical filters, computes market regime, uploads results. |
| `fmp.py` | Thin FMP REST client (`requests` + pandas). Quotes, statements, technical indicators. |
| `fundamentals.py` | Fundamentals screen (earnings growth, ROE, debt levels, sales acceleration). |
| `technical.py` | Trend-template screen (multi-SMA stack, RS rank, distance from 52w high). |
| `api_client.py` | Posts qualifying rows + market regime to the swingtrader screenings HTTP API. |

---

## Outputs

The scan produces three things, persisted in different places:

1. **`scan_jobs` row** (Supabase) — job lifecycle: status, progress %, exit code, error string. Updated throughout the run so the UI can show live status.
2. **Screening rows** — uploaded via the swingtrader API to `user_scan_runs.row_data` (one row per qualifying ticker, with the technical + fundamental columns the UI displays).
3. **Market regime** — `market_json` blob (regime status, days_in_regime, breadth %s above 50/200 SMA) attached to the scan run. Consumed by the podcast research agent and any other "what is the tape doing" caller.

---

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `APIKEY` | required | FMP API key (note: this service uses `APIKEY`, not `FMP_API_KEY` — historical). |
| `SWINGTRADER_JOB_ID` | unset | When set (by job_runner), engine attaches to the existing job row instead of creating a new one. |
| `SWINGTRADER_API_BASE_URL` | `https://www.newsimpactscreener.com` | Origin for the screenings HTTP API. |
| `SWINGTRADER_API_KEY` | required | Bearer token for the screenings API. Must include `screenings:write` scope. |

---

## Why this lives outside `news/`

The screener is fundamentals + price-action only. It doesn't read or write news data. Other services (especially the screening agent) often *consume* a screener run as a starting point — "screen for trend-template eligible names, then evaluate their news exposure" — but those joins happen in the consumer, not here.

Keeping it independent means scans can run on a schedule even if the news pipeline is down, and the news pipeline doesn't need to wait for FMP technicals.

---

## Running on a schedule

The Mac Mini's crontab triggers the scan at market open and close. The MCP job_runner manages the lifecycle; the engine just runs. See the analytics top-level [`README.md`](../../README.md) → **Scheduled Jobs** for the cron entries.
