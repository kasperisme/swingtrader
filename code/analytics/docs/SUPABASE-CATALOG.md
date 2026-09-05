# Supabase `swingtrader` catalog

Generated 2026-09-05 by `python -m services.catalog.build`. **Do not hand-edit** — regenerate instead.

108 tables/views, 1247 columns, 55 functions.

`rows` is a planner estimate, not a count. `fresh` is the newest row's timestamp — an object with an old date is likely abandoned, and that is as important to know as whether it exists.

## Relationships & graph

### `ticker_relationship_edge_evidence` (table)

*~88,286 rows, fresh to 2026-09-05*

Ticker relationship edge traceability Goal: - Provide deterministic traceability from ticker_relationship_edges back to source articles and impact-vector dimensions.

| column | type |
|---|---|
| `edge_id` | bigint |
| `article_id` | bigint |
| `rel_pair_key` | text |
| `rel_type` | text |
| `pair_strength` | double precision |
| `head_confidence` | double precision |
| `reasoning_text` | text |
| `published_at` | timestamp with time zone |
| `impact_json_snapshot` | jsonb |
| `top_dimensions_snapshot` | jsonb |
| `created_at` | timestamp with time zone |

`rel_type` values: `acquirer`, `client/representative`, `competitor`, `competitor|supplier|customer|partner|acquirer|subsidiary`, `customer`, `investigates`, `investigating`, `investigation`, `investigation_subject`, `investigation_target`, `investor`, `investor_holding`, `mutual`, `n/a`, `none`, `other`, `partner`, `potential partner`, `potential_acquirer`, `potential_customer`, `potential_partner`, `service_provider`, `subsidiary`, `supplier`

### `ticker_relationship_edges` (table)

*~39,685 rows, fresh to 2026-09-05*

Ticker Relationship Network (graph-ready adjacency structure) Why: - Avoid scanning/parsing JSONB relationship heads for every narrative run. - Materialize ticker->ticker edges with indexed lookup for multi-hop traversal. - Keep provenance + recency so downstream ranking can prioritize fresh edges.

| column | type |
|---|---|
| `id` | bigint |
| `from_ticker` | text |
| `to_ticker` | text |
| `rel_type` | text |
| `strength_avg` | double precision |
| `strength_max` | double precision |
| `mention_count` | integer |
| `article_count` | integer |
| `first_seen_at` | timestamp with time zone |
| `last_seen_at` | timestamp with time zone |
| `updated_at` | timestamp with time zone |
| `metadata_json` | jsonb |

`rel_type` values: `acquirer`, `client/representative`, `competitor`, `competitor|supplier|customer|partner|acquirer|subsidiary`, `customer`, `investigates`, `investigating`, `investigation`, `investigation_subject`, `investigation_target`, `investor`, `investor_holding`, `mutual`, `n/a`, `none`, `other`, `partner`, `potential partner`, `potential_acquirer`, `potential_customer`, `potential_partner`, `service_provider`, `subsidiary`, `supplier`

### `ticker_relationship_network_resolved_mv` (matview)

*~21,734 rows*

Relationship network materialization Problem (statement timeout on /protected/relations): ticker_relationship_network_resolved_v calls resolve_canonical_ticker() TWICE per edge across all ~22k rows of ticker_relationship_edges (each call is a security_identity_map lookup), then GROUP BYs — on EVERY query. So get_relationship_neighborhood() paid a fixed ~6s cost regardless of seed or hop count (measured: 1-hop and 2-hop both ~6.3s; the resolved view costs ~4.5s just to COUNT). Every node click on the relations side panel re-runs it, tripping the Postgres statement_timeout. Fix: Materialize the 

| column | type |
|---|---|

### `ticker_pair_stats` (table)

*~795 rows, fresh to 2026-09-03*

Ticker Pair Stats (cointegration / pairs-trading metrics on the graph) Why: - The news-derived relationship graph (ticker_relationship_edges) already prunes the candidate set: we only ever test pairs that share a verified economic link, not a blind N^2 universe scan. - Price-derived statistics (hedge ratio, Engle-Granger p-value, OU half-life, rolling spread mean/std) live HERE, in a separate lineage from the news-derived edges, so the relationship-graph refresh never clobbers them and vice versa. The two are stitched together in a view. Two clocks (kept up to date by two separate CLIs / cron 

| column | type |
|---|---|
| `id` | bigint |
| `ticker_a` | text |
| `ticker_b` | text |
| `hedge_ratio` | double precision |
| `coint_pvalue` | double precision |
| `half_life_days` | double precision |
| `spread_mean` | double precision |
| `spread_std` | double precision |
| `window_days` | integer |
| `n_obs` | integer |
| `is_cointegrated` | boolean |
| `calibrated_at` | timestamp with time zone |
| `current_price_a` | double precision |
| `current_price_b` | double precision |
| `current_spread` | double precision |
| `current_zscore` | double precision |
| `zscore_at` | timestamp with time zone |
| `updated_at` | timestamp with time zone |
| `metadata_json` | jsonb |

### `ticker_pair_candidates_v` (view)

*view — row count n/a*

Candidate pairs: order-normalized, deduped across rel_types, off the canonicalized graph. This is the whole moat in one view — calibrate_cli only ever fits pairs that appear here, so we test hundreds of news-linked pairs per week, not the tens of thousands a blind universe scan would.

| column | type |
|---|---|
| `ticker_a` | text |
| `ticker_b` | text |
| `article_count` | numeric |
| `mention_count` | numeric |
| `strength_max_any` | double precision |
| `last_seen_at` | timestamp with time zone |
| `rel_types` | ARRAY |

### `ticker_relationship_edge_traceability_v` (view)

*view — row count n/a*

Ticker relationship edge traceability Goal: - Provide deterministic traceability from ticker_relationship_edges back to source articles and impact-vector dimensions.

| column | type |
|---|---|
| `edge_id` | bigint |
| `from_ticker` | text |
| `to_ticker` | text |
| `rel_type` | text |
| `strength_avg` | double precision |
| `mention_count` | integer |
| `article_id` | bigint |
| `article_title` | character varying |
| `article_url` | character varying |
| `published_at` | timestamp with time zone |
| `pair_strength` | double precision |
| `head_confidence` | double precision |
| `reasoning_text` | text |
| `top_dimensions_snapshot` | jsonb |
| `impact_json_snapshot` | jsonb |

### `ticker_relationship_network_pairs_v` (view)

*view — row count n/a*

The stitched view: every news-derived edge, now carrying its pair's live cointegration metrics. A news event triggers the existing graph traversal (get_relationship_neighborhood / relationshipsGetNeighborhood) and every returned edge already has is_cointegrated + current_zscore on it — no new plumbing for the UI/agent layer.

| column | type |
|---|---|
| `from_ticker` | text |
| `to_ticker` | text |
| `rel_type` | text |
| `strength_avg` | double precision |
| `strength_max` | double precision |
| `mention_count` | bigint |
| `article_count` | bigint |
| `first_seen_at` | timestamp with time zone |
| `last_seen_at` | timestamp with time zone |
| `hedge_ratio` | double precision |
| `coint_pvalue` | double precision |
| `is_cointegrated` | boolean |
| `half_life_days` | double precision |
| `spread_mean` | double precision |
| `spread_std` | double precision |
| `current_zscore` | double precision |
| `zscore_at` | timestamp with time zone |
| `calibrated_at` | timestamp with time zone |

### `ticker_relationship_network_resolved_v` (view)

*view — row count n/a*

Canonicalized graph view for adjacency traversal.

| column | type |
|---|---|
| `from_ticker` | text |
| `to_ticker` | text |
| `rel_type` | text |
| `strength_avg` | double precision |
| `strength_max` | double precision |
| `mention_count` | bigint |
| `article_count` | bigint |
| `first_seen_at` | timestamp with time zone |
| `last_seen_at` | timestamp with time zone |

### `ticker_relationship_network_v` (view)

*view — row count n/a*

Ticker Relationship Network (graph-ready adjacency structure) Why: - Avoid scanning/parsing JSONB relationship heads for every narrative run. - Materialize ticker->ticker edges with indexed lookup for multi-hop traversal. - Keep provenance + recency so downstream ranking can prioritize fresh edges.

| column | type |
|---|---|
| `from_ticker` | text |
| `to_ticker` | text |
| `rel_type` | text |
| `strength_avg` | double precision |
| `strength_max` | double precision |
| `mention_count` | integer |
| `article_count` | integer |
| `first_seen_at` | timestamp with time zone |
| `last_seen_at` | timestamp with time zone |

## News: articles & scoring

### `news_impact_heads` (table)

*~2,651,283 rows, fresh to 2026-09-05*

news_impact_heads: per-cluster LLM scoring results

| column | type |
|---|---|
| `id` | bigint |
| `article_id` | bigint |
| `cluster` | character varying |
| `scores_json` | jsonb |
| `reasoning_json` | jsonb |
| `confidence` | double precision |
| `model` | character varying |
| `latency_ms` | integer |
| `created_at` | timestamp with time zone |

`cluster` values: `ARTICLE_TAGS`, `BUSINESS_MODEL`, `FINANCIAL_STRUCTURE`, `GEOGRAPHY_TRADE`, `GROWTH_PROFILE`, `MACRO_SENSITIVITY`, `MARKET_BEHAVIOUR`, `SECTOR_ROTATION`, `STORY_KEY_POINTS`, `SUPPLY_CHAIN_EXPOSURE`, `TICKER_RELATIONSHIPS`, `TICKER_SENTIMENT`, `VALUATION_POSITIONING`

### `news_article_embeddings` (table)

*~1,853,533 rows*

Embedding setup for semantic retrieval over scored news.

| column | type |
|---|---|
| `id` | bigint |
| `article_id` | bigint |
| `chunk_index` | integer |
| `chunk_hash` | text |
| `chunk_text` | text |
| `embedding` | USER-DEFINED |
| `embedding_model` | text |
| `created_at` | timestamp with time zone |
| `published_at` | timestamp with time zone |

### `news_article_tickers` (table)

*~739,882 rows*

news_article_tickers: ticker mentions extracted from articles

| column | type |
|---|---|
| `article_id` | bigint |
| `ticker` | character varying |
| `source` | character varying |

### `news_articles` (table)

*~226,391 rows, fresh to 2026-09-05*

news_articles: article content and metadata

| column | type |
|---|---|
| `id` | bigint |
| `created_at` | timestamp with time zone |
| `url` | character varying |
| `title` | character varying |
| `body` | text |
| `source` | character varying |
| `article_hash` | character varying |
| `published_at` | timestamp with time zone |
| `publisher` | text |
| `image_url` | text |
| `slug` | text |
| `article_stream` | text |
| `processing_status` | text |
| `search_tags` | ARRAY |
| `fts` | tsvector |

`article_stream` values: `fmp_general`, `fmp_stock`, `unknown`

`processing_status` values: `complete`, `failed`, `partial`

### `news_article_embedding_jobs` (table)

*~225,591 rows, fresh to 2026-09-05*

Embedding setup for semantic retrieval over scored news.

| column | type |
|---|---|
| `article_id` | bigint |
| `status` | text |
| `attempt_count` | integer |
| `last_error` | text |
| `last_attempt_at` | timestamp with time zone |
| `completed_at` | timestamp with time zone |
| `created_at` | timestamp with time zone |
| `updated_at` | timestamp with time zone |

`status` values: `completed`, `failed`, `pending`, `processing`

### `news_impact_vectors` (table)

*~209,330 rows, fresh to 2026-09-05*

news_impact_vectors: aggregated impact dimension vectors

| column | type |
|---|---|
| `id` | bigint |
| `article_id` | bigint |
| `impact_json` | jsonb |
| `top_dimensions` | jsonb |
| `created_at` | timestamp with time zone |
| `impact_magnitude` | double precision |

### `news_source_dry_days` (table)

*~691 rows*

Track calendar days where a news source stream has been fully exhausted (all available articles fetched/processed, no new content from the API). Used to skip re-polling dry days in future runs.

| column | type |
|---|---|
| `source_stream` | character varying |
| `day` | date |
| `marked_at` | timestamp with time zone |
| `pages_checked` | integer |
| `articles_found` | integer |
| `note` | text |

`source_stream` values: `fmp_general`, `fmp_stock`

### `news_embedding_hourly_cluster_articles` (table)

*~57 rows*

Hourly / daily embedding clusters over swingtrader.news_article_embeddings (UTC buckets). Populated by services/news/embeddings/time_bucket_clustering.py (scripts/cluster_news_embedding_buckets.py). Per bucket: run metadata, one centroid row per cluster (float8[] + nearest-chunk reverse text), one article assignment row per article.

| column | type |
|---|---|
| `bucket_start` | timestamp with time zone |
| `embedding_model` | text |
| `article_id` | bigint |
| `cluster_index` | integer |
| `computed_at` | timestamp with time zone |

### `news_briefing_subscriptions` (table)

*~34 rows, fresh to 2026-09-04*

News briefing subscriptions: the free, no-account email service that sends a nicely structured PDF of the last 24h of news, summaries and impact for the tickers / tags a visitor cares about. Mirrors market_screening_email_subscriptions (email-only, soft-unsubscribe, service-role access) but the unit a visitor subscribes to is their OWN watchlist of tickers + tags rather than a curated screening. One briefing per email — editing the watchlist is an in-place update via a signed manage link, no login required. Delivery: * On signup we set initial_briefing_requested_at; the Python briefing tick ge

| column | type |
|---|---|
| `id` | uuid |
| `email` | text |
| `tickers` | ARRAY |
| `tags` | ARRAY |
| `status` | text |
| `source` | text |
| `user_id` | uuid |
| `referrer` | text |
| `user_agent` | text |
| `metadata` | jsonb |
| `initial_briefing_requested_at` | timestamp with time zone |
| `last_sent_at` | timestamp with time zone |
| `unsubscribed_at` | timestamp with time zone |
| `created_at` | timestamp with time zone |
| `updated_at` | timestamp with time zone |

`status` values: `active`, `unsubscribed`

`source` values: `article_briefing`, `briefings_page`, `briefings_preset`

### `news_embedding_daily_cluster_articles` (table)

*~0 rows*

Hourly / daily embedding clusters over swingtrader.news_article_embeddings (UTC buckets). Populated by services/news/embeddings/time_bucket_clustering.py (scripts/cluster_news_embedding_buckets.py). Per bucket: run metadata, one centroid row per cluster (float8[] + nearest-chunk reverse text), one article assignment row per article.

| column | type |
|---|---|
| `bucket_start` | timestamp with time zone |
| `embedding_model` | text |
| `article_id` | bigint |
| `cluster_index` | integer |
| `computed_at` | timestamp with time zone |

### `news_embedding_daily_cluster_centroids` (table)

*~0 rows*

Hourly / daily embedding clusters over swingtrader.news_article_embeddings (UTC buckets). Populated by services/news/embeddings/time_bucket_clustering.py (scripts/cluster_news_embedding_buckets.py). Per bucket: run metadata, one centroid row per cluster (float8[] + nearest-chunk reverse text), one article assignment row per article.

| column | type |
|---|---|
| `bucket_start` | timestamp with time zone |
| `embedding_model` | text |
| `cluster_index` | integer |
| `centroid` | ARRAY |
| `reverse_embedding_text` | text |
| `reverse_embedding_article_id` | bigint |
| `reverse_embedding_chunk_index` | integer |
| `member_count` | integer |
| `computed_at` | timestamp with time zone |

### `news_embedding_daily_cluster_runs` (table)

*~0 rows*

── Daily ───────────────────────────────────────────────────────────────────

| column | type |
|---|---|
| `bucket_start` | timestamp with time zone |
| `embedding_model` | text |
| `n_clusters` | integer |
| `article_count` | integer |
| `chunk_rows_used` | integer |
| `embedding_dim` | integer |
| `computed_at` | timestamp with time zone |

### `news_embedding_hourly_cluster_centroids` (table)

*~0 rows*

Hourly / daily embedding clusters over swingtrader.news_article_embeddings (UTC buckets). Populated by services/news/embeddings/time_bucket_clustering.py (scripts/cluster_news_embedding_buckets.py). Per bucket: run metadata, one centroid row per cluster (float8[] + nearest-chunk reverse text), one article assignment row per article.

| column | type |
|---|---|
| `bucket_start` | timestamp with time zone |
| `embedding_model` | text |
| `cluster_index` | integer |
| `centroid` | ARRAY |
| `reverse_embedding_text` | text |
| `reverse_embedding_article_id` | bigint |
| `reverse_embedding_chunk_index` | integer |
| `member_count` | integer |
| `computed_at` | timestamp with time zone |

### `news_embedding_hourly_cluster_runs` (table)

*~0 rows*

── Hourly ─────────────────────────────────────────────────────────────────

| column | type |
|---|---|
| `bucket_start` | timestamp with time zone |
| `embedding_model` | text |
| `n_clusters` | integer |
| `article_count` | integer |
| `chunk_rows_used` | integer |
| `embedding_dim` | integer |
| `computed_at` | timestamp with time zone |

### `news_trends_article_base_v` (view)

*view — row count n/a*

1) Article-level base rows with parsed vectors + mean confidence.

