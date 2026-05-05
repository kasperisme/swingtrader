# Bulk Analysis Worker

Per-ticker technical-analysis worker. The UI inserts a job into `user_bulk_analysis_jobs`; a cron tick picks it up and runs an Ollama pass per ticker, writing the analysis straight into the chart workspace's chat history so users see the result inline.

---

## Architecture

```
UI: insert row → user_bulk_analysis_jobs (status='queued')
                                │
                                ▼
crontab (every minute)
  └─ scripts/run_bulk_analysis_tick.sh
       └─ python -m services.bulk_analysis.cli tick
            ├─ scheduler.run_tick:
            │    ├─ flip stuck 'running' rows older than STUCK_TIMEOUT → 'error'
            │    ├─ count current 'running' jobs vs MAX_CONCURRENT
            │    └─ for each newly-claimed 'queued' row:
            │         flip to 'running', spawn subprocess
            │              └─ python -m services.bulk_analysis.cli run <job-id>
            │                   └─ worker.run_job:
            │                        ├─ load tickers from user_scan_rows
            │                        ├─ fetch.py: 6mo OHLCV + SMAs (FMP)
            │                        ├─ Ollama pass per ticker (asyncio.Semaphore)
            │                        ├─ append synthetic chat turn →
            │                        │     user_ticker_chart_workspace.ai_chat_messages
            │                        ├─ upsert user_scan_row_notes.status + comment
            │                        └─ refresh job progress counters
```

Mirrors the `services/agent/scheduler.py` shape: one cron entry, dispatch subprocesses up to a concurrency cap. Per-ticker concurrency is bounded *inside* the worker via `asyncio.Semaphore`, so the scheduler-level cap can stay low (default `MAX_CONCURRENT=1`).

---

## Key files

| File | Role |
|---|---|
| `cli.py` | Entry point. `tick` (cron) and `run <job-id>` (one job). |
| `scheduler.py` | Tick logic: cleanup, dispatch, concurrency gate. |
| `worker.py` | Per-job runner: loads tickers, fans out per-ticker Ollama calls, persists results. |
| `fetch.py` | FMP daily candles + locally computed SMA (20/50/200) windows. |
| `prompt.py` | Single-pass technical-analysis prompt → strict JSON `{status, comment, analysis_markdown}`. |

---

## CLI

```bash
# Cron tick (one iteration). Called every minute by run_bulk_analysis_tick.sh.
python -m services.bulk_analysis.cli tick [--max-concurrent N]

# Run a single specific job (mostly for debugging).
python -m services.bulk_analysis.cli run <job-uuid>
```

---

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `BULK_ANALYSIS_MAX_CONCURRENT` | `1` | Scheduler-level cap on concurrent jobs (each job is its own subprocess). |
| `BULK_ANALYSIS_CONCURRENCY` | `2` | Per-job cap on concurrent ticker analyses (asyncio.Semaphore inside the worker). |
| `BULK_ANALYSIS_TIMEOUT` | `90` | Per-ticker LLM timeout in seconds. |
| `BULK_ANALYSIS_STUCK_TIMEOUT_MINUTES` | `60` | A `running` job older than this is flagged as crashed and flipped to `error`. |
| `BULK_ANALYSIS_MODEL` | unset | Override the LLM model. Falls back to backend default when unset. |
| `FMP_API_KEY` | required | For OHLCV + SMA fetches. |

---

## DB tables touched

- `user_bulk_analysis_jobs` — the work queue. Status lifecycle: `queued → running → done | error`. Progress counters track ticker-level state.
- `user_scan_rows` — read source for the ticker list (joined via the linked scan run).
- `user_ticker_chart_workspace.ai_chat_messages` — write target. The worker appends a synthetic assistant chat turn so the analysis renders inline in the user's chart workspace.
- `user_scan_row_notes` — write target for `status` (`bullish`/`bearish`/`neutral`) and `comment` columns surfaced on the row in the screenings list.

---

## Why this exists

UI users wanted to "analyze every ticker in this scan run" without clicking each row. A bulk job is one DB insert; the worker fans out and writes results back into the same chat workspaces the user already uses, so the experience is identical to running each analysis manually — just batched and run on the Mac Mini overnight.
