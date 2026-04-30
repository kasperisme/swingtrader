# Screening Agent

LLM-driven scheduled screening service. Analyzes market data against user-defined prompts, delivers results via Telegram.

## Architecture

```
OpenClaw (one cron, every minute)
  └─ cli.py tick
       ├─ croniter: which screenings are due?
       ├─ DB: count running jobs (concurrency gate)
       ├─ DB: insert result row (status=running)
       └─ subprocess: cli.py run <id> --result-id <uuid>
                           └─ engine.py: LLM agent loop
                           └─ engine.py: persist_and_deliver → Telegram
```

Single OpenClaw cron replaces per-screening crons to avoid rate limits.

---

## Setup

```bash
# Install dependencies
pip install -r requirements.txt

# Register the tick cron in OpenClaw (run once)
python -m services.agent.cli setup-cron
```

Apply the DB migration before first run:

```
supabase/migrations/20260430200000_screening_results_status.sql
```

---

## CLI

```bash
# Run one scheduler tick manually
python -m services.agent.cli tick [--max-concurrent N]

# Run a specific screening directly
python -m services.agent.cli run <screening-id> [--dry-run]

# Register/repair the single tick cron in OpenClaw
python -m services.agent.cli setup-cron

# Test FMP connectivity
python -m services.agent.cli fmp-test
```

---

## How Scheduling Works

Each `user_scheduled_screenings` row has a standard 5-part cron expression (`schedule`), a `timezone`, and a `next_run_at` timestamp (pre-computed next scheduled fire time).

Every minute the tick runs two phases:

### Phase 1 — Queue

```
For each active screening:
  │
  ├─ next_run_at IS NULL?
  │    → compute first next_run_at from last_run_at (or created_at)
  │    → save it, skip this tick (runs next time)
  │
  ├─ next_run_at > now? → not yet due, skip
  │
  └─ next_run_at <= now → due
       INSERT user_screening_results (status='due', run_at=next_run_at)
       UPDATE user_scheduled_screenings SET next_run_at = <next cron fire>

For each screening with run_requested_at set (manual trigger):
  └─ no existing due/running row? → INSERT (status='due', is_test=true)
```

`next_run_at` advances immediately after queueing, so the same scheduled time is never queued twice. Due rows accumulate across ticks — nothing is dropped.

### Phase 2 — Dispatch

```
running_count = SELECT count(*) WHERE status='running'
available     = MAX_CONCURRENT - running_count

SELECT id, screening_id FROM user_screening_results
  WHERE status='due'
  ORDER BY run_at ASC          ← oldest first
  LIMIT available

For each row:
  UPDATE status='running', started_at=now
  Popen: cli.py run <screening_id> --result-id <id>
         └─ engine.py: LLM agent loop
         └─ persist_and_deliver: UPDATE row → status=done|error, deliver Telegram
```

### Handling clustered screenings

If A, B, C are all due at the same minute and `MAX_CONCURRENT=1`:

```
tick 1 → Phase 1: inserts due rows for A, B, C
          Phase 2: dispatches A (status=running), B and C stay due
tick 2 → Phase 1: nothing new due
          Phase 2: A still running → 0 slots → B, C stay due
tick 3 → Phase 1: nothing new due
          Phase 2: A done → dispatches B
tick 4 → dispatches C
```

B and C are never dropped — they wait in the queue until a slot opens.

### Stuck job detection

Jobs still marked `running` after `STUCK_TIMEOUT_MINUTES` are flipped to `error` at the start of each tick, freeing their concurrency slot.

**Manual trigger:** set `run_requested_at` on the screening row. Next tick queues it as `is_test=true`. `persist_and_deliver` clears `run_requested_at` after the run.

---

## Concurrency

| Env var | Default | Purpose |
|---------|---------|---------|
| `SCREENING_MAX_CONCURRENT` | `1` | Max parallel screening runs |
| `SCREENING_STUCK_TIMEOUT_MINUTES` | `20` | Mark stuck `running` rows as `error` |
| `SCREENING_TIMEOUT_MS` | `600000` | OpenClaw wall-clock timeout for the tick cron |

---

## Result Lifecycle

```
DB row status:  running → done | error
                         ↑
                persist_and_deliver() called by run subprocess
```

`delivered=true` is set after successful Telegram send.

---

## Key Files

| File | Purpose |
|------|---------|
| `scheduler.py` | Tick logic: due-check, concurrency, subprocess launch |
| `engine.py` | LLM agent loop (Ollama), `run_screening`, `persist_and_deliver` |
| `cli.py` | CLI entrypoint |
| `sync_crons.py` | One-time OpenClaw tick cron setup + old cron cleanup |
| `data_queries.py` | Supabase query wrappers (market + user data) |
| `fmp_tools.py` | FMP MCP client (optional, requires `FMP_API_KEY`) |

---

## DB Tables

**`user_scheduled_screenings`** — user-defined screening config (prompt, schedule, tickers).

**`user_screening_results`** — execution history. Key fields:

| Field | Type | Notes |
|-------|------|-------|
| `status` | text | `running` / `done` / `error` |
| `started_at` | timestamptz | Set by scheduler tick on launch |
| `run_at` | timestamptz | Same as `started_at` (scheduled time) |
| `triggered` | bool | Whether LLM conditions were met |
| `delivered` | bool | Whether Telegram message was sent |
| `is_test` | bool | True for manual `run_requested_at` runs |