| column | type |
|---|---|
| `article_id` | bigint |
| `published_at` | timestamp with time zone |
| `bucket_day` | timestamp with time zone |
| `bucket_hour` | timestamp with time zone |
| `impact_jsonb` | jsonb |
| `confidence_mean` | double precision |
| `id` | bigint |
| `title` | character varying |
| `url` | character varying |
| `source` | character varying |
| `slug` | text |
| `image_url` | text |
| `article_created_at` | timestamp with time zone |

### `news_trends_cluster_daily_v` (view)

*view — row count n/a*

4) Cluster rollups from dimensions, matching UI logic: per-article cluster = mean(dimensions in cluster), then weighted mean by bucket.

| column | type |
|---|---|
| `bucket_day` | timestamp with time zone |
| `cluster_id` | text |
| `bucket_article_count` | bigint |
| `article_count` | bigint |
| `cluster_avg` | double precision |
| `cluster_weighted_avg` | double precision |

### `news_trends_cluster_hourly_v` (view)

*view — row count n/a*

Bound hourly news-trends views to last 60 days so their CTEs don't scan the full base table. Original views (in 20260414100000_news_trends_aggregate_views.sql) compute `bucket_counts` and `article_cluster_scores` over every article — the outer WHERE on `bucket_hour` cannot push into those CTEs, which causes statement timeouts on Supabase. Filtering inside the view on `published_at` (indexed via idx_news_articles_published_at) bounds the scan up-front so the rollup stays under `statement_timeout`.

| column | type |
|---|---|
| `bucket_hour` | timestamp with time zone |
| `cluster_id` | text |
| `bucket_article_count` | bigint |
| `article_count` | bigint |
| `cluster_avg` | double precision |
| `cluster_weighted_avg` | double precision |

### `news_trends_dimension_cluster_map_v` (view)

*view — row count n/a*

| column | type |
|---|---|
| `dimension_key` | text |
| `cluster_id` | text |

### `news_trends_dimension_daily_v` (view)

*view — row count n/a*

3) Dimension aggregates (daily / hourly), weighted and unweighted.

| column | type |
|---|---|
| `bucket_day` | timestamp with time zone |
| `dimension_key` | text |
| `bucket_article_count` | bigint |
| `sample_count` | bigint |
| `article_count` | bigint |
| `dimension_avg` | double precision |
| `dimension_weighted_avg` | double precision |

### `news_trends_dimension_hourly_v` (view)

*view — row count n/a*

Bound hourly news-trends views to last 60 days so their CTEs don't scan the full base table. Original views (in 20260414100000_news_trends_aggregate_views.sql) compute `bucket_counts` and `article_cluster_scores` over every article — the outer WHERE on `bucket_hour` cannot push into those CTEs, which causes statement timeouts on Supabase. Filtering inside the view on `published_at` (indexed via idx_news_articles_published_at) bounds the scan up-front so the rollup stays under `statement_timeout`.

| column | type |
|---|---|
| `bucket_hour` | timestamp with time zone |
| `dimension_key` | text |
| `bucket_article_count` | bigint |
| `sample_count` | bigint |
| `article_count` | bigint |
| `dimension_avg` | double precision |
| `dimension_weighted_avg` | double precision |

### `news_trends_dimension_points_v` (view)

*view — row count n/a*

2) One row per article/dimension with numeric value.

| column | type |
|---|---|
| `article_id` | bigint |
| `published_at` | timestamp with time zone |
| `bucket_day` | timestamp with time zone |
| `bucket_hour` | timestamp with time zone |
| `confidence_mean` | double precision |
| `dimension_key` | text |
| `dimension_value` | double precision |

### `news_trends_heads_daily_v` (view)

*view — row count n/a*

5) Head-level aggregates for diagnostics/trend overlays.

| column | type |
|---|---|
| `bucket_day` | timestamp with time zone |
| `cluster` | character varying |
| `bucket_article_count` | bigint |
| `head_count` | bigint |
| `article_count` | bigint |
| `confidence_avg` | double precision |

### `news_trends_heads_hourly_v` (view)

*view — row count n/a*

Pre-aggregated views for News Trends charts. Goal: avoid scanning/parsing every raw row in the UI path. Supporting indexes for faster joins/bucketing.

