# Market screenings

Admin-defined, **script-backed** screenings that run on a shared schedule, persist one **global** result per run, optionally enrich each ticker with an **LLM analysis pass** (notes + entry levels), and **fan out** copies to every subscribed user (their `user_scan_*` tables plus optional Telegram). They complement **private** screenings (`user_scheduled_screenings` + LLM agent in `services/agent/`): public runs are deterministic Python in this package, not the tool-calling agent.

When a screening row has `llm_prompt` set, fan-out is **deferred** until the bulk-analytics worker has enriched the per-ticker rows — subscribers only get notified once both the screening and the analysis are visible in `/protected/screenings`.

---

## Architecture

```
OpenClaw cron: market-screening-tick  (every minute, UTC)
        │
        ▼
services.market_screenings.cli tick [--max-concurrent N]
        │
        ▼
scheduler.run_tick
        │
        ├─ Phase 1: _queue_due_market_screenings
        │     inserts market_screening_results (status=due), advances next_run_at
        │     OR queues manual run (run_requested_at → is_test row)
        │
        └─ Phase 2: _dispatch_due_public
              subprocess: python -m services.market_screenings.cli run <id> --result-id <uuid> [--is-test]

services.market_screenings.cli run
        │
        ▼
runner.run_market_screening(screening)
        │   registry.get_script(screening["script_key"]) → callable
        │   script(client, screening) → ScreeningResult
        │
        ▼
runner.persist_and_deliver_public(result, result_id=…)
        │   UPDATE/INSERT market_screening_results (summary, triggered, lean data_used, status)
        │   INSERT market_screening_result_rows (one row per ticker from data_used["symbols"])
        │   UPDATE market_screenings (last_run_at, last_triggered; clears run_requested_at on test)
        │
        ├── llm_prompt set + symbols + no error?
        │     YES → UPDATE market_screening_results.bulk_analysis_status='queued'
        │            (fan-out is DEFERRED — the bulk-analytics worker will trigger it)
        │     NO  → fan_out_to_subscribers(result)  (immediate, see below)
        │
        ▼
─── If queued, the bulk-analytics tick picks it up: ────────────────────────────

OpenClaw cron: public-bulk-analysis-tick  (every minute, UTC)
        │
        ▼
services.market_screening_bulk_analytics.cli tick
        │
        ▼
scheduler.run_tick   (cleanup stuck 'running', dispatch oldest 'queued')
        │
        ▼ subprocess: python -m services.market_screening_bulk_analytics.cli run <result-id>
worker.run_pass(result_id)
        │   load parent screening for llm_prompt
        │   load every market_screening_result_rows row for this result
        │   per ticker (concurrency-bounded):
        │     fetch FMP 6-month OHLCV + SMAs   (services.bulk_analysis.fetch)
        │     LLM call — single pass, strict JSON  (services.bulk_analysis.prompt)
        │     merge {status, comment, analysis_markdown, entry, generated_at}
        │     into row_data.llm_analysis; UPDATE the row
        │   UPDATE market_screening_results.bulk_analysis_status='done'
        │
        └─► runner.fan_out_from_db(result_id)
                  rebuilds the fan-out payload from the now-enriched rows and
                  delegates to fan_out_to_subscribers, so subscribers see and
                  get notified about the analysis-enriched results.

─── Fan-out (called either immediately or after bulk-analytics): ──────────────

fan_out_to_subscribers(result)
        per row in market_screening_subscriptions:
          INSERT user_scan_jobs, user_scan_runs, user_scan_rows (full payload incl. symbols)
          optional Telegram (if notifications_enabled + linked chat)
```

Cron helpers (`parse_schedule`, `next_run_after`, `to_utc`) live in **`shared/screening_schedule.py`** and are shared with the LLM agent scheduler so both use identical `next_run_at` semantics.

