-- ---------------------------------------------------------------------------
-- Ticker relationship edge traceability
--
-- Goal:
-- - Provide deterministic traceability from ticker_relationship_edges
--   back to source articles and impact-vector dimensions.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS swingtrader.ticker_relationship_edge_evidence (
  edge_id BIGINT NOT NULL REFERENCES swingtrader.ticker_relationship_edges(id) ON DELETE CASCADE,
  article_id BIGINT NOT NULL REFERENCES swingtrader.news_articles(id) ON DELETE CASCADE,
  rel_pair_key TEXT NOT NULL,
  rel_type TEXT NOT NULL,
  pair_strength DOUBLE PRECISION,
  head_confidence DOUBLE PRECISION,
  reasoning_text TEXT,
  published_at TIMESTAMPTZ,
  impact_json_snapshot JSONB,
  top_dimensions_snapshot JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (edge_id, article_id, rel_pair_key)
);

CREATE INDEX IF NOT EXISTS idx_tre_evidence_article
  ON swingtrader.ticker_relationship_edge_evidence (article_id);

CREATE INDEX IF NOT EXISTS idx_tre_evidence_edge_created
  ON swingtrader.ticker_relationship_edge_evidence (edge_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_tre_evidence_rel_type
  ON swingtrader.ticker_relationship_edge_evidence (rel_type);

CREATE OR REPLACE FUNCTION swingtrader.refresh_ticker_relationship_edge_evidence(
  p_lookback INTERVAL DEFAULT NULL
)
RETURNS INTEGER
LANGUAGE plpgsql
AS $$
DECLARE
  v_rows INTEGER := 0;
BEGIN
  WITH src AS (
    SELECT
      h.article_id,
      UPPER(BTRIM(split_part(kv.key, '__', 1))) AS from_ticker,
      UPPER(BTRIM(split_part(kv.key, '__', 2))) AS to_ticker,
      LOWER(BTRIM(split_part(kv.key, '__', 3))) AS rel_type,
      kv.key AS rel_pair_key,
      CASE
        WHEN kv.value ~ '^-?[0-9]+(\.[0-9]+)?$' THEN LEAST(1.0, GREATEST(0.0, kv.value::DOUBLE PRECISION))
        ELSE NULL
      END AS pair_strength,
      h.confidence AS head_confidence,
      (h.reasoning_json ->> kv.key) AS reasoning_text,
      COALESCE(a.published_at, a.created_at, h.created_at) AS published_at,
      v.impact_json AS impact_json_snapshot,
      v.top_dimensions AS top_dimensions_snapshot
    FROM swingtrader.news_impact_heads h
    JOIN swingtrader.news_articles a
      ON a.id = h.article_id
    LEFT JOIN swingtrader.news_impact_vectors v
      ON v.article_id = h.article_id
    CROSS JOIN LATERAL jsonb_each_text(
      CASE
        WHEN jsonb_typeof(h.scores_json) = 'object' THEN h.scores_json
        ELSE '{}'::jsonb
      END
    ) AS kv(key, value)
    WHERE h.cluster = 'TICKER_RELATIONSHIPS'
      AND array_length(string_to_array(kv.key, '__'), 1) = 3
      AND (p_lookback IS NULL OR COALESCE(a.published_at, a.created_at, h.created_at) >= NOW() - p_lookback)
  ),
  matched AS (
    SELECT
      e.id AS edge_id,
      s.article_id,
      s.rel_pair_key,
      s.rel_type,
      s.pair_strength,
      s.head_confidence,
      s.reasoning_text,
      s.published_at,
      s.impact_json_snapshot,
      s.top_dimensions_snapshot
    FROM src s
    JOIN swingtrader.ticker_relationship_edges e
      ON e.from_ticker = s.from_ticker
     AND e.to_ticker = s.to_ticker
     AND e.rel_type = s.rel_type
  ),
  upserted AS (
    INSERT INTO swingtrader.ticker_relationship_edge_evidence (
      edge_id,
      article_id,
      rel_pair_key,
      rel_type,
      pair_strength,
      head_confidence,
      reasoning_text,
      published_at,
      impact_json_snapshot,
      top_dimensions_snapshot
    )
    SELECT
      edge_id,
      article_id,
      rel_pair_key,
      rel_type,
      pair_strength,
      head_confidence,
      reasoning_text,
      published_at,
      impact_json_snapshot,
      top_dimensions_snapshot
    FROM matched
    ON CONFLICT (edge_id, article_id, rel_pair_key)
    DO UPDATE SET
      pair_strength = EXCLUDED.pair_strength,
      head_confidence = EXCLUDED.head_confidence,
      reasoning_text = EXCLUDED.reasoning_text,
      published_at = EXCLUDED.published_at,
      impact_json_snapshot = EXCLUDED.impact_json_snapshot,
      top_dimensions_snapshot = EXCLUDED.top_dimensions_snapshot
    RETURNING 1
  )
  SELECT COUNT(*) INTO v_rows FROM upserted;

  RETURN v_rows;
END;
$$;

-- Initial full backfill for traceability.
SELECT swingtrader.refresh_ticker_relationship_edge_evidence(NULL);

CREATE OR REPLACE VIEW swingtrader.ticker_relationship_edge_traceability_v AS
SELECT
  e.id AS edge_id,
  e.from_ticker,
  e.to_ticker,
  e.rel_type,
  e.strength_avg,
  e.mention_count,
  ev.article_id,
  na.title AS article_title,
  na.url AS article_url,
  ev.published_at,
  ev.pair_strength,
  ev.head_confidence,
  ev.reasoning_text,
  ev.top_dimensions_snapshot,
  ev.impact_json_snapshot
FROM swingtrader.ticker_relationship_edges e
JOIN swingtrader.ticker_relationship_edge_evidence ev
  ON ev.edge_id = e.id
LEFT JOIN swingtrader.news_articles na
  ON na.id = ev.article_id;

GRANT SELECT ON swingtrader.ticker_relationship_edge_evidence TO anon, authenticated, service_role;
GRANT SELECT ON swingtrader.ticker_relationship_edge_traceability_v TO anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION swingtrader.refresh_ticker_relationship_edge_evidence(INTERVAL) TO service_role;