| column | type |
|---|---|
| `bucket_hour` | timestamp with time zone |
| `cluster` | character varying |
| `bucket_article_count` | bigint |
| `head_count` | bigint |
| `article_count` | bigint |
| `confidence_avg` | double precision |

### `news_trends_tag_daily_v` (view)

*view — row count n/a*

2) Theme-tag frequency per day. search_tags holds lowercase theme/event slugs PLUS uppercase tickers in one array. Tickers are covered by view (1); here we keep theme slugs only via `tag = lower(tag)` (tickers are uppercase by construction).

| column | type |
|---|---|
| `bucket_day` | date |
| `tag` | text |
| `article_count` | bigint |

### `news_trends_ticker_daily_v` (view)

*view — row count n/a*

1) Ticker mentions per day, with sentiment overlay. mention_count  = # articles mentioning the ticker that day (all mentions) scored_count   = # of those with an LLM sentiment head avg_sentiment  = mean sentiment over scored mentions  ∈ [-1, 1] weighted_sentiment = confidence-weighted mean sentiment

| column | type |
|---|---|
| `bucket_day` | date |
| `ticker` | character varying |
| `mention_count` | bigint |
| `scored_count` | bigint |
| `avg_sentiment` | double precision |
| `weighted_sentiment` | double precision |

## News: topics & claims

### `topic_claim_stats` (table)

*~1,497 rows, fresh to 2026-09-05*

topic_claim_stats — the materialized half. Ranked STORY_KEY_POINTS across a topic's whole arc. This CANNOT be live: it scans every matching article's heads, and the REST role (`authenticator`) caps statements at 8s. Refreshed after each ingest, exactly like ticker_sentiment_heads / ticker_relationship_edges. Every claim keeps `article_ts`. A permanent page that aggregates claims will otherwise enshrine stale numbers as evergreen fact — observed repeatedly: NVIDIA "$119B supply commitments / $91B guide" (pre-quarter, reports Aug 26) and Micron "+346% to $41.46B" (a prior quarter) both resurface

| column | type |
|---|---|
| `topic_slug` | text |
| `article_id` | bigint |
| `claim_key` | text |
| `claim` | text |
| `impact` | real |
| `article_ts` | timestamp with time zone |
| `article_title` | text |
| `article_slug` | text |
| `tickers` | ARRAY |
| `updated_at` | timestamp with time zone |

### `topic_stats` (table)

*~2 rows*

Materialize the topic headline counts. getTopicStats ran an exact count over topic_article_v — the LIVE membership view — for every topic on every render. Measured against the built app: /quote (reads a materialized rollup) serves in ~0.10s while /topics and /topics/[slug] take ~0.35s, and that count is the whole difference. It is also the one query on the page that can time out, which is how a tracker with 791 stories could render "0 stories". Only the COUNT moves. The feed stays live — it is `limit 24` off an indexed view (~50ms) and being live is the point of it. Refreshed inside exec_topic

| column | type |
|---|---|
| `topic_slug` | text |
| `article_count` | bigint |
| `claim_count` | bigint |
| `first_seen` | timestamp with time zone |
| `last_seen` | timestamp with time zone |
| `refreshed_at` | timestamp with time zone |

### `topic_article_v` (view)

*view — row count n/a*

topic_article_v — the membership query, as a view. Deliberately NOT materialized: it resolves in ~30ms and materializing it would reintroduce the staleness the whole design exists to avoid. The heavy rollups (15-month arcs) are materialized separately below.

| column | type |
|---|---|
| `topic_slug` | text |
| `article_id` | bigint |
| `title` | character varying |
| `article_slug` | text |
| `published_at` | timestamp with time zone |
| `search_tags` | ARRAY |
| `matched_tickers` | ARRAY |

## Tickers: sentiment & coverage

### `ticker_sentiment_heads` (table)

*~364,321 rows, fresh to 2026-09-05*

Ticker Sentiment Materialization (pre-exploded, indexed) Why: - swingtrader.ticker_sentiment_heads_v explodes EVERY TICKER_SENTIMENT head's scores_json (text->jsonb cast + jsonb_each_text) and joins news_articles on every request. The `ticker` column is derived from JSON keys and `article_ts` from a join, so neither a `ticker IN (...)` nor a date filter can be pushed down or indexed — the view is O(all sentiment heads) per call and was taking 4–8s for a single ticker (and growing with ingestion). - This pre-explodes the same data into a real table keyed by (head_id, ticker) with an index on (t

| column | type |
|---|---|
| `head_id` | bigint |
| `article_id` | bigint |
| `ticker` | text |
| `sentiment_score` | double precision |
| `reasoning_text` | text |
| `confidence` | double precision |
| `model` | text |
| `latency_ms` | integer |
| `scored_at` | timestamp with time zone |
| `article_ts` | timestamp with time zone |
| `updated_at` | timestamp with time zone |

`model` values: `claude-haiku-4-5`, `do-agent`, `gemma4:31b-cloud`, `gemma4:e4b`

### `ticker_coverage_daily` (table)

*~60,400 rows, fresh to 2026-09-05*

Materialize the /quote directory's daily rollup. get_top_covered_tickers read news_trends_ticker_daily_v directly, which rescans 120 days of news_article_tickers + news_articles + ticker_sentiment heads on every call: measured 4.6s for a plain page and 7.6s for a search — against the REST role's 8s statement_timeout. That is a page that breaks the first time the corpus grows. Same split the topic hubs use: membership stays live, the expensive rollup is materialized and rebuilt post-ingest. A table (not a matview) so it can carry RLS like its siblings. Only the daily rollup is stored, NOT the w

| column | type |
|---|---|
| `bucket_day` | date |
| `ticker` | text |
| `mention_count` | bigint |
| `scored_count` | bigint |
| `avg_sentiment` | double precision |

### `ticker_sentiment_heads_v` (view)

*view — row count n/a*

Ticker Sentiment View (article-level, parsed from TICKER_SENTIMENT heads) Why: - Expose sentiment by (article, ticker) without JSON parsing in application code. - Keep traceability to source head metadata and article publication timestamps.

| column | type |
|---|---|
| `head_id` | bigint |
| `article_id` | bigint |
| `ticker` | text |
| `sentiment_score` | double precision |
| `reasoning_text` | text |
| `confidence` | double precision |
| `model` | character varying |
| `latency_ms` | integer |
| `scored_at` | timestamp with time zone |
| `article_ts` | timestamp with time zone |
| `published_at` | timestamp with time zone |
| `article_source` | character varying |
| `article_publisher` | text |
| `article_title` | character varying |
| `article_url` | character varying |

## Company factor vectors

### `company_vectors` (table)

*~3,401 rows, fresh to 2026-04-29*

company_vectors: fundamental dimension vectors per ticker per date

| column | type |
|---|---|
| `id` | bigint |
| `ticker` | character varying |
| `vector_date` | date |
| `dimensions_json` | jsonb |
| `raw_json` | jsonb |
| `metadata_json` | jsonb |
| `fetched_at` | timestamp with time zone |

## Screening & scans

### `market_screening_result_rows` (table)

*~134,149 rows, fresh to 2026-09-05*

| column | type |
|---|---|
| `id` | bigint |
| `market_screening_id` | uuid |
| `result_id` | uuid |
| `run_at` | timestamp with time zone |
| `scan_date` | date |
| `dataset` | character varying |
| `symbol` | character varying |
| `row_data` | jsonb |
| `created_at` | timestamp with time zone |

### `market_screening_results` (table)

*~4,296 rows, fresh to 2026-09-05*

| column | type |
|---|---|
| `id` | uuid |
| `market_screening_id` | uuid |
| `run_at` | timestamp with time zone |
| `started_at` | timestamp with time zone |
| `status` | text |
| `triggered` | boolean |
| `summary` | text |
| `data_used` | jsonb |
| `error` | text |
| `is_test` | boolean |
| `created_at` | timestamp with time zone |
| `bulk_analysis_status` | text |
| `bulk_analysis_started_at` | timestamp with time zone |
| `bulk_analysis_finished_at` | timestamp with time zone |
| `bulk_analysis_error` | text |

`status` values: `done`, `error`

`bulk_analysis_status` values: `done`, `error`

### `market_screening_email_subscriptions` (table)

*~23 rows, fresh to 2026-08-19*

