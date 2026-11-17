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
services/rag.search_news (tag overlap → Postgres full-text over news_articles)
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

## Retired: embeddings/ (Nov 2026)

The vector pipeline (`embeddings_cli` → `news_article_embeddings`, pgvector, plus
the hourly/daily embedding-cluster tables) was retired. The table had grown to
32 GB of a 38 GB database, its 18 GB ivfflat index had not been scanned since the
filter-first search rewrite (Sep 2026), and the agent tools had already moved to
the tag/full-text cascade for speed. Every reader now uses that cascade —
`services.rag.search_news` (Python) or the `search_news_by_tags` /
`search_news_fulltext` RPCs (UI) — and the priced-in pipeline vectorises
`news_articles.body` in memory over full-text lexemes
(`code/strategylab/strategylab/social/lexical.py`). What was given up is
meaning-level recall for queries that share no words with the article.

---

## DB tables touched

- `news_articles` — written by `scoring/news_ingester`.
- `news_impact_vectors` — written by `scoring/impact_scorer`.
- `news_article_tickers` — many-to-many ticker → article join table.
- `company_vectors` — written by `company/build_vectors_cli`.
- `user_daily_narratives` — written by `narrative_generator`.