Concurrency for **public** runs alone: **`MARKET_SCREENING_MAX_CONCURRENT`** (falls back to **`SCREENING_MAX_CONCURRENT`**, then `1`). Stuck-job timeout uses **`SCREENING_STUCK_TIMEOUT_MINUTES`** (same as the agent).

Register the OpenClaw job with **`python -m services.market_screenings.cli setup-cron`** or run **`python -m services.agent.cli setup-cron`**, which also ensures `market-screening-tick` exists alongside `screening-tick`.

### System crontab (no OpenClaw)

Use the same minute tick from **`cron`** or **`launchd`**. Wrapper (loads `.env` via `cd` into `code/analytics`):

[`scripts/run_market_screenings_tick.sh`](../../scripts/run_market_screenings_tick.sh)

```cron
* * * * * /ABS/PATH/swingtrader/code/analytics/scripts/run_market_screenings_tick.sh >> /ABS/PATH/logs/market_screenings_tick.log 2>&1
```

Or inline (still `cd` into analytics so `.env` resolves):

```cron
* * * * * cd /ABS/PATH/swingtrader/code/analytics && ./.venv/bin/python -m services.market_screenings.cli tick >> /ABS/PATH/logs/market_screenings_tick.log 2>&1
```

If you use crontab for market screenings, **do not** also register OpenClaw `market-screening-tick` for the same host (double queueing). The LLM agent tick (`screening-tick` / `services.agent.cli tick`) is separate — run that on its own schedule/cron if you use it.

---

## Database (schema `swingtrader`)

| Table | Role |
|-------|------|
| `market_screenings` | Definition: `name`, `slug`, `script_key`, schedule fields (`next_run_at`, cron-style config), `is_active`, `is_published`, `run_requested_at` for manual test, `author_user_id`, counters such as `download_count`, optional **`llm_prompt`** that opts the screening into the bulk-analytics pass. |
| `market_screening_results` | One row per **run**: `status` (`due` → `running` → `done`/`error`), `triggered`, `summary`, `data_used` (JSONB **without** the heavy `symbols` list after persist — see below), `is_test`, timestamps. Bulk-analytics state lives here too: **`bulk_analysis_status`** (`queued` / `running` / `done` / `error` / `null`), **`bulk_analysis_started_at`**, **`bulk_analysis_finished_at`**, **`bulk_analysis_error`**. |
| `market_screening_result_rows` | Canonical **per-ticker** rows for the public run (symbol + `row_data`), keyed by `result_id`. Used by the Next.js app for tables/exports without bloating `data_used`. The bulk-analytics worker enriches `row_data` in place by adding a top-level `llm_analysis` object: `{ status, comment, analysis_markdown, entry, generated_at }`. |
| `market_screening_subscriptions` | User opted in: `user_id`, `market_screening_id`, `notifications_enabled`. |

Migrations: `20260512150000_market_screenings.sql`, `20260513000000_market_screening_result_rows.sql`, `20260513010000_market_screening_download_counter.sql`, `20260514000000_market_screenings_llm_analysis.sql`, `20260514120000_market_screenings_schedule_recompute_trigger.sql`.

> **Schedule edits auto-recompute `next_run_at`.** A `BEFORE UPDATE OF schedule, timezone` trigger on `market_screenings` sets `next_run_at = NULL` whenever either field actually changes. The next scheduler tick re-initializes it from `last_run_at`. Without this, the scheduler keeps advancing the *old* `next_run_at` by one step from its previous value, leaving the new cadence anchored to a stale time.

---

## Script contract

Each registered script lives under `scripts/<script_key>.py` and exposes:

```python
def run(client, screening: dict) -> ScreeningResult: ...
```

- **`client`**: Supabase client (scripts may ignore it if they only call FMP/other APIs).
- **`screening`**: Full `market_screenings` row (includes `id`, `name`, `script_key`, etc.).

Return a **`ScreeningResult`** (`types.py`):