Market screening EMAIL subscriptions: the lightweight, email-only delivery list that powers the "Send me the results" CTA across the site (article bridge CTA + the screenings gallery Subscribe buttons). This is deliberately separate from the two existing tables: * early_access_signups            — a waitlist / lead capture. No delivery intent; conversions are manual. * market_screening_subscriptions  — auth-only (user_id FK). In-app + Telegram delivery for signed-in users. This table answers "which email wants which screening results, on which channel" with no account required. One row per (em

| column | type |
|---|---|
| `id` | uuid |
| `email` | text |
| `market_screening_id` | uuid |
| `channel` | text |
| `status` | text |
| `source` | text |
| `user_id` | uuid |
| `referrer` | text |
| `user_agent` | text |
| `metadata` | jsonb |
| `confirmation_sent_at` | timestamp with time zone |
| `unsubscribed_at` | timestamp with time zone |
| `created_at` | timestamp with time zone |
| `updated_at` | timestamp with time zone |

`status` values: `active`, `unsubscribed`

`source` values: `gallery_card_subscribe`, `gallery_csv_download`, `screening_detail_subscribe`

### `market_screenings` (table)

*~10 rows, fresh to 2026-09-05*

| column | type |
|---|---|
| `id` | uuid |
| `author_user_id` | uuid |
| `slug` | text |
| `script_key` | text |
| `name` | text |
| `description` | text |
| `category` | text |
| `schedule` | text |
| `timezone` | text |
| `is_active` | boolean |
| `is_published` | boolean |
| `next_run_at` | timestamp with time zone |
| `last_run_at` | timestamp with time zone |
| `last_triggered` | boolean |
| `run_requested_at` | timestamp with time zone |
| `created_at` | timestamp with time zone |
| `updated_at` | timestamp with time zone |
| `download_count` | bigint |
| `llm_prompt` | text |

`category` values: `IPO`, `Insider`, `Thematic`, `fundamental-sentiment`, `fundamentals`, `technical`, `technical-fundamental`, `test`

### `market_screening_subscriptions` (table)

*~0 rows*

| column | type |
|---|---|
| `id` | uuid |
| `user_id` | uuid |
| `market_screening_id` | uuid |
| `notifications_enabled` | boolean |
| `subscribed_at` | timestamp with time zone |

## Users, plans & billing

### `user_scan_rows` (table)

*~68,397 rows, fresh to 2026-09-04*

| column | type |
|---|---|
| `id` | bigint |
| `run_id` | bigint |
| `scan_date` | date |
| `dataset` | character varying |
| `symbol` | character varying |
| `row_data` | jsonb |
| `user_id` | uuid |

### `user_scan_row_notes` (table)

*~21,384 rows, fresh to 2026-09-04*

| column | type |
|---|---|
| `id` | bigint |
| `scan_row_id` | bigint |
| `run_id` | bigint |
| `ticker` | character varying |
| `status` | character varying |
| `highlighted` | boolean |
| `comment` | text |
| `stage` | character varying |
| `priority` | smallint |
| `tags` | ARRAY |
| `metadata_json` | jsonb |
| `created_at` | timestamp with time zone |
| `updated_at` | timestamp with time zone |
| `user_id` | uuid |

`status` values: `active`, `dismissed`, `pipeline`, `watchlist`

### `user_ticker_chart_workspace` (table)

*~5,319 rows, fresh to 2026-09-05*

Per-user chart workspace: annotations + Chart AI conversation, keyed by ticker. Used by protected/charts; RLS restricts rows to the owning user.

| column | type |
|---|---|
| `user_id` | uuid |
| `ticker` | character varying |
| `annotations` | jsonb |
| `ai_chat_messages` | jsonb |
| `updated_at` | timestamp with time zone |

### `user_screening_results` (table)

*~2,492 rows, fresh to 2026-09-05*

── user_screening_results ──────────────────────────────────────────────────

| column | type |
|---|---|
| `id` | uuid |
| `screening_id` | uuid |
| `user_id` | uuid |
| `run_at` | timestamp with time zone |
| `triggered` | boolean |
| `summary` | text |
| `data_used` | jsonb |
| `delivered` | boolean |
| `created_at` | timestamp with time zone |
| `is_test` | boolean |
| `status` | text |
| `started_at` | timestamp with time zone |
| `trace` | jsonb |

`status` values: `done`, `error`, `skipped`

### `user_scan_jobs` (table)

*~306 rows, fresh to 2026-09-04*

| column | type |
|---|---|
| `id` | bigint |
| `created_at` | timestamp with time zone |
| `started_at` | timestamp with time zone |
| `finished_at` | timestamp with time zone |
| `status` | character varying |
| `scan_source` | character varying |
| `script_rel` | character varying |
| `args_json` | jsonb |
| `pid` | integer |
| `exit_code` | integer |
| `scan_run_id` | bigint |
| `stdout_log` | text |
| `stderr_log` | text |
| `error_message` | text |
| `progress_message` | character varying |
| `user_id` | uuid |

`status` values: `completed`, `failed`, `running`

`scan_source` values: `ai_supercycle`, `ibd_screener`, `insider_congress`, `ipo_screener`, `nis_fundamentals`, `nis_momentum`, `stage_2`, `test_aapl`

### `user_scan_runs` (table)

*~216 rows, fresh to 2026-09-04*

| column | type |
|---|---|
| `id` | bigint |
| `created_at` | timestamp with time zone |
| `scan_date` | date |
| `source` | character varying |
| `market_json` | jsonb |
| `result_json` | jsonb |
| `user_id` | uuid |
| `status` | character varying |

`source` values: `LaggeX`, `Phines screenings`, `VSAT`, `ibd_screener`, `ibd_screener_smoke_test`, `market_screening:ai-supercycle`, `market_screening:insider-congress`, `market_screening:ipo-screener`, `market_screening:nis-fundamentals`, `market_screening:nis-momentum`, `market_screening:stage-2`, `public_screening:nis-momentum`, `public_screening:stage-2`, `public_screening:test-aapl`

`status` values: `active`, `deleted`

### `user_trades` (table)

*~36 rows, fresh to 2026-08-15*

user_trades: per-user trade ledger (buy/sell × long/short) Semantics: side            : 'buy' | 'sell' (execution direction) position_side   : 'long' | 'short' (which side of the book) Examples: Open long:   buy  + long Close long:  sell + long Open short:  sell + short Cover short: buy  + short

| column | type |
|---|---|
| `id` | bigint |
| `user_id` | uuid |
| `side` | character varying |
| `position_side` | character varying |
| `ticker` | character varying |
| `quantity` | numeric |
| `price_per_unit` | numeric |
| `currency` | character varying |
| `executed_at` | timestamp with time zone |
| `broker` | character varying |
| `account_label` | character varying |
| `notes` | text |
| `metadata_json` | jsonb |
| `created_at` | timestamp with time zone |
| `updated_at` | timestamp with time zone |
| `is_paper` | boolean |

### `user_profiles` (table)

*~15 rows, fresh to 2026-08-31*

user_profiles Per-user app state that doesn't belong in auth.users.user_metadata. Designed to grow: free-form `metadata` jsonb for ad-hoc flags so adding a new piece of profile state doesn't require a migration. `welcomed_at` drives the first-login welcome dialog: NULL = show, set = skip.

| column | type |
|---|---|
| `user_id` | uuid |
| `created_at` | timestamp with time zone |
| `updated_at` | timestamp with time zone |
| `welcomed_at` | timestamp with time zone |
| `display_name` | text |
| `metadata` | jsonb |
| `onboarding_dismissed_at` | timestamp with time zone |

### `user_bulk_analysis_jobs` (table)

*~6 rows, fresh to 2026-06-02*

user_bulk_analysis_jobs Tracks fire-and-forget bulk per-ticker technical-analysis jobs. One job per "Analyze all" click on a scan run. The Python worker (services.bulk_analysis) picks up status='queued' rows on its 1-min tick, iterates the run's tickers via Ollama, writes the result into user_ticker_chart_workspace.ai_chat_messages and the call into user_scan_row_notes.status, then marks the job done.

| column | type |
|---|---|
| `id` | uuid |
| `user_id` | uuid |
| `scan_run_id` | bigint |
| `status` | text |
| `total_tickers` | integer |
| `completed_tickers` | integer |
| `failed_tickers` | integer |
| `started_at` | timestamp with time zone |
| `finished_at` | timestamp with time zone |
| `error_message` | text |
| `created_at` | timestamp with time zone |
| `user_prompt` | text |
| `ticker_subset` | ARRAY |
| `chart_granularity` | text |
| `chart_date_from` | date |
| `chart_date_to` | date |
| `bulk_chat_messages` | jsonb |

`status` values: `done`, `error`

### `user_scheduled_screenings` (table)

*~5 rows, fresh to 2026-09-05*

── user_scheduled_screenings ────────────────────────────────────────────────

| column | type |
|---|---|
| `id` | uuid |
| `user_id` | uuid |
| `name` | text |
| `prompt` | text |
| `schedule` | text |
| `timezone` | text |
| `is_active` | boolean |
| `last_run_at` | timestamp with time zone |
| `last_triggered` | boolean |
| `created_at` | timestamp with time zone |
| `updated_at` | timestamp with time zone |
| `run_requested_at` | timestamp with time zone |
| `tickers` | ARRAY |
| `linked_scan_run_ids` | ARRAY |
| `next_run_at` | timestamp with time zone |
| `scan_filters` | jsonb |
| `trading_session` | text |
| `condition_enabled` | boolean |
| `trigger_condition` | text |
| `linked_scan_sources` | ARRAY |

### `user_api_keys` (table)

*~2 rows, fresh to 2026-04-12*

user_api_keys

| column | type |
|---|---|
| `id` | uuid |
| `user_id` | uuid |
| `name` | character varying |
| `key_hash` | text |
| `key_prefix` | character varying |
| `scopes` | ARRAY |
| `created_at` | timestamp with time zone |
| `last_used_at` | timestamp with time zone |
| `expires_at` | timestamp with time zone |
| `revoked_at` | timestamp with time zone |

### `user_subscriptions` (table)

*~1 rows, fresh to 2026-08-31*

user_subscriptions Tracks Stripe subscriptions per user. Created by the Stripe webhook Edge Function on checkout.session.completed / customer.subscription.* events. user_id is nullable so a row can be created before the user has a Supabase auth account (payment first, then account creation).

| column | type |
|---|---|
| `id` | uuid |
| `created_at` | timestamp with time zone |
| `updated_at` | timestamp with time zone |
| `user_id` | uuid |
| `email` | text |
| `stripe_customer_id` | text |
| `stripe_subscription_id` | text |
| `status` | text |
| `plan` | text |
| `billing_interval` | text |
| `phase` | text |
| `grandfathered` | boolean |
| `current_period_end` | timestamp with time zone |
| `attribution` | jsonb |

### `user_narrative_preferences` (table)

*~0 rows, fresh to 2026-04-12*

── user_narrative_preferences ────────────────────────────────────────────────

| column | type |
|---|---|
| `id` | uuid |
| `user_id` | uuid |
| `is_enabled` | boolean |
| `delivery_time` | time without time zone |
| `timezone` | character varying |
| `delivery_method` | character varying |
| `lookback_hours` | integer |
| `include_portfolio` | boolean |
| `include_screenings` | boolean |
| `created_at` | timestamp with time zone |
| `updated_at` | timestamp with time zone |

### `user_portfolio_alerts` (table)

*~0 rows*

── user_portfolio_alerts ─────────────────────────────────────────────────────

| column | type |
|---|---|
| `id` | uuid |
| `user_id` | uuid |
| `ticker` | character varying |
| `alert_type` | character varying |
| `price` | numeric |
| `direction` | character varying |
| `notes` | text |
| `is_active` | boolean |
| `triggered_at` | timestamp with time zone |
| `created_at` | timestamp with time zone |
| `updated_at` | timestamp with time zone |

### `user_telegram_connections` (table)

*~0 rows, fresh to 2026-08-06*

user_telegram_connections: general-purpose Telegram account linkage Decoupled from user_narrative_preferences so any feature can send personalised Telegram messages without coupling to the narrative system. Also removes the Telegram-specific columns that were added to user_narrative_preferences in the previous migrations.

| column | type |
|---|---|
| `id` | uuid |
| `user_id` | uuid |
| `chat_id` | character varying |
| `link_token` | character varying |
| `link_expires_at` | timestamp with time zone |
| `connected_at` | timestamp with time zone |
| `created_at` | timestamp with time zone |
| `updated_at` | timestamp with time zone |

### `user_trade_reviews` (table)

*~0 rows, fresh to 2026-06-07*

user_trade_reviews: AI post-trade review chats keyed by the closing trade A "review" lives on the trade row that flattens a position back to zero (the closing fill). The position itself is derived client/server-side by replaying user_trades; we just need a stable key (the closing trade id) and a place to persist the chat + final AI summary so users can revisit.

| column | type |
|---|---|
| `id` | bigint |
| `user_id` | uuid |
| `closing_trade_id` | bigint |
| `ticker` | character varying |
| `position_snapshot` | jsonb |
| `messages` | jsonb |
| `summary` | text |
| `scores` | jsonb |
| `created_at` | timestamp with time zone |
| `updated_at` | timestamp with time zone |

### `user_trading_strategy` (table)

*~0 rows, fresh to 2026-08-18*

| column | type |
|---|---|
| `user_id` | uuid |
| `strategy` | text |
| `updated_at` | timestamp with time zone |

## Agents & jobs

### `job_runs` (table)

*~256,091 rows, fresh to 2026-09-05*

| column | type |
|---|---|
| `id` | bigint |
| `job_name` | text |
| `started_at` | timestamp with time zone |
| `finished_at` | timestamp with time zone |
| `status` | text |
| `duration_s` | double precision |
| `error` | text |
| `created_at` | timestamp with time zone |

`status` values: `failed`, `success`

### `job_health` (table)

*~15 rows*

| column | type |
|---|---|
| `job_name` | text |
| `last_started_at` | timestamp with time zone |
| `last_finished_at` | timestamp with time zone |
| `last_status` | text |
| `last_error` | text |
| `consecutive_fails` | integer |
| `expected_interval` | interval |
| `metadata` | jsonb |

`last_status` values: `failed`, `running`, `success`

## Other

### `tickers` (table)

*~5,810 rows, fresh to 2026-08-08*

tickers: universe of actively-traded NYSE and NASDAQ stocks Seeded via scripts/seed_tickers.py (FMP company-screener endpoint).

| column | type |
|---|---|
| `symbol` | character varying |
| `exchange` | character varying |
| `company_name` | character varying |
| `sector` | character varying |
| `industry` | character varying |
| `market_cap` | bigint |
| `price` | double precision |
| `volume` | bigint |
| `beta` | double precision |
| `country` | character varying |
| `is_actively_trading` | boolean |
| `last_seen_at` | timestamp with time zone |
| `updated_at` | timestamp with time zone |

### `research_priced_in_universe` (table)

*~5,807 rows, fresh to 2026-09-04*

1) The working universe and its schedule.

