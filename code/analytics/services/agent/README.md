# Screening Agent

LLM-driven scheduled screening service. Analyzes market data against user-defined prompts, delivers results via Telegram.

## Architecture

```
OpenClaw: screening-tick (every minute, UTC)
  └─ services.agent.cli tick
       ├─ croniter + next_run_at: which user screenings are due?
       ├─ DB: count running user_screening_results (concurrency gate)
       └─ subprocess: services.agent.cli run <id> --result-id <uuid>
                           └─ engine.py: LLM agent loop
                           └─ engine.py: persist_and_deliver → Telegram
```

```
OpenClaw: market-screening-tick (every minute, UTC)   ← separate cron
  └─ services.market_screenings.cli tick
       └─ subprocess: services.market_screenings.cli run <id> --result-id <uuid>
                           └─ market_screenings/runner.py (scripts + fan-out)
```

Both schedulers import **`shared.screening_schedule`** for the same `next_run_at` semantics. `python -m services.agent.cli setup-cron` registers **both** OpenClaw jobs when missing.

Single **user** tick replaces per-screening crons to avoid rate limits; **market** screenings use their own tick for isolation.

---

## Setup

```bash
# Install dependencies
pip install -r requirements.txt

# Register OpenClaw crons (screening-tick + market-screening-tick) — run once
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

# Register OpenClaw crons (user + public ticks)
python -m services.agent.cli setup-cron

# Test FMP connectivity
python -m services.agent.cli fmp-test
```

**Public script screenings** are scheduled by [`../market_screenings/scheduler.py`](../market_screenings/scheduler.py) (`market_screenings.cli tick`), not this CLI. After upgrading, run `setup-cron` once if `market-screening-tick` is missing.

See [`../market_screenings/README.md`](../market_screenings/README.md).

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

### Skills (the optimized primary path)

Screenings with ≥2 tickers route through `multi_ticker.py`. Before the dynamic
LLM planner runs, a **cheap classifier** (`skills.classify_skill`) maps the
prompt to a predefined `ScreeningSkill` (`skills.py`). On a match, the skill's
**hardcoded** recipe runs as the primary path — the model never chooses tools
or FMP endpoints. Each per-ticker evaluation walks a deterministic-first ladder:

```
1. FETCH    skill.tool_plan runs verbatim (internal RAG + FMP, args/enums baked in)
2. COMPUTE  skill.analytics(ticker, data) → TickerSignal (pure Python)
              metrics + facts + a verdict where the data is unambiguous
3. JUDGE    only TickerSignals with needs_llm=True go to the per-ticker LLM
              evaluator (skill.eval_focus tunes it); decided cases cost no tokens
4. VERDICT  stage-3 concluder synthesises {triggered, summary}
```

This collapses the old `plan(≤90s) [+ re-plan(≤90s)] + trial rounds` prefix into
**one cheap classify call**, makes plans reproducible per intent, and shrinks the
per-ticker LLM batch to only the ambiguous names (a breakout run may escalate
zero tickers). Skills stand on an internal `requires` floor; FMP calls are
best-effort — unknown/access-denied FMP tools are dropped and analytics degrades
to escalation. When no skill fits (classifier → `NONE`) or a skill's required
internal tools are missing, the run **diverts** to the unchanged dynamic planner.

Current skills: `news_impact`, `breakout`, `portfolio_rundown`,
`relationship_contagion`. Inspect/repair them with:

```bash
python -m services.agent.cli validate-skills [--user-id <uuid>] [--probe] [--ticker AAPL]
python -m services.agent.cli classify "which names are breaking out?"
```

`validate-skills` checks each skill's `requires` against a live registry, reports
which FMP tools resolve, and (with `--probe`) calls them to confirm API-plan
availability. Run `validate-skills --probe` after an FMP plan change.

#### Breakout skill — fully deterministic, multi-timeframe

The breakout decision is made **entirely in Python** (`_analytics_breakout`) and
never escalates to the LLM — the per-ticker verdict is reproducible, and the LLM
only writes the final multi-ticker message from the confirmed set.

It scans **multiple timeframes** (`_BREAKOUT_TIMEFRAMES`): **daily** EOD and
**intraday hourly**. The skill calls FMP `chart` twice under distinct result
slots — `chart_daily` (`historical-price-eod-light`, ~45-day window) and
`chart_1h` (`intraday-1-hour`, ~5-day window) — plus `quote` (live price/volume,
used for the daily check) and the user's logged entry from
`get_user_screening_note_details`. (The pipeline supports the same tool under
multiple slots via an optional `key` on a tool-plan entry; see `_plan_key`.) A
ticker **triggers if ANY timeframe confirms**, so an intraday move is caught as
it develops — before the daily candle has run up. If the intraday endpoint isn't
available on the API tier, that timeframe is simply skipped.