| Field | Meaning |
|-------|---------|
| `triggered` | Whether the run is treated as an “alert” vs informational (Telegram `message_type`, semantics in UI). |
| `summary` | Short HTML/text for logs and richer context; subscriber Telegram uses a separate compact template (name + ticker count / error). |
| `data_used` | Arbitrary JSON-serializable metadata. **If you include `symbols`**, it must be a **list of dicts**; each dict should have a `"symbol"` key for indexing. Those rows are stripped from the persisted `market_screening_results.data_used` and written to `market_screening_result_rows` and to each subscriber’s `user_scan_rows`. |
| `ticker_count` | Optional; used in Telegram (“N tickers”). Defaults omitted → omitted in notification. |
| `error` | If truthy, run is stored as `status=error` and subscribers get an error-style Telegram when notifications are on. |

Unknown `script_key` or uncaught exceptions become an error result (runner does not crash the subprocess).

---

## Registry

`registry.py` maps `script_key` → function. To add a screening:

1. Implement `scripts/<key>.py` with `run(client, screening) -> ScreeningResult`.
2. Import it in `registry.py` and add `"<key>": module.run` to `SCRIPTS`.
3. Insert/update a `market_screenings` row with `script_key = "<key>"` (admin UI or SQL). The row must be **`is_published`** for the scheduler to queue it.

Current keys: `list_script_keys()` → e.g. `nis_momentum`, `nis_short`, `stage_2`, `test_aapl`.

---

## Key files

| File | Role |
|------|------|
| `cli.py` | `tick` (scheduler), `run` (one job), `setup-cron` (OpenClaw `market-screening-tick` only). |
| `scheduler.py` | Queue + dispatch due `market_screening_results`; independent from `services.agent.scheduler`. |
| `sync_crons.py` | Registers `market-screening-tick` in OpenClaw. |
| `runner.py` | `run_market_screening`, `persist_and_deliver_public`, subscriber fan-out and Telegram. |
| `registry.py` | `SCRIPTS` map and `get_script`. |
| `types.py` | `ScreeningResult` dataclass. |
| `scripts/stage_2.py` | Example: full-universe Minervini stage-2-style screen via `services.screener.technical`; builds `data_used["symbols"]` for passers. |
| `scripts/nis_momentum.py` | Example screening implementation. |
| `scripts/nis_short.py` | Short-side inverse of NIS Momentum — Minervini/O'Neil Stage-4 decline of a **former leader** (up 100%+ prior, now rolling over), gated on a bearish market regime. See its module docstring. |
| `scripts/test_aapl.py` | Minimal smoke script for pipeline testing. |

---

## CLI

```bash
cd code/analytics

# OpenClaw calls this every minute (job name: market-screening-tick)
python -m services.market_screenings.cli tick [--max-concurrent N]

# One run (normally launched by tick after a due row is inserted)
python -m services.market_screenings.cli run <market_screening_uuid> \
  --result-id <market_screening_result_uuid> [--is-test] [--dry-run]

# Register only the public OpenClaw cron (agent setup-cron does this too)
python -m services.market_screenings.cli setup-cron
```

- **`tick`**: Queues due definitions, dispatches oldest `due` result rows up to the concurrency limit, clears stuck `running` rows.
- **`run` `--result-id`**: Required in production — the scheduler pre-inserts `market_screening_results` as `due`, then passes its `id` so the runner **updates** that row instead of inserting a duplicate.
- **`--dry-run`**: Executes the script but skips `persist_and_deliver_public`.
- **`--is-test`**: Manual trigger path; `run_requested_at` is cleared on the parent screening after success.

---

## LLM bulk-analytics pass

Lives in a sibling module: [`services/market_screening_bulk_analytics/`](../market_screening_bulk_analytics/).

