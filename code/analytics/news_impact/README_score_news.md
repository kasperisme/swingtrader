# score_news_cli

Embeds a news article into an impact vector by running 8 parallel local LLM calls — one per dimension cluster — then optionally scores a list of companies against that vector to surface tailwinds and headwinds.

Requires [Ollama](https://ollama.com) running locally with a model pulled (default: `devstral`).

## Usage

```bash
# Embed article only — no tickers needed
python -m news_impact.score_news_cli --text "Fed raises rates 50bps..."
python -m news_impact.score_news_cli --url "https://..."
python -m news_impact.score_news_cli --file article.txt

# Embed + score specific companies (tailwinds/headwinds)
python -m news_impact.score_news_cli --text "..." --tickers AAPL MSFT NVDA JPM XOM --score-companies

# Optional metadata + debug logging (single-article mode)
python -m news_impact.score_news_cli --text "..." --title "Headline" --source reuters --published-at "2026-01-15T12:00:00" -v

# Use cached company vectors (from build_vectors_cli cache)
python -m news_impact.score_news_cli --text "..." --tickers AAPL MSFT --use-cache --score-companies

# Re-score an article already in the DB (overwrites stored heads + vector)
python -m news_impact.score_news_cli --text "..." --refresh

# Score without writing to Supabase
python -m news_impact.score_news_cli --text "..." --no-persist

# Fetch and score latest FMP stock news (market-wide Stock News Feed API)
# → GET https://financialmodelingprep.com/stable/news/stock-latest?page=0&limit=20
python -m news_impact.score_news_cli --fmp-news
python -m news_impact.score_news_cli --fmp-news --limit 30

# Fetch FMP news for specific tickers (Search Stock News API — stable/news/stock?symbols=...)
python -m news_impact.score_news_cli --fmp-news --tickers AAPL MSFT NVDA

# Fetch FMP news for a date window (inclusive)
python -m news_impact.score_news_cli --fmp-news --from 2025-11-01 --to 2025-11-30

# Date window + ticker filter
python -m news_impact.score_news_cli --fmp-news --tickers AAPL --from 2025-11-01 --to 2025-11-30

# Paginate through older FMP news
python -m news_impact.score_news_cli --fmp-news --limit 20 --page 2

# General News API (headlines/snippets/URLs; symbol often null)
# → GET https://financialmodelingprep.com/stable/news/general-latest?page=0&limit=20
python -m news_impact.score_news_cli --fmp-news --fmp-news-feed general

# Stock + general in one run (merged, URL-deduped)
python -m news_impact.score_news_cli --fmp-news --fmp-news-feed both --limit 40

# Pick the sparsest UTC calendar day in the last N days (by DB row counts), then ingest until M new rows exist
#
python -m news_impact.score_news_cli --fmp-news --sparse-fill N_DAYS M_NEW
python -m news_impact.score_news_cli --fmp-news --sparse-fill 30 10

# Same, but loop: fill the sparsest day, then the next sparsest, until every day in the window had a turn
python -m news_impact.score_news_cli --fmp-news --sparse-fill 30 10 --sparse-fill-loop
```

## Options

### Article source (mutually exclusive, one required)

| Flag          | Description                                                            |
| ------------- | ---------------------------------------------------------------------- |
| `--url URL`   | Fetch article from a URL (fetches full article, falls back to summary) |
| `--text TEXT` | Article text supplied inline                                           |
| `--file PATH` | Read article text from a local file                                    |
| `--fmp-news`  | Fetch news from FMP stable APIs and score each article (see `--fmp-news-feed`) |

### FMP news options (only with `--fmp-news`)

| Flag                         | Default | Description                                                                                                                                                                                                                                                                    |
| ---------------------------- | ------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `--fmp-news-feed FEED`       | `stock` | `stock` → `news/stock-latest` or `news/stock?symbols=…` if `--tickers`. `general` → `news/general-latest` (market-wide). `both` → fetch stock + general in parallel and merge (dedupe by URL).                                                                                |
| `--limit N`                  | `20`    | Max articles to fetch per FMP request (FMP max: `250`)                                                                                                                                                                                                                         |
| `--page N`                   | `0`     | Page offset for pagination (0-indexed; FMP max: `100`)                                                                                                                                                                                                                         |
| `--from YYYY-MM-DD`          | —       | Start date filter for FMP fetch (inclusive)                                                                                                                                                                                                                                    |
| `--to YYYY-MM-DD`            | —       | End date filter for FMP fetch (inclusive)                                                                                                                                                                                                                                      |
| `--sparse-fill N_DAYS M_NEW` | —       | Query `news_articles` for per-day counts (UTC); choose the day with the fewest rows (earliest day on ties); fetch that day from FMP and paginate until `M_NEW` **new inserts** or API exhaustion. Overrides `--from`, `--to`, and `--page`. Requires DB (omit `--no-persist`). |
| `--sparse-fill-loop`         | off     | With `--sparse-fill`: after each day’s run, re-query counts and process the **next** sparsest day (skipping days already done this run) until each day in the N-day window has had one pass. |

### Tickers and company scoring

| Flag                   | Default | Description                                                                                                                                                                                                |
| ---------------------- | ------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `--tickers TICKER ...` | —       | **Non–FMP:** Explicit symbols (merged with LLM-extracted; persisted to `news_article_tickers`). **FMP stock / both:** Uses `news/stock?symbols=…` when set; else `stock-latest`. **FMP general:** Does not filter the API; symbols are only added as explicit tags after scoring. Company tailwinds/headwinds require `--score-companies`. |
| `--score-companies`    | off     | Build/load company vectors and print tailwinds/headwinds (otherwise only impact clusters and extracted tickers are shown).                                                                                 |
| `--use-cache`          | off     | Load company vectors from the on-disk cache from `build_vectors_cli` (avoids refetching fundamentals from FMP where cached).                                                                               |
| `--top-n N`            | `6`     | Max companies shown per side (tailwinds vs headwinds) when `--score-companies` is on.                                                                                                                      |

### Article metadata (stored when persisting)

| Flag                 | Description                                                      |
| -------------------- | ---------------------------------------------------------------- |
| `--title TITLE`      | Article title                                                    |
| `--published-at ISO` | Publication time stored and printed (e.g. `2026-04-08T14:30:00`) |
| `--source SOURCE`    | Source label (e.g. `bloomberg`, `fmp`)                           |

### Persistence

| Flag           | Description                                                                       |
| -------------- | --------------------------------------------------------------------------------- |
| `--no-persist` | Score without writing to Supabase (`news_articles`, heads, vectors, tickers).     |
| `--refresh`    | Re-score even if the article already exists (overwrites stored heads and vector). |

### Other

| Flag                       | Description                                                                                    |
| -------------------------- | ---------------------------------------------------------------------------------------------- |
| `--news-impact-backend`    | `ollama`, `anthropic`, or `do_agent` — overrides `NEWS_IMPACT_BACKEND` (default: env / ollama) |
| `--ollama-impact-model`    | Overrides `OLLAMA_IMPACT_MODEL` for this run when using the Ollama backend.                    |
| `--verbose` / `-v`         | Debug logging                                                                                  |

### Date range filtering with `--from` / `--to`

Use `--from` and `--to` with `--fmp-news` to constrain fetches to a specific date range.

- Format: `YYYY-MM-DD` (for example: `2025-11-01`)
- Can be used independently:
  - `--from` only: fetch from that date onward
  - `--to` only: fetch up to that date
- Can be combined with `--tickers`, `--limit`, and `--page`

### Embedding pipeline (split job)

`score_news_cli` now enqueues `news_article_embedding_jobs` when articles are persisted.
Run the worker separately:

```bash
# Queue any old rows missing jobs/embeddings
python -m news_impact.embeddings_cli --enqueue-missing --limit 500

# Process pending jobs (Ollama embeddings)
python -m news_impact.embeddings_cli --process-pending --limit 100

# Retry failed jobs
python -m news_impact.embeddings_cli --process-pending --retry-failed --limit 200

# Cleanup orphan rows
python -m news_impact.embeddings_cli --cleanup-orphans
```

Environment:
- `OLLAMA_BASE_URL` (default `http://localhost:11434`)
- `OLLAMA_EMBED_MODEL` (default `mxbai-embed-large`)

Examples:

```bash
# Entire month window
python -m news_impact.score_news_cli --fmp-news --from 2025-11-01 --to 2025-11-30

# From a date onward
python -m news_impact.score_news_cli --fmp-news --from 2025-11-01

# Up to a date
python -m news_impact.score_news_cli --fmp-news --to 2025-11-30
```

### Complete option reference (every flag)

| Flag                         | Default | Description                                                             |
| ---------------------------- | ------- | ----------------------------------------------------------------------- |
| `--file PATH`                | —       | Read article text from a file (source mode).                            |
| `--fmp-news`                 | off     | Batch mode: fetch and score stock news from FMP.                        |
| `--from DATE`                | —       | FMP: inclusive start date (`YYYY-MM-DD`).                               |
| `--limit N`                  | `20`    | FMP: max articles per request (≤ 250).                                  |
| `--news-impact-backend`      | —       | `ollama`, `anthropic`, or `do_agent`; overrides `NEWS_IMPACT_BACKEND`.   |
| `--ollama-impact-model`      | —       | Ollama model name; overrides `OLLAMA_IMPACT_MODEL` for this run.        |
| `--no-persist`               | off     | Do not write to Supabase.                                               |
| `--page N`                   | `0`     | FMP: pagination index (≤ 100).                                          |
| `--published-at ISO`         | —       | Stored publication timestamp.                                           |
| `--refresh`                  | off     | Re-score existing DB article.                                           |
| `--score-companies`          | off     | Compute tailwinds/headwinds vs company vectors.                         |
| `--sparse-fill N_DAYS M_NEW` | —       | FMP: fill sparsest UTC day in the last `N_DAYS` until `M_NEW` new rows. |
| `--sparse-fill-loop`         | off     | After each sparse day, continue with the next sparsest (see FMP options). |
| `--source SOURCE`            | —       | Stored source label.                                                    |
| `--text TEXT`                | —       | Inline article body (source mode).                                      |
| `--tickers TICK ...`         | —       | Symbols for FMP filter and/or company scoring (see above).              |
| `--title TITLE`              | —       | Stored title.                                                           |
| `--to DATE`                  | —       | FMP: inclusive end date (`YYYY-MM-DD`).                                 |
| `--top-n N`                  | `6`     | Max companies per tailwind/headwind side.                               |
| `--url URL`                  | —       | Fetch article from URL (source mode).                                   |
| `--use-cache`                | off     | Prefer on-disk company vector cache.                                    |
| `--verbose` / `-v`           | off     | Debug logging.                                                          |

## Output

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Article: Fed raises rates by 50bps, surprises markets...
article_id=3
Companies mentioned: JPM, BAC, GS

Cluster confidence:
  MACRO_SENSITIVITY      ██████████  0.94
  FINANCIAL_STRUCTURE    ████████░░  0.81
  VALUATION_POSITIONING  ██████░░░░  0.63
  SECTOR_ROTATION        █████░░░░░  0.54
  GROWTH_PROFILE         ███░░░░░░░  0.31
  GEOGRAPHY_TRADE        █░░░░░░░░░  0.14
  BUSINESS_MODEL         █░░░░░░░░░  0.09
  MARKET_BEHAVIOUR       ░░░░░░░░░░  0.03

Top signals:
  interest_rate_sensitivity    -0.87
  debt_burden                  -0.81
  sector_financials            +0.76
  valuation_multiple           -0.68
  floating_rate_debt_ratio     -0.62

TAILWINDS              HEADWINDS
  JPM   +0.81          NVDA  -0.89
  XOM   +0.44          AAPL  -0.51
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

## How it works

1. **Ticker extraction** — an LLM call identifies any publicly traded companies mentioned in the article. These are merged with any explicit `--tickers` and fetched automatically.

2. **8 cluster heads** — one LLM call per dimension cluster runs in sequence (Ollama processes one request at a time). Each head returns `scores`, `reasoning`, and `confidence` as JSON.

3. **Aggregation** — scores are weighted by each head's confidence and merged into a single impact vector: `{dimension_key: float}` in the range `[-1.0, +1.0]`.

4. **Company scoring** — each company's score is the dot product of its dimension vector (0–1 rank) and the impact vector. Positive = tailwind, negative = headwind.

5. **Persistence** — article, all 8 head responses, and the aggregated vector are stored in Supabase. Duplicate articles (same sha256) return the cached result unless `--refresh` is passed.

6. **Embedding queue hook** — when a row is persisted, `score_news_cli` enqueues a
   job in `news_article_embedding_jobs` for async chunk embedding by
   `news_impact.embeddings_cli` (split pipeline).

## Supabase tables (swingtrader schema)

| Table                  | Contents                                                                              |
| ---------------------- | ------------------------------------------------------------------------------------- |
| `news_articles`        | One row per article (deduped by sha256 of body)                                       |
| `news_impact_heads`    | 8 rows per article — one per cluster (scores, reasoning, confidence)                  |
| `news_impact_vectors`  | Aggregated impact vector per article (`impact_json`, `top_dimensions`)                |
| `news_article_tickers` | Ticker mentions per article — `source` is `extracted` (LLM) or `explicit` (--tickers) |
| `news_article_embedding_jobs` | Async embedding queue + status (`pending`, `processing`, `completed`, `failed`) |
| `news_article_embeddings` | Chunk embeddings for retrieval (default: `mxbai-embed-large`, `vector(1024)`) |

## Environment variables

| Variable                 | Default                   | Description                                                                 |
| ------------------------ | ------------------------- | --------------------------------------------------------------------------- |
| `NEWS_IMPACT_BACKEND`    | `ollama`                  | `ollama`, `anthropic`, or `do_agent`. Override: `--news-impact-backend`.   |
| `OLLAMA_IMPACT_MODEL`    | `devstral`                | Ollama model name                                                           |
| `OLLAMA_BASE_URL`        | `http://localhost:11434`  | Ollama endpoint                                                             |
| `OLLAMA_CONCURRENCY`     | `1`                       | Concurrent Ollama requests (keep at 1 for single-GPU)                       |
| `OLLAMA_TIMEOUT`         | `120`                     | Per-request timeout (Ollama; fallback for `do_agent` if unset)              |
| `OLLAMA_NUM_PREDICT`     | `1024`                    | Max tokens per LLM response                                                 |
| `DO_GENAI_AGENT_BASE_URL`| see `do_agent_client`     | DigitalOcean GenAI Agent base URL (no trailing slash)                       |
| `DO_GENAI_AGENT_API_KEY` | —                         | Bearer token for `/api/v1/chat/completions`                                |
| `DO_GENAI_AGENT_TIMEOUT` | `120`                     | Per-request timeout for GenAI Agent                                         |
| `DO_GENAI_AGENT_MAX_TOKENS` | `4096`                 | Max completion tokens (reasoning models often need ≥4k to finish JSON)      |
| `DO_GENAI_AGENT_MODEL`   | `do-agent`                | Label stored in head rows (agent picks model server-side)                   |
| `DO_GENAI_AGENT_CONCURRENCY` | `4`                   | Parallel head requests against GenAI Agent                                  |
| `DO_GENAI_AGENT_RETRIEVAL` | `none`                  | `none` \| `rewrite` \| `step_back` \| `sub_queries` (RAG behaviour)         |
| `DO_GENAI_AGENT_LOG_FULL_RESPONSE` | off             | Set to `1` / `true` / `yes` to print each raw HTTP body to **stderr** (debug). |
| `ANTHROPIC_API_KEY`      | —                         | Required when `NEWS_IMPACT_BACKEND=anthropic`                                 |
| `ANTHROPIC_IMPACT_MODEL` | `claude-haiku-4-5-...`    | Anthropic model id                                                          |
| `ANTHROPIC_CONCURRENCY`  | `8`                       | Parallel heads (anthropic); falls back to `OLLAMA_CONCURRENCY` if set      |
| `ANTHROPIC_TIMEOUT`      | `60`                      | Per-request timeout (anthropic)                                              |
| `FMP_API_KEY`            | —                         | Required only when fetching company vectors                                 |
| `HANS_DUCKDB_PATH`       | `data/swingtrader.duckdb` | DuckDB file path                                                            |
| `OLLAMA_EMBED_MODEL`     | `mxbai-embed-large`       | Model used by `embeddings_cli` and semantic retrieval query embedding       |
| `USE_SEMANTIC_RETRIEVAL` | `true`                    | Enable semantic evidence retrieval in daily narrative + blog generation      |

For GenAI Agent: models such as Qwen3 may leave `content` empty and put text in `reasoning_content`; the client uses that as a fallback. If JSON responses truncate, increase `DO_GENAI_AGENT_MAX_TOKENS`.

## Pulling the default model

```bash
ollama pull devstral
```

Faster alternatives (lower quality): `qwen2.5:7b`, `llama3.2:3b`

### DigitalOcean GenAI Agent (`do_agent`)

The scorer calls `POST /api/v1/chat/completions` with Bearer auth (OpenAI-style `messages`, `stream: false`). Discover parameters on your deployment via `https://<agent-host>/openapi.json`. Set `NEWS_IMPACT_BACKEND=do_agent`, `DO_GENAI_AGENT_API_KEY`, and `DO_GENAI_AGENT_BASE_URL` if not using the default in `do_agent_client.py`. Use `DO_GENAI_AGENT_RETRIEVAL=none` for scoring without knowledge-base retrieval (default).

## Related scripts/modules

- `news_impact.embeddings_cli` — queue/process/retry/cleanup embedding jobs.
- `news_impact.embeddings` — chunking + Ollama embedding + job orchestration.
- `news_impact.semantic_retrieval` — query embedding + pgvector retrieval against `news_article_embeddings`.
- `news_impact.narrative_generator` — now consumes semantic evidence in prompt context (guarded by `USE_SEMANTIC_RETRIEVAL`, default on).
- `scripts/generate_blog_post.py` — now adds semantic evidence snippets to the generation prompt (guarded by same flag).
