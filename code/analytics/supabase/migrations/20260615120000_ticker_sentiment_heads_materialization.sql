-- ---------------------------------------------------------------------------
-- Ticker Sentiment Materialization (pre-exploded, indexed)
--
-- Why:
-- - swingtrader.ticker_sentiment_heads_v explodes EVERY TICKER_SENTIMENT head's
--   scores_json (text->jsonb cast + jsonb_each_text) and joins news_articles on
--   every request. The `ticker` column is derived from JSON keys and `article_ts`
--   from a join, so neither a `ticker IN (...)` nor a date filter can be pushed
--   down or indexed — the view is O(all sentiment heads) per call and was taking
--   4–8s for a single ticker (and growing with ingestion).
-- - This pre-explodes the same data into a real table keyed by (head_id, ticker)
--   with an index on (ticker, article_ts) so the hot lookup is an index range
--   scan (single-digit ms).
--
-- Refresh model mirrors ticker_relationship_edges: NOT refreshed synchronously
-- on every head write (that caused statement timeouts during score_cli batches —
-- see 20260526120000_defer_relationship_graph_refresh). Batch writers call
-- exec_ticker_sentiment_heads_refresh() once per run; schedule via cron for
-- other writers if needed.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS swingtrader.ticker_sentiment_heads (
  head_id         BIGINT           NOT NULL,
  article_id      BIGINT           NOT NULL,
  ticker          TEXT             NOT NULL,
  sentiment_score DOUBLE PRECISION NOT NULL,
  reasoning_text  TEXT,
  confidence      DOUBLE PRECISION,
  model           TEXT,
  latency_ms      INTEGER,
  scored_at       TIMESTAMPTZ,
  article_ts      TIMESTAMPTZ,
  updated_at      TIMESTAMPTZ      NOT NULL DEFAULT NOW(),
  CONSTRAINT ticker_sentiment_heads_pk PRIMARY KEY (head_id, ticker)
);

-- Hot path: `WHERE ticker IN (...) AND article_ts >= <cutoff>`.
CREATE INDEX IF NOT EXISTS idx_ticker_sentiment_heads_ticker_ts
  ON swingtrader.ticker_sentiment_heads (ticker, article_ts DESC);

CREATE INDEX IF NOT EXISTS idx_ticker_sentiment_heads_article
  ON swingtrader.ticker_sentiment_heads (article_id);

-- Speeds the refresh's source scan (one cluster out of several).
CREATE INDEX IF NOT EXISTS idx_news_impact_heads_ticker_sentiment
  ON swingtrader.news_impact_heads (id)
  WHERE cluster = 'TICKER_SENTIMENT';

-- ---------------------------------------------------------------------------
-- Refresh: re-explode TICKER_SENTIMENT heads into the table.
--   p_lookback NULL  -> full rebuild (delete all, reinsert)
--   p_lookback set   -> only heads whose article_ts is within the window
--
-- SECURITY DEFINER so the delete/insert run as the table owner regardless of the
-- caller (service_role / cron). Delete-then-insert (rather than pure upsert) so a
-- re-scored head whose ticker set shrank never leaves stale (head_id, ticker)
-- rows behind.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION swingtrader.refresh_ticker_sentiment_heads(
  p_lookback INTERVAL DEFAULT NULL
)
RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = swingtrader, pg_temp
AS $$
DECLARE
  v_count INTEGER := 0;