- **Trigger**: `runner.persist_and_deliver_public` sets `bulk_analysis_status='queued'` on the result row whenever the parent screening has a non-empty `llm_prompt`, the run produced symbols, and didn't error. The fan-out is **skipped** in that path; it runs after the worker finishes.
- **Worker**: per ticker, fetches a 6-month FMP snapshot (`services.bulk_analysis.fetch`), calls the LLM once with the prompt schema in `services.bulk_analysis.prompt`, and merges the parsed result into `market_screening_result_rows.row_data.llm_analysis`. The schema mirrors the user-facing bulk-analysis tool (`status`, `comment`, `analysis_markdown`, optional `entry`).
- **Fan-out trigger**: when the pass finishes, the worker calls `runner.fan_out_from_db(result_id)`, which reconstructs the fan-out payload **from the now-enriched DB rows** and delivers to subscribers — so subscribers see (and get notified about) results that already include the analysis.
- **One pass per result**: state lives on `market_screening_results` itself, not in a separate jobs table.

### CLI

```bash
cd code/analytics

# OpenClaw calls this every minute (job name: public-bulk-analysis-tick)
python -m services.market_screening_bulk_analytics.cli tick [--max-concurrent N]

# Run one pass for a specific market_screening_results row (normally launched by tick)
python -m services.market_screening_bulk_analytics.cli run <market_screening_result_uuid>

# Register the OpenClaw cron
python -m services.market_screening_bulk_analytics.cli setup-cron
```

### System crontab (no OpenClaw)

Same minute tick from `cron` or `launchd`. Wrapper (loads `.env` via `cd` into `code/analytics`):

[`scripts/run_market_bulk_analysis_tick.sh`](../../scripts/run_market_bulk_analysis_tick.sh)

```cron
* * * * * /ABS/PATH/swingtrader/code/analytics/scripts/run_market_bulk_analysis_tick.sh >> /ABS/PATH/logs/market_bulk_analysis_tick.log 2>&1
```

Or inline:

```cron
* * * * * cd /ABS/PATH/swingtrader/code/analytics && ./.venv/bin/python -m services.market_screening_bulk_analytics.cli tick >> /ABS/PATH/logs/market_bulk_analysis_tick.log 2>&1
```

If you use crontab for the bulk-analysis tick, **do not** also register OpenClaw `public-bulk-analysis-tick` for the same host (double dispatch). Pair it with whichever scheduler you use for `market-screening-tick` — both ticks run independently and at the same cadence (every minute), but they're separate jobs and can be scheduled by different runners if you want.

---

## Running a full screening end-to-end

Use this to dry-run the entire pipeline against the live DB without waiting for cron.

1. **One-time setup — register both cron jobs.** (Skip if you use system crontab.)

   ```bash
   cd code/analytics
   .venv/bin/python -m services.market_screenings.cli setup-cron
   .venv/bin/python -m services.market_screening_bulk_analytics.cli setup-cron
   ```

2. **Set an `llm_prompt`** on a published screening to opt it into the bulk-analytics pass. Example via SQL (Supabase Studio or `psql`):

   ```sql
   UPDATE swingtrader.market_screenings
      SET llm_prompt = 'Identify high-probability swing-trading setups. Flag clear pivot levels, breakouts above resistance, or pullbacks to rising 20/50 SMAs. Return entry, stop, and target where a tradeable level exists.'
    WHERE slug = 'nis-momentum';
   ```

   To run **without** LLM analysis, leave `llm_prompt = NULL` — the screening fans out immediately, same as before.

3. **Trigger a manual run.** Either:

   - **From the admin UI** (`/protected/agents` or wherever your admin tools live), click *Run now*, which sets `run_requested_at`. The next `market-screening-tick` will queue a `due` result row and dispatch.
   - **Or directly via CLI** (skips the scheduler):

     ```bash
     # Get the screening id and a fresh result row id first:
     # SELECT id FROM swingtrader.market_screenings WHERE slug = 'nis-momentum';
     .venv/bin/python -m services.market_screenings.cli run <screening_id> --is-test
     ```

