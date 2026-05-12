# News Pipeline

The factor-scoring core. Ingests news articles, scores their impact across factor dimensions, embeds them for semantic retrieval, and synthesises personalised pre-market briefings. Every other LLM-driven service downstream consumes its outputs.

---

## Architecture

```
External feeds (RSS, X)
        │
        ▼
news_ingester ────────────────▶ news_articles                     (dedup by URL / sha256)
        │
        ▼
impact_scorer (8 parallel LLM heads, one per cluster)
        │
        ├──▶ news_impact_vectors (per-article impact_json + top_dimensions)
        │
        ▼
embeddings_cli (chunk + vector)
        │
        └──▶ news_article_embeddings (pgvector)
                                                 │
                                                 ▼
                                       semantic_retrieval
                                                 │
                                                 ▼
                                ┌────────────────┴────────────────┐
                                │                                 │
                          narrative_generator           services/rag → consumed by
                                │                       agents (screening, podcast,
                                ▼                       bulk analysis)
                          user_daily_narratives
                                │
                                ▼
                          Telegram delivery
```

---

## Subpackages

| Subpackage | Role |
|---|---|
| `scoring/` | Impact scorer + ingester. 8-cluster parallel LLM scoring → `news_articles` + `news_impact_vectors`. |
| `embeddings/` | Vector pipeline: chunk articles, embed via Ollama, write to `news_article_embeddings`. Semantic retrieval helper; optional time-bucket clustering (`cluster_news_embedding_buckets.py`). |
| `narrative/` | Daily narrative generator. Per-user pre-market briefing assembled from open positions, active screen tickers, alerts, and recent news. |
| `llm/` | LLM client wrappers — `ollama_client`, `anthropic_client`, `do_agent_client`. All three share the `chat() -> (text, latency_ms)` signature; `ollama_client` now delegates to `services.agent_core.simple_chat`. |
| `company/` | Company factor-vector builder. Computes per-ticker dimension exposures (macro sensitivity, sector rotation, etc.) used to score news against companies. |

---

## scoring/

```
news_ingester.py  ─▶ fetches feeds, dedupes, persists raw articles
score_cli.py      ─▶ enqueues unscored article IDs
impact_scorer.py  ─▶ 8 parallel LLM heads (one per cluster), aggregate to one impact_json
dimensions.py     ─▶ canonical cluster + dimension definitions
x_fetcher.py      ─▶ pulls X (Twitter) posts as a news source
```

Each cluster head is independent — one head failing never blocks the others. Output is the per-article `impact_json` (dimension → score in `[-1, +1]`) plus the top dimensions by absolute magnitude.

---

## embeddings/

```
embeddings.py                 ─▶ chunk + embed articles → news_article_embeddings (pgvector)
gte_backfill.py               ─▶ one-shot backfill for the gte-small migration
embeddings_cli.py             ─▶ batched job runner (consumes the queue from scoring)
semantic_retrieval.py         ─▶ search_news_embeddings(query, lookback_hours, tickers, limit)
time_bucket_clustering.py    ─▶ hourly/daily K-means over embeddings (see clustering below)
```

`semantic_retrieval.search_news_embeddings` is the single entry point for "find recent articles that match this query / are about these tickers." Used by the blog generator, podcast research agent, and the RAG `search_news` tool.

Embedding model: primary pipeline uses Ollama (`OLLAMA_EMBED_MODEL`, default `mxbai-embed-large` in code paths that reference it). `gte_backfill.py` targets `news_article_embeddings_gte`.

### Time-bucket embedding clusters (hourly / daily)

K-means clusters over `news_article_embeddings` in **UTC** windows: each **hour** `[bucket, bucket+1h)` or each **calendar day** `[midnight, midnight+1d)`. For each cluster, **Ollama** (`/api/chat`, non-streaming) reads numbered excerpts from member chunks in that bucket and writes a short **theme label** into `reverse_embedding_text`. `reverse_embedding_article_id` / `reverse_embedding_chunk_index` point at the chunk **nearest the centroid** within the cluster (anchor, not the full label source). If Ollama errors, the label falls back to that nearest chunk’s text.

**1. Apply the migration** (creates hourly + daily table families; drops legacy `news_embedding_time_cluster_*` if present):

```bash
# From repo root or analytics — use your usual Supabase workflow, e.g.
cd code/analytics && supabase db push
# or apply: supabase/migrations/20260512140000_news_embedding_time_clusters.sql
```

**2. Configure `code/analytics/.env`** (same as other DB scripts):

- `SUPABASE_DB_DIRECT_URL` **or** `SUPABASE_URL` + `SUPABASE_DB_PWD` (direct Postgres for `psycopg2`)
- Optional: `SUPABASE_SCHEMA` (default `swingtrader`)
- Optional: `OLLAMA_EMBED_MODEL` — must match `news_article_embeddings.embedding_model` for the rows you cluster (default in script: `mxbai-embed-large`)
- **Ollama for labels:** `OLLAMA_BASE_URL` (default `http://localhost:11434`), `OLLAMA_CLUSTER_LABEL_MODEL` or fallbacks `OLLAMA_IMPACT_MODEL` → `OLLAMA_NARRATIVE_MODEL` → `llama3.2` (see `default_label_model()` in `time_bucket_clustering.py`).

