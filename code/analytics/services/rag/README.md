# services/rag

Read-only data access layer + the canonical LLM tool schemas.

Every service that needs to query the news impact data (cluster trends, ticker sentiment, top articles, semantic search, company vectors, user portfolios) imports from `services.rag` rather than re-querying Supabase. This means: one place defines what "the data API" looks like, one place defines the LLM tool schemas, and changes to query shape only need to land here.

---

## Why this exists

Before `rag/`, every LLM-driven service redefined its own queries against Supabase and its own tool schemas. The screening agent, podcast script generator, and narrative generator each had their own ~200 lines of "fetch top articles for these tickers in the last N hours" — slightly different in each, all sourced from the same tables.

`rag/` consolidates them. New services that need read access to the news pipeline import from here. The screening agent's `get_top_articles` is identical to the podcast research agent's `get_top_articles` because there's only one definition.

---

## Architecture

```
                                  Supabase (swingtrader schema)
                                            ▲
                                            │ read-only queries
                  ┌─────────────────────────┼──────────────────────────┐
                  │                         │                          │
              articles.py               sentiment.py                 graph.py
              ─ get_top_articles        ─ get_cluster_trends         ─ get_ticker_relationships
              ─ get_ticker_news         ─ get_dimension_trends       ─ get_company_vectors
              ─ fetch_tickers_for_      ─ get_ticker_sentiment       ─ expand_related_tickers
                articles                ─ compute_cluster_summary    ─ build_neighborhood_from_seed

              embeddings.py             portfolio.py                 screening.py
              ─ search_news             ─ get_user_positions         ─ apply_scan_filters
              ─ embed_query             ─ get_user_alerts            ─ get_filtered_tickers_from_scan
                                        ─ get_user_screening_notes
                                        ─ get_user_trading_strategy

              context.py                taxonomy.py                  company.py
              ─ get_linked_scan_run_    ─ CLUSTERS, CLUSTER_ID_TO_   ─ CompanyScore
                context                   LABEL, DIM_KEY_TO_LABEL    ─ score_companies (lazy import; pulls numpy/pandas)

                                       tools.py
                                       ─ TOOL_SCHEMAS (Ollama function-call schemas for all of the above)
                                       ─ get_market_tools() → name → fn
                                       ─ get_user_tools() → name → fn (per-user, takes user_id)
```

All exports are surfaced from `services/rag/__init__.py` — import `from services.rag import …` rather than reaching into submodules.

---

## What each module does

### Data access

| Module | Tables read | Purpose |
|---|---|---|
| `articles.py` | `news_articles`, `news_impact_vectors`, `news_article_tickers` | Top articles by impact magnitude; per-ticker article feeds; ticker-list backfill for a set of articles. |
| `sentiment.py` | `news_impact_vectors` | Cluster-level + dimension-level sentiment time series. |
| `graph.py` | `ticker_relationships`, `company_vectors` | Ticker neighborhood (1-hop / N-hop) for "show me what else is related to NVDA"; company factor vectors for downstream scoring. |
| `embeddings.py` | `news_chunk_embeddings` (pgvector) | Semantic search via `gte-small` embeddings. Resolves a query string → ranked article snippets. |
| `portfolio.py` | `user_trades`, `user_alerts`, `user_scan_row_notes`, `user_settings` | Per-user portfolio context. Each fn takes `user_id` as the first arg. |
| `screening.py` | `user_scan_runs`, `user_scan_rows` | Filter the rows of a scan run by column-level criteria; resolve filtered ticker lists for use as agent input. |
| `context.py` | `user_scan_runs` (latest) | Render a "linked scan context" string for the agent's system prompt — the active screening's results in compact form. |

### Schemas + taxonomy

| Module | Purpose |
|---|---|
| `taxonomy.py` | Canonical cluster + dimension definitions. Source of truth for `MACRO_SENSITIVITY`, `SECTOR_ROTATION`, etc. and the human-readable labels. |
| `tools.py` | Ollama function-call schemas for every market + user tool. Used by `services.agent_core.market_tools` to build the base tool registry. |

### Heavy computation

| Module | Purpose |
|---|---|
| `company.py` | `score_companies(impact_vector, company_vectors)` — scores a list of companies against a news impact vector (dot product over shared dimensions). Imported lazily because it pulls numpy + pandas. |
| `market.py` | Market-level aggregates (regime, breadth) — used by services that surface "what is the tape doing." |

---

## Public API

The most-used entry points, all importable from `services.rag`:

```python
from services.rag import (
    # articles
    get_top_articles,         # (tickers, hours, limit) → list[article]
    get_ticker_news,          # (tickers, hours, per_ticker_limit) → list[article]
    fetch_tickers_for_articles,

    # sentiment
    get_cluster_trends,       # (hours) → cluster_id → time series
    get_dimension_trends,
    get_ticker_sentiment,     # (tickers, hours) → per-article-per-ticker

    # graph
    get_ticker_relationships, # (ticker, hops) → {nodes, edges}
    get_company_vectors,      # (tickers) → list of dimension vectors
    expand_related_tickers,
    build_neighborhood_from_seed,

    # embeddings
    search_news,              # (query, lookback_hours, tickers, limit) → semantic hits
    embed_query,

    # portfolio (per-user — pass user_id as first arg)
    get_user_positions, get_user_alerts, get_user_screening_notes,
    get_user_trading_strategy,

    # screening + context
    apply_scan_filters, get_filtered_tickers_from_scan,
    get_linked_scan_run_context,

    # taxonomy
    CLUSTERS, CLUSTER_ID_TO_LABEL, DIM_KEY_TO_LABEL,

    # tool schemas + dispatch maps
    TOOL_SCHEMAS, get_market_tools, get_user_tools,
)
```

---

## Consumers

| Service | What it imports |
|---|---|
| `services.agent_core` | `TOOL_SCHEMAS`, `get_market_tools()`, `get_user_tools()` — the base market registry is built from these. |
| `services.agent.engine` | `get_user_trading_strategy`, scan-filter helpers, linked-context helper. |
| `services.podcast.research_agent` | The base market registry (transitively, via `agent_core.build_market_registry`). |
| `services.news.narrative.narrative_generator` | Most of the data-access surface (positions, alerts, ticker news, expansions, semantic search). |
| `scripts/generate_blog_post.py` | Indirectly, via `services.news.embeddings.semantic_retrieval` (which delegates to `rag.search_news`). |

---

## Conventions

- **Read-only.** No module in `rag/` writes to Supabase. Mutations belong in the service that owns the data (e.g. `news/scoring/news_ingester` writes `news_articles`).
- **`user_id` is always the first positional arg** for any user-scoped function. `services.agent_core.build_user_registry(user_id)` relies on this — it pre-binds `user_id` to each tool fn so the agent loop dispatches by name without threading user context.
- **Add new tools in `tools.py`.** When you add a new helper to one of the data modules and want an LLM agent to call it, register the schema in `tools.py` and add the callable to `get_market_tools()` or `get_user_tools()`. Both `agent_core` and `engine.py` pick it up automatically.
- **Lazy-import the heavy stuff.** `company.score_companies` pulls numpy/pandas. Lazy imports keep startup time low for services that don't need it.