| column | type |
|---|---|
| `symbol` | text |
| `exchange` | text |
| `company_name` | text |
| `market_cap` | bigint |
| `eligible` | boolean |
| `reason` | text |
| `n_targets` | integer |
| `mentions_180d` | bigint |
| `checked_at` | timestamp with time zone |
| `priority` | double precision |
| `last_run_at` | timestamp with time zone |
| `last_run_status` | text |
| `last_error` | text |
| `consecutive_failures` | integer |
| `cooldown_until` | date |
| `runs` | integer |
| `updated_at` | timestamp with time zone |

`last_run_status` values: `failed`, `ineligible`, `ok`, `skipped`

### `security_identity_map` (table)

*~2,019 rows, fresh to 2026-04-15*

Unified security identity map + graph integration Goal: - Keep ticker aliases and company-name aliases in one table. - Resolve graph edges to canonical tickers through that map.

| column | type |
|---|---|
| `id` | bigint |
| `alias_kind` | text |
| `alias_value` | text |
| `alias_value_norm` | text |
| `canonical_ticker` | text |
| `canonical_company_name` | text |
| `confidence` | double precision |
| `source` | text |
| `verified` | boolean |
| `metadata_json` | jsonb |
| `created_at` | timestamp with time zone |
| `updated_at` | timestamp with time zone |

`alias_kind` values: `company_name`, `ticker`

`source` values: `manual`, `manual_mcp`, `swingtrader.tickers`

### `telegram_message_log` (table)

*~1,253 rows*

telegram_message_log — record every Telegram message sent by the platform Populated by the Mac Mini cron (run_daily_narrative.py) and any future server-side Telegram sender.  Read-only from the UI for audit/debug.

| column | type |
|---|---|
| `id` | uuid |
| `user_id` | uuid |
| `chat_id` | character varying |
| `message_type` | character varying |
| `message_text` | text |
| `telegram_message_id` | bigint |
| `success` | boolean |
| `error_text` | text |
| `sent_at` | timestamp with time zone |

`message_type` values: `daily_narrative`, `market_screening_alert`, `market_screening_error`, `public_screening_alert`, `public_screening_no_trigger`, `screening_alert`, `screening_error`, `screening_no_trigger`

### `research_priced_in` (table)

*~650 rows, fresh to 2026-09-04*

1) What a price already contains, reconstructed at a point in time.

| column | type |
|---|---|
| `id` | bigint |
| `ticker` | text |
| `as_of` | date |
| `price` | double precision |
| `implied_revenue_cagr` | double precision |
| `discount_rate` | double precision |
| `terminal_growth` | double precision |
| `fcf_margin` | double precision |
| `n_targets` | integer |
| `target_low` | double precision |
| `target_high` | double precision |
| `target_median` | double precision |
| `median_gap` | double precision |
| `n_rejected_bull` | integer |
| `n_rejected_bear` | integer |
| `n_endorsed` | integer |
| `drivers_json` | jsonb |
| `cases_json` | jsonb |
| `summary` | text |
| `pipeline_version` | text |
| `model` | text |
| `generation_is_pit` | boolean |
| `note_slug` | text |
| `published` | boolean |
| `created_at` | timestamp with time zone |
| `summary_json` | jsonb |

`model` values: `claude-opus-5`, `glm-5.1:cloud`

### `arena_orders` (table)

*~562 rows, fresh to 2026-09-05*

── 3) Orders — the only thing an agent writes ────────────────────────────── An order is an INTENT until the fill pass runs. `status` walks pending -> filled | rejected | cancelled. Rejections keep their reason.

| column | type |
|---|---|
| `id` | uuid |
| `agent_id` | uuid |
| `decision_id` | uuid |
| `ticker` | text |
| `side` | text |
| `quantity` | numeric |
| `status` | text |
| `reject_reason` | text |
| `thesis` | text |
| `conviction` | numeric |
| `stop_price` | numeric |
| `target_price` | numeric |
| `submitted_at` | timestamp with time zone |
| `intended_for` | date |
| `filled_at` | timestamp with time zone |
| `fill_price` | numeric |
| `reference_price` | numeric |
| `slippage_bps` | numeric |
| `commission` | numeric |
| `notional` | numeric |
| `realized_pnl` | numeric |
| `realized_pct` | numeric |
| `created_at` | timestamp with time zone |
| `is_backtest` | boolean |
| `backtest_run_id` | uuid |
| `championship_id` | uuid |
| `position_effect` | text |

`status` values: `filled`, `pending`, `rejected`

### `arena_decisions` (table)

*~388 rows, fresh to 2026-09-05*

── 2) The decision record ────────────────────────────────────────────────── One row per agent per trading day. This is the public "why" — the narrative the agent gives for what it did, alongside the machine trace (which tools it called, how many rounds, how long) so a bad day can be diagnosed.

| column | type |
|---|---|
| `id` | uuid |
| `agent_id` | uuid |
| `decision_date` | date |
| `status` | text |
| `narrative` | text |
| `error` | text |
| `llm_model` | text |
| `rounds_used` | integer |
| `tools_called` | jsonb |
| `orders_requested` | integer |
| `orders_accepted` | integer |
| `orders_rejected` | integer |
| `nav_at_decision` | numeric |
| `cash_at_decision` | numeric |
| `started_at` | timestamp with time zone |
| `finished_at` | timestamp with time zone |
| `duration_ms` | integer |
| `created_at` | timestamp with time zone |
| `is_backtest` | boolean |
| `backtest_run_id` | uuid |
| `resources` | jsonb |
| `championship_id` | uuid |

`status` values: `error`, `ok`

`llm_model` values: `gemma4:31b-cloud`, `glm-5.1:cloud`

### `arena_nav_history` (table)

*~371 rows, fresh to 2026-09-05*

Arena: competing AI paper-trading agents What: - A set of autonomous agents, each funded with the same starting cash, each restricted to a DIFFERENT slice of the platform's data (news impact scores, the priced-in decomposition, the NIS Momentum screenings, FMP fundamentals, the relationship graph, pair z-scores, sentiment trends), trading against each other on a daily clock. The point is not to make money — it is to make the comparison between approaches falsifiable and public. Why the accounting lives here and not in the model: - The LLM's only write is an ORDER INTENT (arena_orders). Cash, p

| column | type |
|---|---|
| `id` | bigint |
| `agent_id` | uuid |
| `as_of` | date |
| `cash` | numeric |
| `long_value` | numeric |
| `short_value` | numeric |
| `nav` | numeric |
| `n_positions` | integer |
| `daily_return` | numeric |
| `cumulative_return` | numeric |
| `drawdown` | numeric |
| `positions` | jsonb |
| `created_at` | timestamp with time zone |
| `is_backtest` | boolean |
| `backtest_run_id` | uuid |
| `championship_id` | uuid |

### `research_predictions` (table)

*~65 rows, fresh to 2026-08-25*

2) Forward predictions. Sealed at creation; resolved once.

| column | type |
|---|---|
| `lock` | text |
| `ticker` | text |
| `driver` | text |
| `priced_in_pct` | double precision |
| `p_resolves` | double precision |
| `move_if_true` | double precision |
| `move_if_false` | double precision |
| `resolver` | text |
| `spec_json` | jsonb |
| `made_on` | date |
| `resolve_on` | date |
| `price_at_prediction` | double precision |
| `rationale` | text |
| `priced_in_id` | bigint |
| `outcome` | text |
| `outcome_detail` | jsonb |
| `resolved_at` | date |
| `price_at_resolution` | double precision |
| `realised_move` | double precision |
| `published` | boolean |
| `created_at` | timestamp with time zone |

### `arena_positions` (table)

*~64 rows, fresh to 2026-09-05*

── 4) Positions — current book, one row per (agent, ticker) ────────────────

| column | type |
|---|---|
| `id` | uuid |
| `agent_id` | uuid |
| `ticker` | text |
| `quantity` | numeric |
| `avg_cost` | numeric |
| `opened_at` | timestamp with time zone |
| `last_price` | numeric |
| `marked_at` | timestamp with time zone |
| `updated_at` | timestamp with time zone |
| `championship_id` | uuid |

### `early_access_signups` (table)

*~54 rows, fresh to 2026-08-23*

Early access signups: waitlist captured when a visitor (anonymous OR authenticated) clicks "Subscribe" on a public screening in the gallery. We do not auto-create a real subscription row. The product is in early- access mode; conversions to `public_screening_subscriptions` happen later via an admin/manual approval flow.

| column | type |
|---|---|
| `id` | bigint |
| `created_at` | timestamp with time zone |
| `email` | character varying |
| `source` | character varying |
| `contacted` | date |
| `metadata` | jsonb |
| `meta_capi_sent_at` | timestamp with time zone |

`source` values: `article`, `article_briefing`, `briefings_page`, `briefings_preset`, `landing`, `landing-hero`, `screening_detail_subscribe`

### `research_charts` (table)

*~40 rows, fresh to 2026-08-19*