4. **Watch it queue for analysis.** After step 3 completes, the result row exists with `bulk_analysis_status='queued'`:

   ```sql
   SELECT id, status, bulk_analysis_status, run_at
     FROM swingtrader.market_screening_results
    WHERE market_screening_id = '<screening_id>'
    ORDER BY run_at DESC LIMIT 1;
   ```

5. **Run the bulk-analytics pass** (either wait one minute for the cron, or trigger directly):

   ```bash
   .venv/bin/python -m services.market_screening_bulk_analytics.cli run <result_id>
   ```

6. **Verify enrichment + fan-out.**

   ```sql
   -- Per-ticker enrichment landed on row_data.llm_analysis
   SELECT symbol, row_data->'llm_analysis'->>'status' AS llm_status,
          row_data->'llm_analysis'->>'comment'        AS comment
     FROM swingtrader.market_screening_result_rows
    WHERE result_id = '<result_id>';

   -- Pass marked done
   SELECT bulk_analysis_status, bulk_analysis_finished_at, bulk_analysis_error
     FROM swingtrader.market_screening_results WHERE id = '<result_id>';

   -- Subscribers got their copies (one user_scan_runs row per subscriber)
   SELECT user_id, scan_date, source
     FROM swingtrader.user_scan_runs
    WHERE source = 'market_screening:nis-momentum'
    ORDER BY scan_date DESC LIMIT 5;
   ```

   In the UI, the screening at `/screenings/nis-momentum` shows the `llm_prompt` panel, and `/protected/screenings` shows the enriched `llm_analysis` block on each ticker for any user who's subscribed.

---

## Frontend

Server actions and routes under `code/ui/app/actions/market-screenings.ts` (and related pages) load published screenings, latest results, `market_screening_result_rows`, subscriptions, and download counting (`increment_market_screening_download` RPC). Subscribers see mirrored runs under **Screenings** via `user_scan_rows` (`dataset` matches `script_key` for filtering in the UI).

---

## Environment

Uses the same Supabase and Telegram configuration as other analytics services (`shared/db.py`, `shared/telegram.py`).

| Variable | Default | Purpose |
|----------|---------|---------|
| `MARKET_SCREENING_MAX_CONCURRENT` | `SCREENING_MAX_CONCURRENT` or `1` | Max parallel `market_screening_results` runs dispatched per tick. |
| `SCREENING_MAX_CONCURRENT` | `1` | Fallback when `MARKET_SCREENING_MAX_CONCURRENT` is unset. |
| `SCREENING_STUCK_TIMEOUT_MINUTES` | `20` | Flip stuck `running` public rows to `error`. |
| `SCREENING_TIMEOUT_MS` | `600000` | OpenClaw wall-clock timeout for the **tick** cron message. |
| `PUBLIC_BULK_ANALYSIS_MAX_CONCURRENT` | `1` | Max concurrent bulk-analytics passes dispatched per tick. |
| `PUBLIC_BULK_ANALYSIS_CONCURRENCY` | `2` | Per-pass per-ticker concurrency (asyncio.Semaphore inside the worker). |
| `PUBLIC_BULK_ANALYSIS_TIMEOUT` | `90` | Per-ticker LLM-call timeout in seconds. |
| `PUBLIC_BULK_ANALYSIS_STUCK_TIMEOUT_MINUTES` | `60` | Flip stuck `running` bulk-analysis rows to `error`. |
| `PUBLIC_BULK_ANALYSIS_BACKEND` | `ollama` | LLM backend: `ollama`, `anthropic`, `do_agent`. |
| `PUBLIC_BULK_ANALYSIS_MODEL` | (backend default) | Override the model name for the LLM call. |
| `PUBLIC_BULK_ANALYSIS_TIMEOUT_MS` | `1800000` | OpenClaw wall-clock timeout for the **bulk-analysis tick** cron message. |
