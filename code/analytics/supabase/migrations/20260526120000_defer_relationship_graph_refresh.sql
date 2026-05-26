-- ---------------------------------------------------------------------------
-- Defer ticker relationship graph refresh (fix statement timeouts on ingest)
--
-- The INSERT/UPDATE/DELETE triggers on news_impact_heads called
-- exec_ticker_relationship_heads_refresh() → full-history re-scan on every
-- head write. That exceeds Supabase statement_timeout during score_cli batches.
--
-- Batch writers (score_cli) call exec_ticker_relationship_heads_refresh() once
-- per run instead. Schedule the same RPC via cron for other writers if needed.
-- ---------------------------------------------------------------------------

DROP TRIGGER IF EXISTS trg_news_impact_heads_refresh_relationship_graph_ins ON swingtrader.news_impact_heads;
DROP TRIGGER IF EXISTS trg_news_impact_heads_refresh_relationship_graph_upd ON swingtrader.news_impact_heads;
DROP TRIGGER IF EXISTS trg_news_impact_heads_refresh_relationship_graph_del ON swingtrader.news_impact_heads;

GRANT EXECUTE ON FUNCTION swingtrader.exec_ticker_relationship_heads_refresh() TO service_role;
