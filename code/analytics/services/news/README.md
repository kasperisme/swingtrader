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
        └──▶ news_chunk_embeddings (pgvector, gte-small)
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
| `embeddings/` | Vector pipeline: chunk articles, embed via gte-small, write to `news_chunk_embeddings`. Also the semantic retrieval helper used by every search-the-news caller. |
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
embeddings.py            ─▶ chunk + embed articles → news_chunk_embeddings (pgvector)
gte_backfill.py          ─▶ one-shot backfill for the gte-small migration
embeddings_cli.py        ─▶ batched job runner (consumes the queue from scoring)
semantic_retrieval.py    ─▶ search_news_embeddings(query, lookback_hours, tickers, limit)
```

`semantic_retrieval.search_news_embeddings` is the single entry point for "find recent articles that match this query / are about these tickers." Used by the blog generator, podcast research agent, and the RAG `search_news` tool.

Embedding model: gte-small via Ollama (`/api/embeddings`). Calls are sub-second so streaming isn't relevant.

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
