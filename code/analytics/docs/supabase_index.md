# swingtrader schema index (generated 2026-09-05)

## Relationships & graph
- `ticker_relationship_edge_evidence` (table, ~88,286 @2026-09-05) Ticker relationship edge traceability Goal: - Provide deterministic traceability from ticker_relationship_edge
- `ticker_relationship_edges` (table, ~39,685 @2026-09-05) Ticker Relationship Network (graph-ready adjacency structure) Why: - Avoid scanning/parsing JSONB relationship
- `ticker_relationship_network_resolved_mv` (matview, ~21,734) Relationship network materialization Problem (statement timeout on /protected/relations): ticker_relationship_
- `ticker_pair_stats` (table, ~795 @2026-09-03) Ticker Pair Stats (cointegration / pairs-trading metrics on the graph) Why: - The news-derived relationship gr
- `ticker_pair_candidates_v` (view) Candidate pairs: order-normalized, deduped across rel_types, off the canonicalized graph
- `ticker_relationship_edge_traceability_v` (view) Ticker relationship edge traceability Goal: - Provide deterministic traceability from ticker_relationship_edge
- `ticker_relationship_network_pairs_v` (view) The stitched view: every news-derived edge, now carrying its pair's live cointegration metrics
- `ticker_relationship_network_resolved_v` (view) Canonicalized graph view for adjacency traversal.
- `ticker_relationship_network_v` (view) Ticker Relationship Network (graph-ready adjacency structure) Why: - Avoid scanning/parsing JSONB relationship

## News: articles & scoring
- `news_impact_heads` (table, ~2,651,283 @2026-09-05) news_impact_heads: per-cluster LLM scoring results
- `news_article_embeddings` (table, ~1,853,533) Embedding setup for semantic retrieval over scored news.
- `news_article_tickers` (table, ~739,882) news_article_tickers: ticker mentions extracted from articles
- `news_articles` (table, ~226,391 @2026-09-05) news_articles: article content and metadata
- `news_article_embedding_jobs` (table, ~225,591 @2026-09-05) Embedding setup for semantic retrieval over scored news.
- `news_impact_vectors` (table, ~209,330 @2026-09-05) news_impact_vectors: aggregated impact dimension vectors
- `news_source_dry_days` (table, ~691) Track calendar days where a news source stream has been fully exhausted (all available articles fetched/proces
- `news_embedding_hourly_cluster_articles` (table, ~57) Hourly / daily embedding clusters over swingtrader.news_article_embeddings (UTC buckets)
- `news_briefing_subscriptions` (table, ~34 @2026-09-04) News briefing subscriptions: the free, no-account email service that sends a nicely structured PDF of the last
- `news_embedding_daily_cluster_articles` (table, ~0) Hourly / daily embedding clusters over swingtrader.news_article_embeddings (UTC buckets)
- `news_embedding_daily_cluster_centroids` (table, ~0) Hourly / daily embedding clusters over swingtrader.news_article_embeddings (UTC buckets)
- `news_embedding_daily_cluster_runs` (table, ~0) ── Daily ───────────────────────────────────────────────────────────────────
- `news_embedding_hourly_cluster_centroids` (table, ~0) Hourly / daily embedding clusters over swingtrader.news_article_embeddings (UTC buckets)
- `news_embedding_hourly_cluster_runs` (table, ~0) ── Hourly ─────────────────────────────────────────────────────────────────
- `news_trends_article_base_v` (view) 1) Article-level base rows with parsed vectors + mean confidence.
- `news_trends_cluster_daily_v` (view) 4) Cluster rollups from dimensions, matching UI logic: per-article cluster = mean(dimensions in cluster), then
- `news_trends_cluster_hourly_v` (view) Bound hourly news-trends views to last 60 days so their CTEs don't scan the full base table
- `news_trends_dimension_cluster_map_v` (view) 
- `news_trends_dimension_daily_v` (view) 3) Dimension aggregates (daily / hourly), weighted and unweighted.
- `news_trends_dimension_hourly_v` (view) Bound hourly news-trends views to last 60 days so their CTEs don't scan the full base table
- `news_trends_dimension_points_v` (view) 2) One row per article/dimension with numeric value.
- `news_trends_heads_daily_v` (view) 5) Head-level aggregates for diagnostics/trend overlays.
- `news_trends_heads_hourly_v` (view) Pre-aggregated views for News Trends charts
- `news_trends_tag_daily_v` (view) 2) Theme-tag frequency per day
- `news_trends_ticker_daily_v` (view) 1) Ticker mentions per day, with sentiment overlay