**3. Run the CLI** from `code/analytics` (bootstrap matches `scripts/generate_blog_post.py`). **Ollama must be reachable** unless you only use `--dry-run` (no labels written).

```bash
cd code/analytics

# Hourly buckets in a UTC half-open range [since, until)
python scripts/cluster_news_embedding_buckets.py --granularity hour --since 2026-05-10 --until 2026-05-12

# Daily buckets (UTC calendar days)
python scripts/cluster_news_embedding_buckets.py --granularity day --since 2026-05-01 --until 2026-05-13

# Dry run (no DB writes; no Ollama calls; prints JSON summary per bucket)
python scripts/cluster_news_embedding_buckets.py --granularity day --since 2026-05-01 --dry-run

# Explicit embedding + chat models
python scripts/cluster_news_embedding_buckets.py --granularity hour --since 2026-05-10 --until 2026-05-11 --embed-model mxbai-embed-large --label-model llama3.2

# Tunables: --max-k, --min-per-cluster, --random-state, --ollama-timeout (per cluster),
#   --max-cluster-chars (excerpt budget per cluster prompt), --ollama-base-url, -v
```

**Notes**

- `--since` / `--until` accept `YYYY-MM-DD` (interpreted as **UTC midnight**) or full ISO datetimes. **`until` is exclusive**: to include all of `2026-05-12` for daily runs, pass `--until 2026-05-13`.
- Run **twice** (once `--granularity hour`, once `--granularity day`) to populate both table sets.
- Writes go to `news_embedding_hourly_cluster_{runs,centroids,articles}` and `news_embedding_daily_cluster_{runs,centroids,articles}`. Re-running the same `(bucket_start, embedding_model)` replaces that bucket’s rows.
- Cost: **one Ollama `/api/chat` per cluster** after K-means (e.g. 20 clusters ⇒ 20 calls per bucket).

---

## narrative/

`narrative_generator.py` — synthesises a personalised pre-market briefing for each opted-in user.

Inputs per user:
- Open positions (computed from `user_trades`)
- Active screening tickers (`scan_row_notes` where status indicates active interest)
- Price alerts
- Recent news scoped to the user's tickers, expanded via the relationship graph
- Semantic retrieval over the broader news corpus

Output: one structured-JSON narrative split into named sections (portfolio pulse, screening watch, related-news, alerts, market pulse), persisted to `user_daily_narratives` and delivered via Telegram.

LLM call: `services.news.llm.ollama_client.chat()` — which now goes through `services.agent_core.simple_chat` for streaming + retry.

---

## llm/

Three interchangeable client wrappers. All three expose:

```python
async def chat(prompt, system, model=None, timeout=60.0, num_predict=None) -> tuple[str, int]:
    ...

class ChatError(Exception): ...
```

| Client | Backend | Used by |
|---|---|---|
| `ollama_client` | Ollama (local + cloud `:cloud` models). Wraps `services.agent_core.simple_chat`. | `narrative_generator` (current) |
| `anthropic_client` | Anthropic API (Claude). Drop-in replacement for ollama_client. | Available; in-progress migration target. |
| `do_agent_client` | DigitalOcean GenAI Agent (OpenAI-compatible). | Available alternative backend. |

Add new backends here, not inside the consumer modules.

---

## company/

`company_scorer.py`, `company_vector.py`, `dimension_calculator.py`, `normaliser.py`, `fmp_fetcher.py` — build the per-ticker factor vector. Output is `company_vectors.dimensions_json` (rank-normalised 0–1 per dimension), which feeds into ticker-level news scoring (an article's impact applied to a ticker is a dot-product of its impact vector with the company's exposure vector).

Two CLIs:
- `build_vectors_cli.py` — recompute company vectors from current FMP data.
- `dimension_significance_cli.py` — diagnostic, ranks dimensions by signal-to-noise.

---

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama server (local daemon proxies to cloud for `:cloud` models). |
| `OLLAMA_IMPACT_MODEL` | `devstral` | Default model for `ollama_client.chat`. |
| `OLLAMA_NUM_PREDICT` | `1024` | Default max tokens for `ollama_client.chat`. |
| `ANTHROPIC_API_KEY` | required for `anthropic_client` | |
| `ANTHROPIC_IMPACT_MODEL` | `claude-haiku-4-5-20251001` | |
| `DO_GENAI_AGENT_BASE_URL` | required for `do_agent_client` | |
| `DO_GENAI_AGENT_API_KEY` | required for `do_agent_client` | |
| `FMP_API_KEY` | required for `company/` builders | |

---

## DB tables touched

- `news_articles` — written by `scoring/news_ingester`.
- `news_impact_vectors` — written by `scoring/impact_scorer`.
- `news_chunk_embeddings` — written by `embeddings/embeddings_cli`.
- `news_article_tickers` — many-to-many ticker → article join table.
- `company_vectors` — written by `company/build_vectors_cli`.
- `user_daily_narratives` — written by `narrative_generator`.