Charts for the research lab. Companion to 20260819220000_quant_research_lab.sql. Images live in Supabase Storage; this table is the catalogue that gives each one its meaning. Two columns are NOT NULL for a reason that is specific to quant research. `sample_window` — an equity curve drawn on the window the search optimised over is the single most misleading artifact this lab produces. It always slopes up and to the right, because it was selected to. The same strategy's out-of-sample curve went from 5.5x the incumbent to +0.03. So no chart can be stored without declaring which window it is drawn

| column | type |
|---|---|
| `id` | bigint |
| `slug` | text |
| `title` | text |
| `caption` | text |
| `kind` | text |
| `sample_window` | text |
| `storage_path` | text |
| `public_url` | text |
| `bytes` | integer |
| `sha256` | text |
| `campaign_run_id` | text |
| `genome_hash` | text |
| `note_slug` | text |
| `trials_considered` | integer |
| `sort_order` | integer |
| `published` | boolean |
| `created_at` | timestamp with time zone |
| `updated_at` | timestamp with time zone |
| `width` | integer |
| `height` | integer |

`kind` values: `diagnostic`, `equity`, `exposure`, `folds`, `search_operators`, `search_reward`, `search_sources`, `sides`, `trades`

### `research_strategies` (table)

*~35 rows, fresh to 2026-08-19*

The strategies themselves: everything needed to re-run one exactly.

| column | type |
|---|---|
| `id` | bigint |
| `genome_hash` | text |
| `campaign_run_id` | text |
| `genome_json` | jsonb |
| `changes_vs_incumbent` | text |
| `dev_metrics` | jsonb |
| `fold_metrics` | jsonb |
| `holdout_metrics` | jsonb |
| `vault_metrics` | jsonb |
| `trials_considered` | integer |
| `deflated_sharpe` | double precision |
| `pbo` | double precision |
| `gate_passed` | boolean |
| `gate_failures` | ARRAY |
| `created_at` | timestamp with time zone |
| `published` | boolean |

### `arena_accounts` (table)

*~18 rows, fresh to 2026-09-05*

── 5) Cash + NAV history ─────────────────────────────────────────────────── `arena_accounts` is the single mutable cash row per agent; `arena_nav_history` is the append-only daily curve the leaderboard and charts read.

| column | type |
|---|---|
| `agent_id` | uuid |
| `cash` | numeric |
| `updated_at` | timestamp with time zone |
| `championship_id` | uuid |

### `arena_agents` (table)

*~9 rows, fresh to 2026-09-05*

── 1) The competitors ──────────────────────────────────────────────────────

| column | type |
|---|---|
| `id` | uuid |
| `slug` | text |
| `name` | text |
| `tagline` | text |
| `approach` | text |
| `strategy_key` | text |
| `engine` | text |
| `llm_backend` | text |
| `llm_model` | text |
| `max_tool_rounds` | integer |
| `starting_cash` | numeric |
| `max_position_pct` | numeric |
| `max_positions` | integer |
| `max_gross_exposure_pct` | numeric |
| `allow_shorts` | boolean |
| `is_active` | boolean |
| `is_published` | boolean |
| `funded_on` | date |
| `sort_order` | integer |
| `created_at` | timestamp with time zone |
| `updated_at` | timestamp with time zone |
| `inspiration` | text |
| `tool_surface` | jsonb |
| `target_exposure` | jsonb |

### `podcast_episodes` (table)

*~6 rows, fresh to 2026-05-14*

| column | type |
|---|---|
| `id` | integer |
| `date` | date |
| `title` | text |
| `episode_url` | text |
| `duration_seconds` | integer |
| `script_word_count` | integer |
| `elevenlabs_chars` | integer |
| `estimated_cost_usd` | real |
| `status` | text |
| `created_at` | timestamp with time zone |
| `description` | text |
| `audio_url` | text |
| `cover_url` | text |
| `file_size_bytes` | bigint |
| `guid` | text |
| `published_at` | timestamp with time zone |

`status` values: `error`, `published`

### `telegram_update_requests` (table)

*~5 rows, fresh to 2026-05-08*

telegram_update_requests Queue table for on-demand Telegram /update requests. Webhook inserts pending rows; Mac worker processes and sends responses.

| column | type |
|---|---|
| `id` | uuid |
| `user_id` | uuid |
| `chat_id` | character varying |
| `status` | character varying |
| `requested_at` | timestamp with time zone |
| `started_at` | timestamp with time zone |
| `completed_at` | timestamp with time zone |
| `response_preview` | text |
| `telegram_message_id` | bigint |
| `error_text` | text |
| `created_at` | timestamp with time zone |
| `updated_at` | timestamp with time zone |
| `request_type` | character varying |
| `request_text` | text |

`request_type` values: `search`, `update`

### `api_rate_limits` (table)

*~1 rows*

api_rate_limits: 1-minute sliding window buckets

| column | type |
|---|---|
| `key_id` | uuid |
| `window_start` | timestamp with time zone |
| `request_count` | integer |

### `arena_agents_public_v` (view)

*view — row count n/a*

Arena: investor personas + decision provenance Two changes: 1) PERSONAS. The agents are renamed after the investor whose approach each one actually implements (Barren Wuffett runs the fundamentals book, Mark Minervine trades volume-confirmed breakouts, Burton Malarkey is the random walk). Slugs are UPDATED IN PLACE rather than re-inserted, so every order, decision and NAV row stays attached to its agent by id — a re-insert under a new slug would orphan the entire history. `inspiration` records whose style the agent implements, so the page can say it plainly instead of leaving readers to decode

| column | type |
|---|---|
| `id` | uuid |
| `slug` | text |
| `name` | text |
| `tagline` | text |
| `approach` | text |
| `inspiration` | text |
| `tool_surface` | jsonb |
| `engine` | text |
| `starting_cash` | numeric |
| `max_position_pct` | numeric |
| `max_positions` | integer |
| `allow_shorts` | boolean |
| `funded_on` | date |
| `sort_order` | integer |
| `is_active` | boolean |

### `arena_championships` (table)

*~0 rows, fresh to 2026-09-03*

── 1) The championships ────────────────────────────────────────────────────

| column | type |
|---|---|
| `id` | uuid |
| `slug` | text |
| `name` | text |
| `description` | text |
| `starts_on` | date |
| `ends_on` | date |
| `status` | text |
| `starting_cash` | numeric |
| `is_backtest` | boolean |
| `champion_agent_id` | uuid |
| `runner_up_agent_id` | uuid |
| `champion_return` | numeric |
| `concluded_at` | timestamp with time zone |
| `created_at` | timestamp with time zone |
| `updated_at` | timestamp with time zone |

`status` values: `running`, `upcoming`

### `arena_championships_public_v` (view)

*view — row count n/a*

Arena: championships and the title lineage Why: - An open-ended leaderboard has no drama and no end state. Whoever is ahead is ahead "so far", forever, and a bad first week follows an agent for months. A championship is a FIXED WINDOW — every agent starts it on the same day with the same cash — so it can be won, and then run again. - The title carries between championships. The winner holds it until another agent wins a later championship; consecutive wins are defences. That is the thing worth following: not "who is up 3% since June" but "who took the belt off whom, and how long did they keep 

| column | type |
|---|---|
| `id` | uuid |
| `slug` | text |
| `name` | text |
| `description` | text |
| `starts_on` | date |
| `ends_on` | date |
| `status` | text |
| `starting_cash` | numeric |
| `is_backtest` | boolean |
| `concluded_at` | timestamp with time zone |
| `champion_return` | numeric |
| `champion_slug` | text |
| `champion_name` | text |
| `runner_up_slug` | text |
| `runner_up_name` | text |
| `entrants` | bigint |

### `arena_decisions_public_v` (view)

*view — row count n/a*

arena public views: expose championship_id The championships migration added `championship_id` to the base tables but did not add it to the public views. The UI then scoped its reads by that column, so every query failed with 42703 — and because the server actions catch errors and return an empty array, the failure surfaced as "No sessions marked yet" on charts for agents that had 46 sessions of history. Silent-empty is the worst failure shape available here: a broken query and a genuinely new agent look identical on the page. The columns are added to all four views, not just the NAV one, so p

| column | type |
|---|---|
| `agent_slug` | text |
| `id` | uuid |
| `agent_id` | uuid |
| `championship_id` | uuid |
| `decision_date` | date |
| `status` | text |
| `narrative` | text |
| `rounds_used` | integer |
| `tools_called` | jsonb |
| `resources` | jsonb |
| `orders_requested` | integer |
| `orders_accepted` | integer |
| `orders_rejected` | integer |
| `nav_at_decision` | numeric |
| `cash_at_decision` | numeric |
| `duration_ms` | integer |
| `finished_at` | timestamp with time zone |
| `is_backtest` | boolean |

### `arena_leaderboard_v` (view)

*view — row count n/a*

Arena: championships and the title lineage Why: - An open-ended leaderboard has no drama and no end state. Whoever is ahead is ahead "so far", forever, and a bad first week follows an agent for months. A championship is a FIXED WINDOW — every agent starts it on the same day with the same cash — so it can be won, and then run again. - The title carries between championships. The winner holds it until another agent wins a later championship; consecutive wins are defences. That is the thing worth following: not "who is up 3% since June" but "who took the belt off whom, and how long did they keep 

| column | type |
|---|---|
| `championship_id` | uuid |
| `championship_slug` | text |
| `championship_name` | text |
| `championship_status` | text |
| `starts_on` | date |
| `ends_on` | date |
| `championship_is_backtest` | boolean |
| `id` | uuid |
| `slug` | text |
| `name` | text |
| `tagline` | text |
| `inspiration` | text |
| `engine` | text |
| `sort_order` | integer |
| `starting_cash` | numeric |
| `as_of` | date |
| `nav` | numeric |
| `cash` | numeric |
| `long_value` | numeric |
| `short_value` | numeric |
| `n_positions` | integer |
| `daily_return` | numeric |
| `total_return` | numeric |
| `max_drawdown` | numeric |
| `nav_days` | bigint |
| `sharpe` | double precision |
| `filled_orders` | bigint |
| `closed_trades` | bigint |
| `winning_trades` | bigint |
| `win_rate` | numeric |
| `realized_pnl` | numeric |
| `avg_realized_pct` | numeric |
| `is_champion` | boolean |

### `arena_nav_history_public_v` (view)

*view — row count n/a*

arena public views: expose championship_id The championships migration added `championship_id` to the base tables but did not add it to the public views. The UI then scoped its reads by that column, so every query failed with 42703 — and because the server actions catch errors and return an empty array, the failure surfaced as "No sessions marked yet" on charts for agents that had 46 sessions of history. Silent-empty is the worst failure shape available here: a broken query and a genuinely new agent look identical on the page. The columns are added to all four views, not just the NAV one, so p