## News: topics & claims
- `topic_claim_stats` (table, ~1,497 @2026-09-05) topic_claim_stats — the materialized half
- `topic_stats` (table, ~2) Materialize the topic headline counts
- `topic_article_v` (view) topic_article_v — the membership query, as a view

## Tickers: sentiment & coverage
- `ticker_sentiment_heads` (table, ~364,321 @2026-09-05) Ticker Sentiment Materialization (pre-exploded, indexed) Why: - swingtrader.ticker_sentiment_heads_v explodes 
- `ticker_coverage_daily` (table, ~60,400 @2026-09-05) Materialize the /quote directory's daily rollup
- `ticker_sentiment_heads_v` (view) Ticker Sentiment View (article-level, parsed from TICKER_SENTIMENT heads) Why: - Expose sentiment by (article,

## Company factor vectors
- `company_vectors` (table, ~3,401 @2026-04-29) company_vectors: fundamental dimension vectors per ticker per date

## Screening & scans
- `market_screening_result_rows` (table, ~134,149 @2026-09-05) 
- `market_screening_results` (table, ~4,296 @2026-09-05) 
- `market_screening_email_subscriptions` (table, ~23 @2026-08-19) Market screening EMAIL subscriptions: the lightweight, email-only delivery list that powers the "Send me the r
- `market_screenings` (table, ~10 @2026-09-05) 
- `market_screening_subscriptions` (table, ~0) 

## Users, plans & billing
- `user_scan_rows` (table, ~68,397 @2026-09-04) 
- `user_scan_row_notes` (table, ~21,384 @2026-09-04) 
- `user_ticker_chart_workspace` (table, ~5,319 @2026-09-05) Per-user chart workspace: annotations + Chart AI conversation, keyed by ticker
- `user_screening_results` (table, ~2,492 @2026-09-05) ── user_screening_results ──────────────────────────────────────────────────
- `user_scan_jobs` (table, ~306 @2026-09-04) 
- `user_scan_runs` (table, ~216 @2026-09-04) 
- `user_trades` (table, ~36 @2026-08-15) user_trades: per-user trade ledger (buy/sell × long/short) Semantics: side            : 'buy' | 'sell' (execut
- `user_profiles` (table, ~15 @2026-08-31) user_profiles Per-user app state that doesn't belong in auth.users.user_metadata
- `user_bulk_analysis_jobs` (table, ~6 @2026-06-02) user_bulk_analysis_jobs Tracks fire-and-forget bulk per-ticker technical-analysis jobs
- `user_scheduled_screenings` (table, ~5 @2026-09-05) ── user_scheduled_screenings ────────────────────────────────────────────────
- `user_api_keys` (table, ~2 @2026-04-12) user_api_keys
- `user_subscriptions` (table, ~1 @2026-08-31) user_subscriptions Tracks Stripe subscriptions per user
- `user_narrative_preferences` (table, ~0 @2026-04-12) ── user_narrative_preferences ────────────────────────────────────────────────
- `user_portfolio_alerts` (table, ~0) ── user_portfolio_alerts ─────────────────────────────────────────────────────
- `user_telegram_connections` (table, ~0 @2026-08-06) user_telegram_connections: general-purpose Telegram account linkage Decoupled from user_narrative_preferences 
- `user_trade_reviews` (table, ~0 @2026-06-07) user_trade_reviews: AI post-trade review chats keyed by the closing trade A "review" lives on the trade row th
- `user_trading_strategy` (table, ~0 @2026-08-18) 

## Agents & jobs
- `job_runs` (table, ~256,091 @2026-09-05) 
- `job_health` (table, ~15) 

## Other
- `tickers` (table, ~5,810 @2026-08-08) tickers: universe of actively-traded NYSE and NASDAQ stocks Seeded via scripts/seed_tickers.py (FMP company-sc
- `research_priced_in_universe` (table, ~5,807 @2026-09-04) 1) The working universe and its schedule.
- `security_identity_map` (table, ~2,019 @2026-04-15) Unified security identity map + graph integration Goal: - Keep ticker aliases and company-name aliases in one 
- `telegram_message_log` (table, ~1,253) telegram_message_log — record every Telegram message sent by the platform Populated by the Mac Mini cron (run_
- `research_priced_in` (table, ~650 @2026-09-04) 1) What a price already contains, reconstructed at a point in time.
- `arena_orders` (table, ~562 @2026-09-05) ── 3) Orders — the only thing an agent writes ────────────────────────────── An order is an INTENT until the f
- `arena_decisions` (table, ~388 @2026-09-05) ── 2) The decision record ────────────────────────────────────────────────── One row per agent per trading day
- `arena_nav_history` (table, ~371 @2026-09-05) Arena: competing AI paper-trading agents What: - A set of autonomous agents, each funded with the same startin
- `research_predictions` (table, ~65 @2026-08-25) 2) Forward predictions
- `arena_positions` (table, ~64 @2026-09-05) ── 4) Positions — current book, one row per (agent, ticker) ────────────────
- `early_access_signups` (table, ~54 @2026-08-23) Early access signups: waitlist captured when a visitor (anonymous OR authenticated) clicks "Subscribe" on a pu
- `research_charts` (table, ~40 @2026-08-19) Charts for the research lab
- `research_strategies` (table, ~35 @2026-08-19) The strategies themselves: everything needed to re-run one exactly.
- `arena_accounts` (table, ~18 @2026-09-05) ── 5) Cash + NAV history ─────────────────────────────────────────────────── `arena_accounts` is the single mu
- `arena_agents` (table, ~9 @2026-09-05) ── 1) The competitors ──────────────────────────────────────────────────────
- `podcast_episodes` (table, ~6 @2026-05-14) 
- `telegram_update_requests` (table, ~5 @2026-05-08) telegram_update_requests Queue table for on-demand Telegram /update requests
- `api_rate_limits` (table, ~1) api_rate_limits: 1-minute sliding window buckets
- `arena_championships` (table, ~0 @2026-09-03) ── 1) The championships ────────────────────────────────────────────────────
- `daily_narratives` (table, ~0) ── daily_narratives ─────────────────────────────────────────────────────────
- `research_artifacts` (table, ~0 @2026-08-19) Artifacts attached to a research write-up
- `research_campaigns` (table, ~0 @2026-08-19) Autonomous quant research lab — the published record
- `research_findings` (table, ~0) Findings: claims, and how much evidence stands behind each one.
- `research_notes` (table, ~0 @2026-08-19) Long-form write-ups (the markdown in research/), versioned by slug.
- `research_prediction_events` (table, ~0) 3) The ledger's log, moved with the ledger.
- `research_priced_in_runs` (table, ~0) 2) One row per batch pass.
- `topics` (table, ~0 @2026-08-03) Topic hubs — permanent, auto-updating deep-dive pages over the scraped corpus
- `arena_agents_public_v` (view) Arena: investor personas + decision provenance Two changes: 1) PERSONAS
- `arena_championships_public_v` (view) Arena: championships and the title lineage Why: - An open-ended leaderboard has no drama and no end state
- `arena_decisions_public_v` (view) arena public views: expose championship_id The championships migration added `championship_id` to the base tab
- `arena_leaderboard_v` (view) Arena: championships and the title lineage Why: - An open-ended leaderboard has no drama and no end state
- `arena_nav_history_public_v` (view) arena public views: expose championship_id The championships migration added `championship_id` to the base tab
- `arena_orders_public_v` (view) arena_orders.position_effect — what a fill DID to the book `side` alone stopped being readable the day every a
- `arena_positions_public_v` (view) arena public views: expose championship_id The championships migration added `championship_id` to the base tab
- `arena_title_lineage_v` (view) Arena: championships and the title lineage Why: - An open-ended leaderboard has no drama and no end state
- `research_artifacts_public_v` (view) Artifacts attached to a research write-up
- `research_charts_public_v` (view) Intrinsic pixel dimensions for chart images
- `research_leaderboard_v` (view) Autonomous quant research lab — the published record
- `research_predictions_integrity_v` (view) 5) Integrity
- `research_predictions_scored_v` (view) 4) Scoring view
- `research_priced_in_public_v` (view) Structured summary for research_priced_in
- `research_priced_in_queue_v` (view) 4) What the batch runner asks for: the next names due
- `research_public_v` (view) Public read access