A timeframe **confirms** when price is in an early-biased band around its
reference **and** volume ≥ `_VOLUME_SURGE`× (1.5×) the trailing average:

- **With a logged entry note** → reference is the planned entry price, direction-
  aware. Band = `[entry·(1−pre), entry·(1+post)]` (long) — default ±5%
  (`_ENTRY_PRE_BAND_PCT` / `_ENTRY_POST_BAND_PCT`). The pre band fires *before*
  price reaches the entry (early detection); the post band keeps it fresh just
  past. Short entries mirror this.
- **No entry note** → reference is the trailing high of that timeframe
  (`_BREAKOUT_LOOKBACK` daily bars / `_INTRADAY_LOOKBACK_BARS` hourly bars);
  in-band = within `pre`% below the high or any new high.

Detection is intentionally biased toward early/false-positive over missing a
breakout. Tune the bands/threshold/timeframes via the constants at the top of
`skills.py` (`_BREAKOUT_TIMEFRAMES`) and the intraday window via
`AGENT_INTRADAY_LOOKBACK_DAYS`.

### Multi-ticker pipeline (screenings with ≥2 tickers)

The fan-out pipeline (`multi_ticker.py`) evaluates tickers in mini-batches so
the call count scales as `ceil(N / batch_size)` instead of `N`. These knobs
tune throughput vs. isolation:

| Env var | Default | Purpose |
|---------|---------|---------|
| `AGENT_MULTI_TICKER_BATCH_SIZE` | `5` | Tickers evaluated per LLM call. `1` = strict one-ticker-per-call isolation. |
| `AGENT_MULTI_TICKER_CONCURRENCY` | `3` | Max concurrent batches in flight. |
| `AGENT_BATCH_EVAL_TIMEOUT` | `120` | Per-batch eval wall-clock ceiling (seconds). |
| `AGENT_BATCH_PER_TOOL_CHARS` | `2500` | Per-tool payload cap inside a batched prompt. |
| `AGENT_RUN_TIMEOUT_SECONDS` | `240` | Hard ceiling on the whole run (set in `engine.py`); a timeout now delivers a ⚠️ failure alert. |

---

## Result Lifecycle

```
DB row status:  running → done | error
                         ↑
                persist_and_deliver() called by run subprocess
```

`delivered=true` is set after successful Telegram send.

### Run trace (debugging a job from the DB)

Every run records an ordered event log to `user_screening_results.trace` (JSONB),
written by `persist_and_deliver`. It captures the sequence of stages
(`run.start → classify → plan → fetch → analytics → eval → conclude`) with
relative timestamps, so a job can be reconstructed straight from the database —
**including runs that errored or timed out**. The recorder (`run_trace.py`) is
created in the synchronous engine frame and passed into the async pipeline by
reference, so a wall-clock timeout that cancels the pipeline still leaves the
events recorded up to the deadline.

Shape: `{ started_at, elapsed, event_count, events: [ {seq, dt, stage, event, …} ] }`.

```sql
-- the sequence of events for one run, newest jobs first
select e->>'stage' as stage, e->>'event' as event, e->>'dt' as t, e
from swingtrader.user_screening_results r,
     jsonb_array_elements(r.trace->'events') e
where r.id = '<result-uuid>'
order by (e->>'seq')::int;

-- jobs that errored or timed out, with their last recorded event
select id, status, trace->'events'->-1 as last_event
from swingtrader.user_screening_results
where status = 'error'
order by run_at desc limit 20;
```

Apply the migration before first use:
`supabase/migrations/20260603000000_screening_result_trace.sql`.

---

## Key Files

| File | Purpose |
|------|---------|
| `scheduler.py` | User queue + dispatch only (`user_screening_results`). |
| `sync_crons.py` | OpenClaw: `screening-tick` + ensures `market-screening-tick` exists |
| `engine.py` | LLM agent loop (Ollama), `run_screening`, `persist_and_deliver` |
| `multi_ticker.py` | Fan-out pipeline: classify → skill recipe \| dynamic plan → per-ticker ladder → conclude |
| `skills.py` | Predefined `ScreeningSkill` recipes, deterministic analytics, `classify_skill` |
| `cli.py` | CLI entrypoint (incl. `validate-skills`, `classify`) |
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