| column | type |
|---|---|
| `agent_slug` | text |
| `agent_id` | uuid |
| `championship_id` | uuid |
| `as_of` | date |
| `nav` | numeric |
| `cash` | numeric |
| `long_value` | numeric |
| `short_value` | numeric |
| `n_positions` | integer |
| `daily_return` | numeric |
| `cumulative_return` | numeric |
| `drawdown` | numeric |
| `is_backtest` | boolean |
| `positions` | jsonb |

### `arena_orders_public_v` (view)

*view — row count n/a*

arena_orders.position_effect — what a fill DID to the book `side` alone stopped being readable the day every agent could short. A SELL is either closing a long or opening a short; a BUY is either opening a long or covering a short. The public order table rendered side as green/red, which inverts the meaning for both short cases: a new bearish position showed in the "exit" colour, and closing a bearish bet showed in the "entry" colour. It cannot be inferred reliably after the fact either. `realized_pnl` is set only on the portion of a fill that closes exposure, so side + realized_pnl separates 

| column | type |
|---|---|
| `agent_slug` | text |
| `id` | uuid |
| `agent_id` | uuid |
| `championship_id` | uuid |
| `decision_id` | uuid |
| `ticker` | text |
| `side` | text |
| `quantity` | numeric |
| `status` | text |
| `reject_reason` | text |
| `thesis` | text |
| `conviction` | numeric |
| `stop_price` | numeric |
| `target_price` | numeric |
| `submitted_at` | timestamp with time zone |
| `intended_for` | date |
| `filled_at` | timestamp with time zone |
| `fill_price` | numeric |
| `notional` | numeric |
| `realized_pnl` | numeric |
| `realized_pct` | numeric |
| `is_backtest` | boolean |
| `position_effect` | text |

### `arena_positions_public_v` (view)

*view — row count n/a*

arena public views: expose championship_id The championships migration added `championship_id` to the base tables but did not add it to the public views. The UI then scoped its reads by that column, so every query failed with 42703 — and because the server actions catch errors and return an empty array, the failure surfaced as "No sessions marked yet" on charts for agents that had 46 sessions of history. Silent-empty is the worst failure shape available here: a broken query and a genuinely new agent look identical on the page. The columns are added to all four views, not just the NAV one, so p

| column | type |
|---|---|
| `agent_slug` | text |
| `agent_id` | uuid |
| `championship_id` | uuid |
| `ticker` | text |
| `quantity` | numeric |
| `avg_cost` | numeric |
| `last_price` | numeric |
| `marked_at` | timestamp with time zone |
| `opened_at` | timestamp with time zone |
| `market_value` | numeric |
| `unrealized_pnl` | numeric |
| `unrealized_pct` | numeric |

### `arena_title_lineage_v` (view)

*view — row count n/a*

Arena: championships and the title lineage Why: - An open-ended leaderboard has no drama and no end state. Whoever is ahead is ahead "so far", forever, and a bad first week follows an agent for months. A championship is a FIXED WINDOW — every agent starts it on the same day with the same cash — so it can be won, and then run again. - The title carries between championships. The winner holds it until another agent wins a later championship; consecutive wins are defences. That is the thing worth following: not "who is up 3% since June" but "who took the belt off whom, and how long did they keep 

| column | type |
|---|---|
| `reign_no` | bigint |
| `agent_id` | uuid |
| `agent_slug` | text |
| `agent_name` | text |
| `held_from` | date |
| `held_through` | date |
| `championships_won` | bigint |
| `successful_defences` | bigint |
| `championship_slugs` | ARRAY |
| `is_current_holder` | boolean |

### `daily_narratives` (table)

*~0 rows*

── daily_narratives ─────────────────────────────────────────────────────────

| column | type |
|---|---|
| `id` | uuid |
| `user_id` | uuid |
| `narrative_date` | date |
| `portfolio_section` | jsonb |
| `screening_section` | jsonb |
| `alert_warnings` | jsonb |
| `market_pulse` | text |
| `model` | character varying |
| `latency_ms` | integer |
| `generated_at` | timestamp with time zone |
| `delivered_at` | timestamp with time zone |
| `market_pulse_sources` | jsonb |

`model` values: `gemma4:31b-cloud`, `gemma4:e4b`

### `research_artifacts` (table)

*~0 rows, fresh to 2026-08-19*

Artifacts attached to a research write-up. The notes reference the files they were computed from — a pre-registration record, a results JSON, a data panel. Printed as bare local paths those references are worse than useless: they look like evidence while pointing at a directory on one laptop. So each referenced file becomes a row. Either it is genuinely downloadable (`available = true`, with a public URL), or it is not, and `reason` has to say why. The second case is not a gap to hide — "this panel is derived from licensed vendor data and cannot be redistributed" is information a replicator ne

| column | type |
|---|---|
| `id` | bigint |
| `note_slug` | text |
| `name` | text |
| `description` | text |
| `available` | boolean |
| `reason` | text |
| `public_url` | text |
| `storage_path` | text |
| `bytes` | bigint |
| `sha256` | text |
| `sort_order` | integer |
| `created_at` | timestamp with time zone |
| `updated_at` | timestamp with time zone |

### `research_artifacts_public_v` (view)

*view — row count n/a*

Artifacts attached to a research write-up. The notes reference the files they were computed from — a pre-registration record, a results JSON, a data panel. Printed as bare local paths those references are worse than useless: they look like evidence while pointing at a directory on one laptop. So each referenced file becomes a row. Either it is genuinely downloadable (`available = true`, with a public URL), or it is not, and `reason` has to say why. The second case is not a gap to hide — "this panel is derived from licensed vendor data and cannot be redistributed" is information a replicator ne

| column | type |
|---|---|
| `note_slug` | text |
| `name` | text |
| `description` | text |
| `available` | boolean |
| `reason` | text |
| `public_url` | text |
| `bytes` | bigint |
| `sha256` | text |
| `sort_order` | integer |

### `research_campaigns` (table)

*~0 rows, fresh to 2026-08-19*

Autonomous quant research lab — the published record. Written by strategylab's research daemon, read by the public site. The whole point is that a reader can REPLICATE, so every row carries the exact inputs (genome, protocol, data window, universe) alongside the result. The schema encodes one hard-won lesson: a single good backtest is not a finding. Everything the lab produced that looked good on first sight failed its first honest replication — a pre-filter worth +0.156 Sharpe on one genome ... p = 0.53 across seven an "impact law" with R2 = 0.83 ................... p = 0.92 out of sample a s

| column | type |
|---|---|
| `id` | bigint |
| `run_id` | text |
| `started_at` | timestamp with time zone |
| `ended_at` | timestamp with time zone |
| `protocol_version` | text |
| `universe_size` | integer |
| `prefilter` | text |
| `dev_start` | date |
| `dev_end` | date |
| `costs_json` | jsonb |
| `iterations` | integer |
| `trials_own` | integer |
| `trials_inherited` | integer |
| `best_genome_hash` | text |
| `best_reward` | double precision |
| `best_sharpe` | double precision |
| `pbo` | double precision |
| `stop_reason` | text |
| `stop_detail` | text |
| `models_used` | jsonb |
| `created_at` | timestamp with time zone |

### `research_charts_public_v` (view)

*view — row count n/a*

Intrinsic pixel dimensions for chart images. Not cosmetic. The figures are lazy-loaded, and a lazy <img> with no width or height collapses to zero height until it loads — so it never enters the viewport, so it never loads. Seven figures rendered as a 0px-tall region and the whole article measured 966px. Storing the real dimensions lets the page reserve the right box up front, which both fixes the deadlock and removes the layout shift when each plot arrives.

| column | type |
|---|---|
| `slug` | text |
| `title` | text |
| `caption` | text |
| `kind` | text |
| `sample_window` | text |
| `public_url` | text |
| `width` | integer |
| `height` | integer |
| `campaign_run_id` | text |
| `genome_hash` | text |
| `note_slug` | text |
| `trials_considered` | integer |
| `sort_order` | integer |
| `created_at` | timestamp with time zone |
| `is_in_sample` | boolean |

### `research_findings` (table)

*~0 rows*

Findings: claims, and how much evidence stands behind each one.

| column | type |
|---|---|
| `id` | bigint |
| `slug` | text |
| `claim` | text |
| `status` | text |
| `replications` | integer |
| `refutations` | integer |
| `evidence_json` | jsonb |
| `caveats` | text |
| `reproduce_command` | text |
| `source_campaign` | text |
| `published` | boolean |
| `created_at` | timestamp with time zone |
| `updated_at` | timestamp with time zone |

### `research_leaderboard_v` (view)

*view — row count n/a*

Autonomous quant research lab — the published record. Written by strategylab's research daemon, read by the public site. The whole point is that a reader can REPLICATE, so every row carries the exact inputs (genome, protocol, data window, universe) alongside the result. The schema encodes one hard-won lesson: a single good backtest is not a finding. Everything the lab produced that looked good on first sight failed its first honest replication — a pre-filter worth +0.156 Sharpe on one genome ... p = 0.53 across seven an "impact law" with R2 = 0.83 ................... p = 0.92 out of sample a s

| column | type |
|---|---|
| `genome_hash` | text |
| `campaign_run_id` | text |
| `dev_sharpe` | double precision |
| `holdout_sharpe` | double precision |
| `trials_considered` | integer |
| `deflated_sharpe` | double precision |
| `pbo` | double precision |
| `gate_passed` | boolean |
| `prefilter` | text |
| `dev_start` | date |
| `dev_end` | date |
| `created_at` | timestamp with time zone |

### `research_notes` (table)

*~0 rows, fresh to 2026-08-19*

Long-form write-ups (the markdown in research/), versioned by slug.

| column | type |
|---|---|
| `id` | bigint |
| `slug` | text |
| `title` | text |
| `summary` | text |
| `body_md` | text |
| `result_kind` | text |
| `tags` | ARRAY |
| `charts` | jsonb |
| `published` | boolean |
| `created_at` | timestamp with time zone |
| `updated_at` | timestamp with time zone |

### `research_prediction_events` (table)

*~0 rows*

3) The ledger's log, moved with the ledger.

| column | type |
|---|---|
| `id` | bigint |
| `at` | timestamp with time zone |
| `kind` | text |
| `lock` | text |
| `payload` | jsonb |

### `research_predictions_integrity_v` (view)

*view — row count n/a*

5) Integrity. Anything listed here means the ledger was edited outside the intended path; the client recomputes the hash and compares.

| column | type |
|---|---|
| `lock` | text |
| `ticker` | text |
| `driver` | text |
| `made_on` | date |
| `resolve_on` | date |
| `outcome` | text |
| `resolved_without_date` | boolean |
| `overdue` | boolean |

### `research_predictions_scored_v` (view)

