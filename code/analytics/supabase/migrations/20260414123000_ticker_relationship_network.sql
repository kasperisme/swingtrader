-- ---------------------------------------------------------------------------
-- Ticker Relationship Network (graph-ready adjacency structure)
--
-- Why:
-- - Avoid scanning/parsing JSONB relationship heads for every narrative run.
-- - Materialize ticker->ticker edges with indexed lookup for multi-hop traversal.
-- - Keep provenance + recency so downstream ranking can prioritize fresh edges.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS swingtrader.ticker_relationship_edges (
  id BIGSERIAL PRIMARY KEY,
  from_ticker TEXT NOT NULL,
  to_ticker TEXT NOT NULL,
  rel_type TEXT NOT NULL,
  strength_avg DOUBLE PRECISION NOT NULL CHECK (strength_avg >= 0 AND strength_avg <= 1),
  strength_max DOUBLE PRECISION NOT NULL CHECK (strength_max >= 0 AND strength_max <= 1),
  mention_count INTEGER NOT NULL DEFAULT 0 CHECK (mention_count >= 0),
  article_count INTEGER NOT NULL DEFAULT 0 CHECK (article_count >= 0),
  first_seen_at TIMESTAMPTZ,
  last_seen_at TIMESTAMPTZ,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  CONSTRAINT ticker_relationship_edges_no_self_loop CHECK (from_ticker <> to_ticker),
  CONSTRAINT ticker_relationship_edges_unique UNIQUE (from_ticker, to_ticker, rel_type)
);

CREATE INDEX IF NOT EXISTS idx_ticker_relationship_edges_from
  ON swingtrader.ticker_relationship_edges (from_ticker);

CREATE INDEX IF NOT EXISTS idx_ticker_relationship_edges_to
  ON swingtrader.ticker_relationship_edges (to_ticker);

CREATE INDEX IF NOT EXISTS idx_ticker_relationship_edges_rel_type
  ON swingtrader.ticker_relationship_edges (rel_type);

CREATE INDEX IF NOT EXISTS idx_ticker_relationship_edges_last_seen
  ON swingtrader.ticker_relationship_edges (last_seen_at DESC);

CREATE INDEX IF NOT EXISTS idx_ticker_relationship_edges_from_strength
  ON swingtrader.ticker_relationship_edges (from_ticker, strength_avg DESC);

CREATE OR REPLACE FUNCTION swingtrader.touch_ticker_relationship_edges_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_ticker_relationship_edges_updated_at ON swingtrader.ticker_relationship_edges;
CREATE TRIGGER trg_ticker_relationship_edges_updated_at
  BEFORE UPDATE ON swingtrader.ticker_relationship_edges
  FOR EACH ROW
  EXECUTE FUNCTION swingtrader.touch_ticker_relationship_edges_updated_at();

CREATE OR REPLACE FUNCTION swingtrader.refresh_ticker_relationship_edges(
  p_lookback INTERVAL DEFAULT NULL
)
RETURNS INTEGER
LANGUAGE plpgsql
AS $$
DECLARE
  v_upserted_count INTEGER := 0;
BEGIN
  WITH source_rows AS (
    SELECT
      h.article_id,
      COALESCE(a.published_at, a.created_at, h.created_at) AS edge_ts,
      kv.key AS pair_key,
      kv.value AS pair_strength
    FROM swingtrader.news_impact_heads h
    JOIN swingtrader.news_articles a
      ON a.id = h.article_id
    CROSS JOIN LATERAL jsonb_each_text(
      CASE
        WHEN jsonb_typeof(h.scores_json) = 'object' THEN h.scores_json
        ELSE '{}'::jsonb
      END
    ) AS kv(key, value)
    WHERE h.cluster = 'TICKER_RELATIONSHIPS'
      AND (p_lookback IS NULL OR COALESCE(a.published_at, a.created_at, h.created_at) >= NOW() - p_lookback)
  ),
  parsed AS (
    SELECT
      article_id,
      edge_ts,
      UPPER(BTRIM(split_part(pair_key, '__', 1))) AS from_ticker,
      UPPER(BTRIM(split_part(pair_key, '__', 2))) AS to_ticker,
      LOWER(BTRIM(split_part(pair_key, '__', 3))) AS rel_type,
      CASE
        WHEN pair_strength ~ '^-?[0-9]+(\.[0-9]+)?$' THEN LEAST(1.0, GREATEST(0.0, pair_strength::DOUBLE PRECISION))
        ELSE NULL
      END AS strength
    FROM source_rows
    WHERE array_length(string_to_array(pair_key, '__'), 1) = 3
  ),
  aggregated AS (
    SELECT
      from_ticker,
      to_ticker,
      rel_type,
      AVG(strength) AS strength_avg,
      MAX(strength) AS strength_max,
      COUNT(*) AS mention_count,
      COUNT(DISTINCT article_id) AS article_count,
      MIN(edge_ts) AS first_seen_at,
      MAX(edge_ts) AS last_seen_at
    FROM parsed
    WHERE from_ticker <> ''
      AND to_ticker <> ''
      AND rel_type <> ''
      AND from_ticker <> to_ticker
      AND strength IS NOT NULL
    GROUP BY from_ticker, to_ticker, rel_type
  ),
  upserted AS (
    INSERT INTO swingtrader.ticker_relationship_edges (
      from_ticker,
      to_ticker,
      rel_type,
      strength_avg,
      strength_max,
      mention_count,
      article_count,
      first_seen_at,
      last_seen_at,
      metadata_json
    )
    SELECT
      from_ticker,
      to_ticker,
      rel_type,
      strength_avg,
      strength_max,
      mention_count,
      article_count,
      first_seen_at,
      last_seen_at,
      jsonb_build_object('refresh_source', 'news_impact_heads')
    FROM aggregated
    ON CONFLICT (from_ticker, to_ticker, rel_type)
    DO UPDATE SET
      strength_avg = EXCLUDED.strength_avg,
      strength_max = EXCLUDED.strength_max,
      mention_count = EXCLUDED.mention_count,
      article_count = EXCLUDED.article_count,
      first_seen_at = EXCLUDED.first_seen_at,
      last_seen_at = EXCLUDED.last_seen_at,
      metadata_json = EXCLUDED.metadata_json
    RETURNING 1
  )
  SELECT COUNT(*) INTO v_upserted_count FROM upserted;

  RETURN v_upserted_count;
END;
$$;

-- Initial backfill over full available history.
SELECT swingtrader.refresh_ticker_relationship_edges(NULL);

CREATE OR REPLACE VIEW swingtrader.ticker_relationship_network_v AS
SELECT
  e.from_ticker,
  e.to_ticker,
  e.rel_type,
  e.strength_avg,
  e.strength_max,
  e.mention_count,
  e.article_count,
  e.first_seen_at,
  e.last_seen_at
FROM swingtrader.ticker_relationship_edges e;

GRANT SELECT ON swingtrader.ticker_relationship_edges TO anon, authenticated, service_role;
GRANT SELECT ON swingtrader.ticker_relationship_network_v TO anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION swingtrader.refresh_ticker_relationship_edges(INTERVAL) TO service_role;
