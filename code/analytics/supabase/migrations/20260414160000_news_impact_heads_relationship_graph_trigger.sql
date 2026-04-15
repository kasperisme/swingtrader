-- ---------------------------------------------------------------------------
-- Auto-refresh ticker relationship materialization when relevant heads change
--
-- news_impact_heads rows (cluster = TICKER_RELATIONSHIPS) feed
-- refresh_ticker_relationship_edges / refresh_ticker_relationship_edge_evidence.
-- Statement-level triggers + transition tables => one full refresh per SQL
-- statement, not once per row. Split by event (INSERT / UPDATE / DELETE) because
-- PostgreSQL does not allow transition tables on a single trigger with multiple
-- events (0A000). UPDATE cannot use UPDATE OF (column list) with transition
-- tables (0A000), so this fires on any column change; the TICKER_RELATIONSHIPS
-- guard limits work to relevant rows only.
--
-- Note: each run re-scans matching head history (p_lookback NULL). High-volume
-- writers may prefer a job queue + scheduled refresh instead.
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION swingtrader.exec_ticker_relationship_heads_refresh()
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = swingtrader, pg_temp
AS $$
BEGIN
  PERFORM swingtrader.refresh_ticker_relationship_edges(NULL);
  PERFORM swingtrader.refresh_ticker_relationship_edge_evidence(NULL);
END;
$$;

REVOKE ALL ON FUNCTION swingtrader.exec_ticker_relationship_heads_refresh() FROM PUBLIC;

CREATE OR REPLACE FUNCTION swingtrader.trg_stmt_nih_rel_graph_ins()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = swingtrader, pg_temp
AS $$
BEGIN
  IF EXISTS (SELECT 1 FROM new_rows nr WHERE nr.cluster = 'TICKER_RELATIONSHIPS') THEN
    PERFORM swingtrader.exec_ticker_relationship_heads_refresh();
  END IF;
  RETURN NULL;
END;
$$;

REVOKE ALL ON FUNCTION swingtrader.trg_stmt_nih_rel_graph_ins() FROM PUBLIC;

CREATE OR REPLACE FUNCTION swingtrader.trg_stmt_nih_rel_graph_upd()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = swingtrader, pg_temp
AS $$
BEGIN
  IF EXISTS (SELECT 1 FROM new_rows nr WHERE nr.cluster = 'TICKER_RELATIONSHIPS')
     OR EXISTS (SELECT 1 FROM old_rows oro WHERE oro.cluster = 'TICKER_RELATIONSHIPS') THEN
    PERFORM swingtrader.exec_ticker_relationship_heads_refresh();
  END IF;
  RETURN NULL;
END;
$$;

REVOKE ALL ON FUNCTION swingtrader.trg_stmt_nih_rel_graph_upd() FROM PUBLIC;

CREATE OR REPLACE FUNCTION swingtrader.trg_stmt_nih_rel_graph_del()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = swingtrader, pg_temp
AS $$
BEGIN
  IF EXISTS (SELECT 1 FROM old_rows oro WHERE oro.cluster = 'TICKER_RELATIONSHIPS') THEN
    PERFORM swingtrader.exec_ticker_relationship_heads_refresh();
  END IF;
  RETURN NULL;
END;
$$;

REVOKE ALL ON FUNCTION swingtrader.trg_stmt_nih_rel_graph_del() FROM PUBLIC;

DROP TRIGGER IF EXISTS trg_news_impact_heads_refresh_relationship_graph_ins ON swingtrader.news_impact_heads;
DROP TRIGGER IF EXISTS trg_news_impact_heads_refresh_relationship_graph_upd ON swingtrader.news_impact_heads;
DROP TRIGGER IF EXISTS trg_news_impact_heads_refresh_relationship_graph_del ON swingtrader.news_impact_heads;

CREATE TRIGGER trg_news_impact_heads_refresh_relationship_graph_ins
AFTER INSERT ON swingtrader.news_impact_heads
REFERENCING NEW TABLE AS new_rows
FOR EACH STATEMENT
EXECUTE FUNCTION swingtrader.trg_stmt_nih_rel_graph_ins();

CREATE TRIGGER trg_news_impact_heads_refresh_relationship_graph_upd
AFTER UPDATE ON swingtrader.news_impact_heads
REFERENCING NEW TABLE AS new_rows OLD TABLE AS old_rows
FOR EACH STATEMENT
EXECUTE FUNCTION swingtrader.trg_stmt_nih_rel_graph_upd();

CREATE TRIGGER trg_news_impact_heads_refresh_relationship_graph_del
AFTER DELETE ON swingtrader.news_impact_heads
REFERENCING OLD TABLE AS old_rows
FOR EACH STATEMENT
EXECUTE FUNCTION swingtrader.trg_stmt_nih_rel_graph_del();

DROP FUNCTION IF EXISTS swingtrader.trg_stmt_news_impact_heads_refresh_relationship_graph();
