# Public screenings

Admin-defined, **script-backed** screenings that run on a shared schedule, persist one **global** result per run, and **fan out** copies to every subscribed user (their `user_scan_*` tables plus optional Telegram). They complement **private** screenings (`user_scheduled_screenings` + LLM agent in `services/agent/`): public runs are deterministic Python in this package, not the tool-calling agent.

---

## Architecture

```
OpenClaw cron: public-screening-tick  (every minute, UTC)
        │
        ▼
services.public_screenings.cli tick [--max-concurrent N]
        │
        ▼
scheduler.run_tick
        │
        ├─ Phase 1: _queue_due_public_screenings
        │     inserts public_screening_results (status=due), advances next_run_at
        │     OR queues manual run (run_requested_at → is_test row)
        │
        └─ Phase 2: _dispatch_due_public
              subprocess: python -m services.public_screenings.cli run <id> --result-id <uuid> [--is-test]

services.public_screenings.cli run
        │
        ▼
runner.run_public_screening(screening)
        │   registry.get_script(screening["script_key"]) → callable
        │   script(client, screening) → ScreeningResult
        │
        ▼
runner.persist_and_deliver_public(result, result_id=…)
        │   UPDATE/INSERT public_screening_results (summary, triggered, lean data_used, status)
        │   INSERT public_screening_result_rows (one row per ticker from data_used["symbols"])
        │   UPDATE public_screenings (last_run_at, last_triggered; clears run_requested_at on test)
        │
        └─► _fan_out_to_subscribers
                  per row in public_screening_subscriptions:
                    INSERT user_scan_jobs, user_scan_runs, user_scan_rows (full payload incl. symbols)
                    optional Telegram (if notifications_enabled + linked chat)
```

Cron helpers (`parse_schedule`, `next_run_after`, `to_utc`) live in **`shared/screening_schedule.py`** and are shared with the LLM agent scheduler so both use identical `next_run_at` semantics.

Concurrency for **public** runs alone: **`PUBLIC_SCREENING_MAX_CONCURRENT`** (falls back to **`SCREENING_MAX_CONCURRENT`**, then `1`). Stuck-job timeout uses **`SCREENING_STUCK_TIMEOUT_MINUTES`** (same as the agent).

Register the OpenClaw job with **`python -m services.public_screenings.cli setup-cron`** or run **`python -m services.agent.cli setup-cron`**, which also ensures `public-screening-tick` exists alongside `screening-tick`.

### System crontab (no OpenClaw)

Use the same minute tick from **`cron`** or **`launchd`**. Wrapper (loads `.env` via `cd` into `code/analytics`):

[`scripts/run_public_screenings_tick.sh`](../../scripts/run_public_screenings_tick.sh)

```cron
* * * * * /ABS/PATH/swingtrader/code/analytics/scripts/run_public_screenings_tick.sh >> /ABS/PATH/logs/public_screenings_tick.log 2>&1
```

Or inline (still `cd` into analytics so `.env` resolves):

```cron
* * * * * cd /ABS/PATH/swingtrader/code/analytics && ./.venv/bin/python -m services.public_screenings.cli tick >> /ABS/PATH/logs/public_screenings_tick.log 2>&1
```

If you use crontab for public screenings, **do not** also register OpenClaw `public-screening-tick` for the same host (double queueing). The LLM agent tick (`screening-tick` / `services.agent.cli tick`) is separate — run that on its own schedule/cron if you use it.

---

## Database (schema `swingtrader`)

| Table | Role |
|-------|------|
| `public_screenings` | Definition: `name`, `slug`, `script_key`, schedule fields (`next_run_at`, cron-style config), `is_active`, `is_published`, `run_requested_at` for manual test, `author_user_id`, counters such as `download_count`. |
| `public_screening_results` | One row per **run**: `status` (`due` → `running` → `done`/`error`), `triggered`, `summary`, `data_used` (JSONB **without** the heavy `symbols` list after persist — see below), `is_test`, timestamps. |
| `public_screening_result_rows` | Canonical **per-ticker** rows for the public run (symbol + `row_data`), keyed by `result_id`. Used by the Next.js app for tables/exports without bloating `data_used`. |
| `public_screening_subscriptions` | User opted in: `user_id`, `public_screening_id`, `notifications_enabled`. |

Migrations: `20260512150000_public_screenings.sql`, `20260513000000_public_screening_result_rows.sql`, `20260513010000_public_screening_download_counter.sql`.

---

## Script contract

Each registered script lives under `scripts/<script_key>.py` and exposes:

```python
def run(client, screening: dict) -> ScreeningResult: ...
```

