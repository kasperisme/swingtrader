---
name: screen-agent
---

# Screen Agent — OpenClaw Setup

## Architecture

The screen agent uses a **sync-and-delegate** pattern with OpenClaw:

```
Supabase (screenings) ←→ sync cron (every 1m) ←→ OpenClaw per-screening cron jobs
                                                            │
                                                            ▼
                                                    Python agent (Ollama + tools)
                                                            │
                                                    ┌───────┼───────┐
                                                    ▼       ▼       ▼
                                              Data tools  LLM    Telegram
```

- **OpenClaw** owns scheduling, retries, timezone handling, and force-runs
- **Python** owns the LLM agent loop, data tools, evaluation, and delivery
- **Supabase** owns state (screening definitions, results, test requests)

## Components

| Component | Location | Role |
|-----------|----------|------|
| Sync cron | `openclaw cron: screen-agent-sync` | Reconciles Supabase → OpenClaw cron jobs every minute |
| Per-screening cron | `openclaw cron: screening-<uuid>` | Runs individual screenings on user's schedule |
| Sync script | `code/analytics/screen_agent/sync_crons.py` | Creates/updates/removes OpenClaw cron jobs |
| Agent engine | `code/analytics/screen_agent/engine.py` | LLM agent loop, tool calling, Telegram delivery |
| Data tools | `code/analytics/screen_agent/data_queries.py` | 11 Supabase query tools (market-wide + user-specific) |
| CLI | `code/analytics/screen_agent/cli.py` | `run <id>`, `sync` commands |
| UI | `code/ui/app/protected/agents/` | Create/manage/test screenings |
| Server actions | `code/ui/app/actions/screenings-agent.ts` | CRUD + test request via Supabase |
| Migration | `code/analytics/supabase/migrations/20260425000000_scheduled_screening_agent.sql` | DB tables + RLS |

## Setup

### 1. Run the database migration

```bash
cd ~/projects/swingtrader/code/analytics
# Apply via Supabase dashboard SQL editor or psql:
psql "$SUPABASE_DB_DIRECT_URL" -f supabase/migrations/20260425000000_scheduled_screening_agent.sql
```

### 2. Verify the Python environment

```bash
cd ~/projects/swingtrader/code/analytics
.venv/bin/python -c "from screen_agent.engine import run_screening; print('OK')"
.venv/bin/python -c "from screen_agent.sync_crons import run_sync; print('OK')"
```

### 3. Register the sync cron in OpenClaw

This is the **only** cron job you need to create manually. It syncs every minute and manages all per-screening jobs automatically.

```bash
openclaw cron add \
  --name "screen-agent-sync" \
  --every 1m \
  --session isolated \
  --no-deliver \
  --timeout 30000 \
  --message "Sync screening cron jobs. Execute: cd ~/projects/swingtrader/code/analytics && .venv/bin/python -m screen_agent.cli sync"
```

That's it. The sync cron handles everything else.

## How it works

### Scheduled runs

1. User creates a screening in the UI with a prompt and schedule (e.g. `0 7 * * 1-5`, timezone `America/New_York`)
2. Server action inserts row into `user_scheduled_screenings` in Supabase
3. Within 1 minute, the sync cron picks up the new row and creates an OpenClaw cron job named `screening-<uuid>` with the user's cron expression and timezone
4. OpenClaw runs the job on schedule, executing: `.venv/bin/python -m screen_agent.cli run <screening-id>`
5. The Python agent runs the LLM loop with all data tools, evaluates the prompt, persists the result, and delivers via Telegram if triggered

### Test runs

1. User clicks the "Test run" button (lightning bolt) in the UI
2. Server action sets `run_requested_at = NOW()` on the screening row
3. Within 1 minute, the sync cron detects it and calls `openclaw cron run <job-id>` to force-execute immediately
4. The Python agent runs identically to a scheduled run (including Telegram delivery) but marks the result with `is_test = true`
5. The UI polls `user_screening_results` for the test result and displays it inline

### Sync behavior

The sync script (`sync_crons.py`) runs every minute and:

| State change | Action |
|-------------|--------|
| New active screening in Supabase | Create OpenClaw cron job |
| Screening schedule/timezone updated | Update OpenClaw cron job |
| Screening paused | Remove OpenClaw cron job |
| Screening deleted | Remove OpenClaw cron job |
| Screening has `run_requested_at` set | Force-run the OpenClaw cron job |

## Data tools available to the agent

### Market-wide (no user scope)

| Tool | Description |
|------|-------------|
| `get_cluster_trends` | 9-cluster sentiment scores |
| `get_dimension_trends` | Per-dimension sentiment within clusters |
| `get_ticker_sentiment` | Per-article per-ticker sentiment |
| `get_top_articles` | Top articles with impact vectors |
| `get_ticker_relationships` | Graph neighborhood around a ticker |
| `get_company_vectors` | Company factor dimension profiles |
| `get_ticker_news` | Per-ticker articles with sentiment + relationship annotations |
| `search_news` | Semantic vector search over articles |

### User-specific (scoped to screening's user_id)

| Tool | Description |
|------|-------------|
| `get_user_positions` | Open positions from user_trades |
| `get_user_alerts` | Active stop-loss/take-profit/price alerts with latest prices |
| `get_user_screening_notes` | Active screening watchlist tickers |

All tools are available to all users regardless of plan tier. Plan gates only control screening count and minimum schedule interval.

## Plan gates

| Plan | Max screenings | Min schedule |
|------|---------------|-------------|
| Observer | 1 | `0 7 * * 1-5` (weekdays 7am) |
| Investor | 5 | `0 */4 * * *` (every 4h) |
| Trader | 25 | `*/15 * * * *` (every 15m) |

## Monitoring

```bash
# List all screen-agent cron jobs
openclaw cron list | grep screening

# Check sync job status
openclaw cron list | grep sync

# Run a screening manually
openclaw cron run <job-id>

# View run history
openclaw cron runs --id <job-id> --limit 10

# Dry-run a screening (no DB writes, no delivery)
cd ~/projects/swingtrader/code/analytics
.venv/bin/python -m screen_agent.cli run <screening-id> --dry-run
```

## Adding new data tools

1. Add the function to `code/analytics/screen_agent/data_queries.py`
2. Add it to `_TOOL_MAP` (market-wide) or `_TOOL_MAP_USER` (user-specific) in `engine.py`
3. Add a `_TOOL_SCHEMAS` entry describing the parameters for the LLM
4. Describe it in `_AGENT_SYSTEM` system prompt
5. If user-specific, ensure it accepts `user_id` and the engine injects it

## Troubleshooting

**Screening not running on schedule:**
- Check `openclaw cron list` for the `screening-<uuid>` job
- Check sync cron is running: `openclaw cron list | grep sync`
- Manually sync: `.venv/bin/python -m screen_agent.cli sync`

**Test button times out:**
- Verify the sync cron is running
- Check `run_requested_at` is set: query `user_scheduled_screenings` in Supabase
- Force-run manually: `openclaw cron run <job-id>`

**Agent returns unexpected results:**
- Dry-run to inspect: `.venv/bin/python -m screen_agent.cli run <id> --dry-run`
- Check Ollama is running: `curl http://localhost:11434/api/tags`
- Check the system prompt in `engine.py` for tool descriptions
