# services/

Python service packages for the swingtrader analytics backend. Each subdirectory is an independent service with its own README and entry points; they share data via Supabase, the FMP API, and a small set of shared utilities under `shared/`.

---

## Service map

```
                            ┌──────────────────────────┐
                            │  Supabase (swingtrader)  │
                            └─────────┬────────────────┘
                                      │
        ┌─────────────────────────────┼─────────────────────────────┐
        │ writes news + impact        │ reads everything             │
        │                             │                              │
┌───────▼────────┐         ┌──────────▼─────────┐         ┌──────────▼────────────┐
│ news/          │         │ rag/               │         │ screener/             │
│ Score articles │         │ Read-only data     │         │ Full-market scan      │
│ + embeddings + │◀────────│ access layer + LLM │         │ (Minervini trend      │
│ daily          │         │ tool schemas (used │         │ template, NYSE+       │
│ narrative      │         │ by every agent)    │         │ NASDAQ, FMP)          │
└────────────────┘         └─────────┬──────────┘         └───────────────────────┘
                                     │
        ┌────────────────────────────┼────────────────────────────┐
        │                            │                            │
┌───────▼─────────┐  ┌───────────────▼───┐  ┌───────────────┐  ┌──▼────────────┐
│ agent_core/     │  │ agent/            │  │ bulk_analysis/│  │ podcast/      │
│ Shared LLM      │◀─│ Scheduled         │  │ Per-ticker    │  │ Daily audio   │
│ tool-call loop  │  │ screening agent   │  │ technical     │  │ digest →      │
│ + tool registry │  │ (LLM + Telegram)  │  │ analysis      │  │ ElevenLabs +  │
│ + market tools  │  │                   │  │ worker        │  │ RSS           │
└─────┬───────────┘  └───────────────────┘  └───────────────┘  └───────────────┘
      │
      └──▶ also used by: scripts/generate_blog_post.py, services/news/llm
```

---

## What lives where

| Service | Role | Entry point |
|---|---|---|
| [`agent_core/`](agent_core/README.md) | Shared LLM plumbing — streaming Ollama tool-call loop, tool registry, base market tools. Used by every other LLM-calling service. | `simple_chat`, `run_tool_loop`, `build_market_registry` |
| [`agent/`](agent/README.md) | Scheduled **user** screening agent (LLM + Telegram). Own OpenClaw cron `screening-tick` → `agent.cli tick`. | `python -m services.agent.cli {tick,run,setup-cron,fmp-test}` |
| [`market_screenings/`](market_screenings/README.md) | Script-backed shared screenings: own scheduler + OpenClaw cron `market-screening-tick`; cron date logic shared via `shared/screening_schedule.py`. | `python -m services.market_screenings.cli {tick,run,setup-cron}` |
| [`bulk_analysis/`](bulk_analysis/README.md) | Per-ticker technical-analysis worker. UI inserts a job row → cron tick dispatches a subprocess that fetches OHLCV, runs LLM analysis, writes to chat workspace. | `python -m services.bulk_analysis.cli {tick,run}` |
| [`news/`](news/README.md) | News ingestion + impact scoring + embeddings + daily narrative. The factor-scoring core that feeds every other service. | `score_cli`, `embeddings_cli`, `narrative_generator` |
| [`podcast/`](podcast/README.md) | Daily audio digest: LLM script → ElevenLabs → MP3 → RSS. Telegram approval gate. | `python scripts/run_podcast.py` |
| [`rag/`](rag/README.md) | Read-only data access layer. Wraps Supabase queries (clusters, dimensions, ticker sentiment, semantic search). Defines the canonical LLM tool schemas. | Imported as a library |
| [`screener/`](screener/README.md) | Full-market scan (NYSE + NASDAQ) using Minervini's trend template. Persists to `scan_jobs` + the screenings HTTP API. | `services.screener.engine.run` |

---

## Data flow

```
News ingestion (news/scoring) ─▶ news_articles + news_impact_vectors
                                  │
                                  ├─▶ news/embeddings (chunk + vector) ─▶ news_chunk_embeddings
                                  │
                                  ├─▶ news/narrative ──▶ user_daily_narratives
                                  │
                                  ▼
                                rag/ ──┬─▶ agent/         (screening triggers)
                                       ├─▶ bulk_analysis/ (per-ticker workspaces)
                                       └─▶ podcast/       (daily digest)
```

The screener (`services/screener/`) lives outside this graph — it's a pure FMP-driven scan that produces `scan_jobs` rows independently of the news pipeline. Other services consume those rows (e.g. bulk_analysis joins user-pinned tickers from a scan run).

**Market screenings** use a **separate** OpenClaw minute cron (`market-screening-tick`) → `services.market_screenings.cli tick` → queue/dispatch `market_screening_results` → `market_screenings.cli run` for each job. They share **`shared/screening_schedule.py`** with the agent for identical `next_run_at` / croniter behavior (see [`market_screenings/README.md`](market_screenings/README.md)).

---

## Shared infrastructure

These live in `shared/` (sibling to `services/`), not in any one service:

- `shared/db.py` — Supabase client factory, `_as_json` helper, `swingtrader` schema constant
- `shared/screening_schedule.py` — cron + timezone helpers for `services.agent.scheduler` and `services.market_screenings.scheduler`
- `shared/logging.py` — structured logger
- `shared/telegram.py` — Telegram chat lookup + chunked send + delivery logging
- `shared/health.py` — `JobHeartbeat` context manager for cron jobs

When in doubt about where a helper belongs: if **two or more services** would need it, it goes in `shared/`. If only one service needs it, keep it inside that service's package.

---

## Conventions

- **Async-first for I/O.** LLM calls, HTTP fetches, Supabase writes that go in batches — all `async`. Use `asyncio.to_thread` to wrap sync DB calls inside an event loop.
- **No direct Ollama calls in new code.** Use `services.agent_core.simple_chat` (one-shot) or `run_tool_loop` (tool-calling). The package handles streaming + retry + heartbeat. See [`agent_core/README.md`](agent_core/README.md).
- **Read-only data access goes through `rag/`.** If you need cluster trends, ticker sentiment, top articles, semantic news search, or company vectors, import from `services.rag` rather than re-querying Supabase.
- **One CLI per service, exposed via `python -m services.{name}.cli`.** Subcommands like `tick` (cron tick) and `run <id>` (one job) are the standard pattern.
- **Cron tick + subprocess dispatch is the standard scheduler shape.** See `services/agent/scheduler.py`, `services/market_screenings/scheduler.py`, and `services/bulk_analysis/scheduler.py` — same skeleton (cleanup stuck jobs, count running, dispatch subprocesses up to a concurrency cap).

---

## Adding a new service

1. Create `services/<name>/` with `__init__.py`, `cli.py`, and the modules it needs.
2. If it queries Supabase for market data, use `services.rag` — don't write new query helpers unless they're genuinely service-specific.
3. If it calls an LLM, use `services.agent_core` — do not implement another streaming loop.
4. If it needs a scheduler, copy the shape of `services/agent/scheduler.py`.
5. Add a `README.md` matching the structure of the existing service READMEs (overview → architecture diagram → key files → env vars → CLI commands).
6. Add a row to the **What lives where** table in this README.