*view — row count n/a*

4) Scoring view. Brier is reported per row; the base-rate comparison has to be done over a set, because a Brier score in absolute means nothing — a 75% "beat" call against a 75% base rate is not skill.

| column | type |
|---|---|
| `lock` | text |
| `ticker` | text |
| `driver` | text |
| `priced_in_pct` | double precision |
| `resolver` | text |
| `p_resolves` | double precision |
| `move_if_true` | double precision |
| `move_if_false` | double precision |
| `made_on` | date |
| `resolve_on` | date |
| `resolved_at` | date |
| `outcome` | text |
| `price_at_prediction` | double precision |
| `price_at_resolution` | double precision |
| `realised_move` | double precision |
| `brier` | double precision |
| `cell` | text |

### `research_priced_in_public_v` (view)

*view — row count n/a*

Structured summary for research_priced_in. `summary` held the whole reconstruction as one ~1,500-character paragraph. The content was right — where the price sits, what it pays for, what it declines, and the one investigable question — but all four ran together, and on a quote page that is a wall nobody reads. Splitting it at GENERATION rather than parsing it out afterwards: the model already knows which sentence is doing which job, so asking for the parts is both more reliable than a regex and better prose, because each part is now written to stand alone. `summary` is kept and still populated

| column | type |
|---|---|
| `ticker` | text |
| `as_of` | date |
| `price` | double precision |
| `implied_revenue_cagr` | double precision |
| `n_targets` | integer |
| `target_low` | double precision |
| `target_high` | double precision |
| `target_median` | double precision |
| `median_gap` | double precision |
| `drivers_json` | jsonb |
| `summary` | text |
| `created_at` | timestamp with time zone |
| `summary_json` | jsonb |

### `research_priced_in_queue_v` (view)

*view — row count n/a*

4) What the batch runner asks for: the next names due. Kept as a view so the ordering rule is stated once, in the database, rather than reimplemented in whichever process happens to be draining the queue. `due_days` is a parameter of the caller, so the view exposes the age and lets the caller threshold it.

| column | type |
|---|---|
| `symbol` | text |
| `exchange` | text |
| `company_name` | text |
| `market_cap` | bigint |
| `n_targets` | integer |
| `mentions_180d` | bigint |
| `priority` | double precision |
| `last_run_at` | timestamp with time zone |
| `last_run_status` | text |
| `consecutive_failures` | integer |
| `cooldown_until` | date |
| `last_as_of` | date |
| `last_published` | boolean |
| `days_since_run` | integer |

### `research_priced_in_runs` (table)

*~0 rows*

2) One row per batch pass.

| column | type |
|---|---|
| `id` | bigint |
| `started_at` | timestamp with time zone |
| `ended_at` | timestamp with time zone |
| `backend` | text |
| `models` | text |
| `pipeline_version` | text |
| `attempted` | integer |
| `succeeded` | integer |
| `failed` | integer |
| `published` | integer |
| `held` | integer |
| `predictions_registered` | integer |
| `usage_json` | jsonb |
| `stop_reason` | text |
| `detail` | text |

### `research_public_v` (view)

*view — row count n/a*

Public read access. Only PUBLISHED rows, and only through a view, so a half-finished campaign cannot leak onto the site mid-run.

| column | type |
|---|---|
| `slug` | text |
| `title` | text |
| `summary` | text |
| `body_md` | text |
| `result_kind` | text |
| `tags` | ARRAY |
| `charts` | jsonb |
| `created_at` | timestamp with time zone |
| `updated_at` | timestamp with time zone |

### `topics` (table)

*~0 rows, fresh to 2026-08-03*

Topic hubs — permanent, auto-updating deep-dive pages over the scraped corpus. The idea: /articles publishes ~5k single-news-item URLs that rank for nothing (Search Console: 20 impressions, 0 clicks, avg position 24 over a week). Thin spokes don't earn topical authority; a small number of deep hubs can. A topic consolidates many articles into one evergreen page carrying the whole arc of a story — e.g. 15 months of the Iran conflict against the oil complex. A topic is a SAVED QUERY, not generated content: theme_tags  (what the story is)  AND  lens_tickers (who it hits) Membership is therefore a

| column | type |
|---|---|
| `slug` | text |
| `title` | text |
| `subtitle` | text |
| `theme_tags` | ARRAY |
| `lens_tickers` | ARRAY |
| `min_impact` | real |
| `visual_archetype` | text |
| `scene` | text |
| `accent` | text |
| `hero_tickers` | ARRAY |
| `thesis_ref` | text |
| `seo_description` | text |
| `is_published` | boolean |
| `created_at` | timestamp with time zone |
| `updated_at` | timestamp with time zone |
| `extra_keywords` | ARRAY |

## Functions

Callable via PostgREST `.rpc(name, {...})` or directly in SQL.

| function | arguments | returns |
|---|---|---|
| `arena_orders_immutable` | `` | trigger |
| `exec_ticker_coverage_refresh` | `` | void |
| `exec_ticker_relationship_heads_refresh` | `` | void |
| `exec_ticker_sentiment_heads_refresh` | `` | void |
| `exec_topic_claims_refresh` | `` | void |
| `get_relationship_neighborhood` | `p_seed text, p_hops integer, p_min_strength double precision, p_min_mentions integer, p_rel_types text[], p_limit_nodes integer, p_limit_edges integer, p_days_lookback integer` | TABLE(row_type text, seed_ticker text, node_ticker text, from_ticker text, to_ticker text, rel_type text, strength_avg double precision, strength_max double precision, mention_count integer, article_count integer, first_seen_at timestamp with time zone, last_seen_at timestamp with time zone, truncated boolean) |
| `get_relationship_node_news` | `p_ticker text, p_page integer, p_page_size integer, p_days_lookback integer` | TABLE(canonical_ticker text, article_id bigint, title text, url text, source text, publisher text, published_at timestamp with time zone, matched_ticker text) |
| `get_relationship_node_sentiment` | `p_ticker text, p_page integer, p_page_size integer` | TABLE(canonical_ticker text, head_id bigint, article_id bigint, ticker text, sentiment_score double precision, reasoning_text text, confidence double precision, article_ts timestamp with time zone, published_at timestamp with time zone, article_source text, article_publisher text, article_title text, article_url text) |
| `get_relationship_node_sentiment_windows` | `p_ticker text` | TABLE(days integer, avg_sentiment double precision, weighted_sentiment double precision, mention_count integer) |
| `get_ticker_impact_news` | `p_ticker text, p_days integer, p_limit integer, p_per_bucket integer` | TABLE(article_id bigint, title text, url text, source text, slug text, published_at timestamp with time zone, sentiment double precision, impact_magnitude double precision, top_dimensions jsonb) |
| `get_top_covered_tickers` | `p_days integer, p_limit integer, p_offset integer, p_search text` | TABLE(ticker text, mention_count bigint, scored_count bigint, avg_sentiment double precision, last_day date, company_name text, sector text, total_count bigint) |
| `get_topic_visuals` | `p_slug text` | jsonb |
| `impact_vector_magnitude` | `p_impact jsonb` | double precision |
| `increment_market_screening_download` | `p_id uuid` | bigint |
| `link_subscription_on_signup` | `` | trigger |
| `news_article_fts` | `title text, search_tags text[], body text` | tsvector |
| `news_articles_fts_maintain` | `` | trigger |
| `recompute_market_screenings_next_run_at` | `` | trigger |
| `refresh_relationship_network_mv` | `` | void |
| `refresh_ticker_coverage_daily` | `` | integer |
| `refresh_ticker_relationship_edge_evidence` | `p_lookback interval` | integer |
| `refresh_ticker_relationship_edges` | `p_lookback interval` | integer |
| `refresh_ticker_sentiment_heads` | `p_lookback interval` | integer |
| `refresh_topic_claims` | `p_slug text` | integer |
| `refresh_topic_stats` | `` | integer |
| `research_predictions_immutable` | `` | trigger |
| `resolve_canonical_graph_ticker` | `p_alias_value text` | text |
| `resolve_canonical_ticker` | `p_alias_value text, p_alias_kind text` | text |
| `search_news_article_embeddings_gte` | `query_embedding double precision[], match_count integer, lookback_days integer, stream_filter text` | TABLE(article_id bigint, title text, url text, source text, slug text, image_url text, article_stream text, published_at timestamp with time zone, snippet text, similarity double precision) |
| `search_news_by_tags` | `tag_filter text[], match_count integer, lookback_hours integer, stream_filter text` | TABLE(article_id bigint, title text, url text, source text, slug text, image_url text, article_stream text, published_at timestamp with time zone, snippet text, similarity double precision) |
| `search_news_embeddings` | `query_embedding double precision[], match_count integer, lookback_hours integer, stream_filter text, ticker_filter text[], as_of timestamp with time zone` | TABLE(article_id bigint, title text, url text, source text, slug text, image_url text, article_stream text, published_at timestamp with time zone, snippet text, similarity double precision) |
| `search_news_fulltext` | `query_text text, match_count integer, lookback_hours integer, stream_filter text` | TABLE(article_id bigint, title text, url text, source text, slug text, image_url text, article_stream text, published_at timestamp with time zone, snippet text, similarity double precision) |
| `set_news_article_slug` | `` | trigger |
| `set_user_profiles_updated_at` | `` | trigger |
| `topic_keywords` | `p_slug text` | text[] |
| `touch_arena_championship` | `` | trigger |
| `touch_arena_updated_at` | `` | trigger |
| `touch_market_screenings_updated_at` | `` | trigger |
| `touch_narrative_prefs_updated_at` | `` | trigger |
| `touch_portfolio_alerts_updated_at` | `` | trigger |
| `touch_scheduled_screenings_updated_at` | `` | trigger |
| `touch_security_identity_map_updated_at` | `` | trigger |
| `touch_telegram_connections_updated_at` | `` | trigger |
| `touch_telegram_update_requests_updated_at` | `` | trigger |
| `touch_ticker_pair_stats_updated_at` | `` | trigger |
| `touch_ticker_relationship_edges_updated_at` | `` | trigger |
| `touch_user_subscriptions` | `` | trigger |
| `touch_user_ticker_chart_workspace_updated_at` | `` | trigger |
| `touch_user_trade_reviews_updated_at` | `` | trigger |
| `touch_user_trades_updated_at` | `` | trigger |
| `trg_set_impact_magnitude` | `` | trigger |
| `trg_stmt_nih_rel_graph_del` | `` | trigger |
| `trg_stmt_nih_rel_graph_ins` | `` | trigger |
| `trg_stmt_nih_rel_graph_upd` | `` | trigger |
| `validate_api_key` | `p_key_hash text, p_rate_limit_per_minute integer` | TABLE(key_id uuid, user_id uuid, scopes text[], rate_ok boolean) |