## Functions
- `arena_orders_immutable()`
- `exec_ticker_coverage_refresh()`
- `exec_ticker_relationship_heads_refresh()`
- `exec_ticker_sentiment_heads_refresh()`
- `exec_topic_claims_refresh()`
- `get_relationship_neighborhood(p_seed text, p_hops integer, p_min_strength double precision, p_min_mentions integer, p_rel_types text[], p_limit_nodes integer, p_limit_edges integer, p_days_lookback integer)`
- `get_relationship_node_news(p_ticker text, p_page integer, p_page_size integer, p_days_lookback integer)`
- `get_relationship_node_sentiment(p_ticker text, p_page integer, p_page_size integer)`
- `get_relationship_node_sentiment_windows(p_ticker text)`
- `get_ticker_impact_news(p_ticker text, p_days integer, p_limit integer, p_per_bucket integer)`
- `get_top_covered_tickers(p_days integer, p_limit integer, p_offset integer, p_search text)`
- `get_topic_visuals(p_slug text)`
- `impact_vector_magnitude(p_impact jsonb)`
- `increment_market_screening_download(p_id uuid)`
- `link_subscription_on_signup()`
- `news_article_fts(title text, search_tags text[], body text)`
- `news_articles_fts_maintain()`
- `recompute_market_screenings_next_run_at()`
- `refresh_relationship_network_mv()`
- `refresh_ticker_coverage_daily()`
- `refresh_ticker_relationship_edge_evidence(p_lookback interval)`
- `refresh_ticker_relationship_edges(p_lookback interval)`
- `refresh_ticker_sentiment_heads(p_lookback interval)`
- `refresh_topic_claims(p_slug text)`
- `refresh_topic_stats()`
- `research_predictions_immutable()`
- `resolve_canonical_graph_ticker(p_alias_value text)`
- `resolve_canonical_ticker(p_alias_value text, p_alias_kind text)`
- `search_news_article_embeddings_gte(query_embedding double precision[], match_count integer, lookback_days integer, stream_filter text)`
- `search_news_by_tags(tag_filter text[], match_count integer, lookback_hours integer, stream_filter text)`
- `search_news_embeddings(query_embedding double precision[], match_count integer, lookback_hours integer, stream_filter text, ticker_filter text[], as_of timestamp with time zone)`
- `search_news_fulltext(query_text text, match_count integer, lookback_hours integer, stream_filter text)`
- `set_news_article_slug()`
- `set_user_profiles_updated_at()`
- `topic_keywords(p_slug text)`
- `touch_arena_championship()`
- `touch_arena_updated_at()`
- `touch_market_screenings_updated_at()`
- `touch_narrative_prefs_updated_at()`
- `touch_portfolio_alerts_updated_at()`
- `touch_scheduled_screenings_updated_at()`
- `touch_security_identity_map_updated_at()`
- `touch_telegram_connections_updated_at()`
- `touch_telegram_update_requests_updated_at()`
- `touch_ticker_pair_stats_updated_at()`
- `touch_ticker_relationship_edges_updated_at()`
- `touch_user_subscriptions()`
- `touch_user_ticker_chart_workspace_updated_at()`
- `touch_user_trade_reviews_updated_at()`
- `touch_user_trades_updated_at()`
- `trg_set_impact_magnitude()`
- `trg_stmt_nih_rel_graph_del()`
- `trg_stmt_nih_rel_graph_ins()`
- `trg_stmt_nih_rel_graph_upd()`
- `validate_api_key(p_key_hash text, p_rate_limit_per_minute integer)`