- **`client`**: Supabase client (scripts may ignore it if they only call FMP/other APIs).
- **`screening`**: Full `public_screenings` row (includes `id`, `name`, `script_key`, etc.).

Return a **`ScreeningResult`** (`types.py`):

| Field | Meaning |
|-------|---------|
| `triggered` | Whether the run is treated as an “alert” vs informational (Telegram `message_type`, semantics in UI). |
| `summary` | Short HTML/text for logs and richer context; subscriber Telegram uses a separate compact template (name + ticker count / error). |
| `data_used` | Arbitrary JSON-serializable metadata. **If you include `symbols`**, it must be a **list of dicts**; each dict should have a `"symbol"` key for indexing. Those rows are stripped from the persisted `public_screening_results.data_used` and written to `public_screening_result_rows` and to each subscriber’s `user_scan_rows`. |
| `ticker_count` | Optional; used in Telegram (“N tickers”). Defaults omitted → omitted in notification. |
| `error` | If truthy, run is stored as `status=error` and subscribers get an error-style Telegram when notifications are on. |

Unknown `script_key` or uncaught exceptions become an error result (runner does not crash the subprocess).

---

## Registry

`registry.py` maps `script_key` → function. To add a screening:

1. Implement `scripts/<key>.py` with `run(client, screening) -> ScreeningResult`.
2. Import it in `registry.py` and add `"<key>": module.run` to `SCRIPTS`.
3. Insert/update a `public_screenings` row with `script_key = "<key>"` (admin UI or SQL). The row must be **`is_published`** for the scheduler to queue it.

Current keys: `list_script_keys()` → e.g. `nis_momentum`, `stage_2`, `test_aapl`.

---

## Key files

| File | Role |
|------|------|
| `cli.py` | `tick` (scheduler), `run` (one job), `setup-cron` (OpenClaw `public-screening-tick` only). |
| `scheduler.py` | Queue + dispatch due `public_screening_results`; independent from `services.agent.scheduler`. |
| `sync_crons.py` | Registers `public-screening-tick` in OpenClaw. |
| `runner.py` | `run_public_screening`, `persist_and_deliver_public`, subscriber fan-out and Telegram. |
| `registry.py` | `SCRIPTS` map and `get_script`. |
| `types.py` | `ScreeningResult` dataclass. |
| `scripts/stage_2.py` | Example: full-universe Minervini stage-2-style screen via `services.screener.technical`; builds `data_used["symbols"]` for passers. |
| `scripts/nis_momentum.py` | Example screening implementation. |
| `scripts/test_aapl.py` | Minimal smoke script for pipeline testing. |

---

## CLI

```bash
cd code/analytics

# OpenClaw calls this every minute (job name: public-screening-tick)
python -m services.public_screenings.cli tick [--max-concurrent N]

# One run (normally launched by tick after a due row is inserted)
python -m services.public_screenings.cli run <public_screening_uuid> \
  --result-id <public_screening_result_uuid> [--is-test] [--dry-run]

# Register only the public OpenClaw cron (agent setup-cron does this too)
python -m services.public_screenings.cli setup-cron
```

- **`tick`**: Queues due definitions, dispatches oldest `due` result rows up to the concurrency limit, clears stuck `running` rows.
- **`run` `--result-id`**: Required in production — the scheduler pre-inserts `public_screening_results` as `due`, then passes its `id` so the runner **updates** that row instead of inserting a duplicate.
- **`--dry-run`**: Executes the script but skips `persist_and_deliver_public`.
- **`--is-test`**: Manual trigger path; `run_requested_at` is cleared on the parent screening after success.

---

## Frontend

Server actions and routes under `code/ui/app/actions/public-screenings.ts` (and related pages) load published screenings, latest results, `public_screening_result_rows`, subscriptions, and download counting (`increment_public_screening_download` RPC). Subscribers see mirrored runs under **Screenings** via `user_scan_rows` (`dataset` matches `script_key` for filtering in the UI).

---

## Environment

Uses the same Supabase and Telegram configuration as other analytics services (`shared/db.py`, `shared/telegram.py`).

| Variable | Default | Purpose |
|----------|---------|---------|
| `PUBLIC_SCREENING_MAX_CONCURRENT` | `SCREENING_MAX_CONCURRENT` or `1` | Max parallel `public_screening_results` runs dispatched per tick. |
| `SCREENING_MAX_CONCURRENT` | `1` | Fallback when `PUBLIC_SCREENING_MAX_CONCURRENT` is unset. |
| `SCREENING_STUCK_TIMEOUT_MINUTES` | `20` | Flip stuck `running` public rows to `error`. |
| `SCREENING_TIMEOUT_MS` | `600000` | OpenClaw wall-clock timeout for the **tick** cron message. |
