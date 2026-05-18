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

## What bulk processing can use (and what it cannot)

Bulk analysis is **not** the chart-workspace agent. There is **no LLM tool-calling loop** — no `draw_on_chart`, `update_ticker_status`, `show_how_to`, RAG/news queries, or specialist personas. Each ticker gets **one** Ollama completion with a fixed system prompt and a pre-built JSON snapshot.

### Chart granularity (from the screenings Charts tab)

At submit time the UI snapshots:

| Job column | UI source |
|------------|-----------|
| `chart_granularity` | Chart picker bar size: `1hour` \| `4hour` \| `1day` \| `1week` |
| `chart_date_from` / `chart_date_to` | Chart picker date range when set (optional; worker uses FMP-default lookback per granularity when null) |

The worker passes these into `fetch.fetch_history` and `fetch.summarize_for_prompt` (`chart_granularity.py` defines SMA windows and bar counts per granularity).

| Granularity | FMP source | SMA windows (typical) | Prompt window |
|-------------|------------|----------------------|---------------|
| `1hour` | intraday 1h | 10 / 20 / 50 | ~120 bars |
| `4hour` | intraday 4h | 10 / 20 / 50 | ~100 bars |
| `1day` | daily | 20 / 50 / 200 | ~126 bars |
| `1week` | daily → weekly resample | 4 / 10 / 20 | ~52 bars |

### Per-ticker data (fetched before the LLM runs)

| Source | Module | What the model sees |
|--------|--------|---------------------|
| **FMP OHLCV** | `fetch.fetch_history` | Bars at the snapshotted granularity + optional date window. |
| **SMAs** | `fetch.py` | Windows depend on granularity (see table above). |
| **Range & volume stats** | `fetch.summarize_for_prompt` | Window high/low, recent vs prior volume ratio. |
| **Recent price shape** | same | Up to last 30 closes in the prompt window. |
| **User instruction** | job `user_prompt` | Optional text from the bulk panel (default: *"Run a technical analysis."*). |
| **Trading strategy** | `user_trading_strategy` | Loaded once per job for `user_id`; prepended to the system prompt (same injection as chart AI `withTradingStrategy`). |

Snapshot JSON includes `granularity`, `bar_label`, `last_date`, `last_close`, `range_window`, `smas`, `volume`, `last_closes`, `bars_total`.

### Per-ticker LLM output (strict JSON, no tools)

The model must return a single JSON object (see `prompt.py`). The worker parses it and writes:

| Field | Written to |
|-------|------------|
| `status` | `user_scan_row_notes.status` — one of `pipeline`, `watchlist`, `active`, `dismissed` (same semantics as chart AI `update_ticker_status`). |
| `comment` | `user_scan_row_notes.comment` — short table cell (max 400 chars). |
| `analysis_markdown` | `user_ticker_chart_workspace.ai_chat_messages` — synthetic user turn (`source: bulk_analysis`) + assistant turn with markdown (`**Trend:**`, `**SMAs:**`, `**Support:**`, `**Resistance:**`, `**Volume:**`, then summary). |
| `entry` (optional) | `user_scan_row_notes.metadata_json.entry` — `direction`, `price`, optional `take_profit` / `stop_loss`; chart bar anchored to snapshot `last_date` / last bar index. |

If FMP returns no candles, JSON is invalid, or the ticker times out, that symbol is counted as **failed** on the job; other tickers continue.

### Job scope (UI → worker)

| Control | Effect |
|---------|--------|
| **`scan_run_id`** | Ticker list comes from `user_scan_rows` for that run. |
| **`ticker_subset`** | When set at submit time, only those symbols are analysed (matches filtered view in the UI). |
| **`user_prompt`** | Same prompt applied to every ticker in scope. |
| **`chart_granularity`** | Bar size from the Charts tab (`1hour` / `4hour` / `1day` / `1week`). |
| **`chart_date_from` / `chart_date_to`** | Optional custom range from the chart picker. |

### vs interactive chart AI (`/api/ai/chart`)

| Capability | Bulk worker | Chart chat |
|------------|-------------|------------|
| Saved trading strategy (`user_trading_strategy`) | Yes — `prompt.build_system()` | Yes — `withTradingStrategy()` |
| FMP OHLCV + SMA snapshot | Yes (batch, at job granularity) | Yes (full OHLC passed to orchestrator) |
| News / sentiment / fundamentals / risk personas | No | Yes (parallel persona calls) |
| Draw annotations on chart | No | Yes (`draw_on_chart`) |
| Platform how-to tours | No | Yes (`show_how_to`) |
| Live status update tool | No (writes note directly from JSON) | Yes (`update_ticker_status`) |
| Streaming / multi-turn chat | No (one shot per ticker) | Yes |

---

## Key files

| File | Role |
|---|---|
| `cli.py` | Entry point. `tick` (cron) and `run <job-id>` (one job). |
| `scheduler.py` | Tick logic: cleanup, dispatch, concurrency gate. |
| `worker.py` | Per-job runner: loads tickers, fans out per-ticker Ollama calls, persists results. |
| `fetch.py` | FMP OHLC at job granularity + locally computed SMAs. |
| `chart_granularity.py` | Granularity config (SMA windows, lookback, prompt bar counts). |
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
| `BULK_ANALYSIS_SUMMARY_TIMEOUT` | `90` | Timeout (seconds) for the post-run All-tickers summary LLM call. |
| `FMP_API_KEY` | required | For OHLCV + SMA fetches. |

---

## DB tables touched

- `user_bulk_analysis_jobs` — the work queue. Status lifecycle: `queued → running → done | error`. Progress counters track ticker-level state. `bulk_chat_messages` stores the **All tickers** tab thread (user prompt at queue time + assistant run summary when finished).
- `user_scan_rows` — read source for the ticker list (joined via the linked scan run).
- `user_ticker_chart_workspace.ai_chat_messages` — write target. The worker appends a synthetic assistant chat turn so the analysis renders inline in the user's chart workspace.
- `user_scan_row_notes` — write target for `status` (`pipeline` / `watchlist` / `active` / `dismissed`), `comment`, and optional `metadata_json.entry` for chart entry markers.

---

## Why this exists

UI users wanted to "analyze every ticker in this scan run" without clicking each row. A bulk job is one DB insert; the worker fans out and writes results back into the same chat workspaces the user already uses, so the experience is identical to running each analysis manually — just batched and run on the Mac Mini overnight.