BEGIN
  IF p_lookback IS NULL THEN
    DELETE FROM swingtrader.ticker_sentiment_heads;
  ELSE
    DELETE FROM swingtrader.ticker_sentiment_heads t
    USING swingtrader.news_impact_heads h
    LEFT JOIN swingtrader.news_articles a ON a.id = h.article_id
    WHERE t.head_id = h.id
      AND h.cluster = 'TICKER_SENTIMENT'
      AND COALESCE(a.published_at, a.created_at, h.created_at) >= NOW() - p_lookback;
  END IF;

  WITH parsed AS (
    SELECT
      h.id AS head_id,
      h.article_id,
      UPPER(BTRIM(kv.key)) AS ticker,
      CASE
        WHEN kv.value ~ '^-?[0-9]+(\.[0-9]+)?$'
          THEN LEAST(1.0, GREATEST(-1.0, kv.value::DOUBLE PRECISION))
        ELSE NULL
      END AS sentiment_score,
      CASE
        WHEN jsonb_typeof(h.reasoning_json::jsonb) = 'object'
          THEN NULLIF(BTRIM(h.reasoning_json::jsonb ->> kv.key), '')
        ELSE NULL
      END AS reasoning_text,
      h.confidence,
      h.model,
      h.latency_ms,
      h.created_at AS scored_at,
      COALESCE(a.published_at, a.created_at, h.created_at) AS article_ts
    FROM swingtrader.news_impact_heads h
    LEFT JOIN swingtrader.news_articles a
      ON a.id = h.article_id
    CROSS JOIN LATERAL jsonb_each_text(
      CASE
        WHEN jsonb_typeof(h.scores_json::jsonb) = 'object'
          THEN h.scores_json::jsonb
        ELSE '{}'::jsonb
      END
    ) AS kv(key, value)
    WHERE h.cluster = 'TICKER_SENTIMENT'
      AND (
        p_lookback IS NULL
        OR COALESCE(a.published_at, a.created_at, h.created_at) >= NOW() - p_lookback
      )
  ),
  inserted AS (
    INSERT INTO swingtrader.ticker_sentiment_heads (
      head_id, article_id, ticker, sentiment_score, reasoning_text,
      confidence, model, latency_ms, scored_at, article_ts
    )
    SELECT
      head_id, article_id, ticker, sentiment_score, reasoning_text,
      confidence, model, latency_ms, scored_at, article_ts
    FROM parsed
    WHERE ticker <> ''
      AND sentiment_score IS NOT NULL
    ON CONFLICT (head_id, ticker) DO UPDATE SET
      article_id      = EXCLUDED.article_id,
      sentiment_score = EXCLUDED.sentiment_score,
      reasoning_text  = EXCLUDED.reasoning_text,
      confidence      = EXCLUDED.confidence,
      model           = EXCLUDED.model,
      latency_ms      = EXCLUDED.latency_ms,
      scored_at       = EXCLUDED.scored_at,
      article_ts      = EXCLUDED.article_ts,
      updated_at      = NOW()
    RETURNING 1
  )
  SELECT COUNT(*) INTO v_count FROM inserted;

  RETURN v_count;
END;
$$;

-- Void wrapper for no-arg RPC calls (matches exec_ticker_relationship_heads_refresh).
CREATE OR REPLACE FUNCTION swingtrader.exec_ticker_sentiment_heads_refresh()
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = swingtrader, pg_temp
AS $$
BEGIN
  PERFORM swingtrader.refresh_ticker_sentiment_heads(NULL);
END;
$$;

REVOKE ALL ON FUNCTION swingtrader.refresh_ticker_sentiment_heads(INTERVAL) FROM PUBLIC;
REVOKE ALL ON FUNCTION swingtrader.exec_ticker_sentiment_heads_refresh() FROM PUBLIC;

-- Initial backfill over full available history.
SELECT swingtrader.refresh_ticker_sentiment_heads(NULL);

GRANT SELECT ON swingtrader.ticker_sentiment_heads TO anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION swingtrader.refresh_ticker_sentiment_heads(INTERVAL) TO service_role;
GRANT EXECUTE ON FUNCTION swingtrader.exec_ticker_sentiment_heads_refresh() TO service_role;

-- RLS: this project ships with row level security ENABLED by default on new
-- tables, and the REST API (supabase-js) reads as the `authenticated` role —
-- which gets ZERO rows until a permissive policy exists. Sibling tables
-- (ticker_relationship_edges, security_identity_map) carry the same
-- "Authenticated access to schemas" SELECT policy; mirror it so logged-in users
-- can read the materialization. (service_role bypasses RLS; reads stay gated to
-- authenticated, matching the siblings.)
ALTER TABLE swingtrader.ticker_sentiment_heads ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Authenticated access to schemas" ON swingtrader.ticker_sentiment_heads;
CREATE POLICY "Authenticated access to schemas"
  ON swingtrader.ticker_sentiment_heads
  FOR SELECT
  TO authenticated
  USING (true);
