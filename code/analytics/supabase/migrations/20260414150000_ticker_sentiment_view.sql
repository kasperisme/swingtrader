-- ---------------------------------------------------------------------------
-- Ticker Sentiment View (article-level, parsed from TICKER_SENTIMENT heads)
--
-- Why:
-- - Expose sentiment by (article, ticker) without JSON parsing in application code.
-- - Keep traceability to source head metadata and article publication timestamps.
-- ---------------------------------------------------------------------------

CREATE OR REPLACE VIEW swingtrader.ticker_sentiment_heads_v AS
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
    h.created_at AS scored_at
  FROM swingtrader.news_impact_heads h
  CROSS JOIN LATERAL jsonb_each_text(
    CASE
      WHEN jsonb_typeof(h.scores_json::jsonb) = 'object'
        THEN h.scores_json::jsonb
      ELSE '{}'::jsonb
    END
  ) AS kv(key, value)
  WHERE h.cluster = 'TICKER_SENTIMENT'
)
SELECT
  p.head_id,
  p.article_id,
  p.ticker,
  p.sentiment_score,
  p.reasoning_text,
  p.confidence,
  p.model,
  p.latency_ms,
  p.scored_at,
  COALESCE(a.published_at, a.created_at) AS article_ts,
  a.published_at,
  a.source AS article_source,
  a.publisher AS article_publisher,
  a.title AS article_title,
  a.url AS article_url
FROM parsed p
LEFT JOIN swingtrader.news_articles a
  ON a.id = p.article_id
WHERE p.ticker <> ''
  AND p.sentiment_score IS NOT NULL;

GRANT SELECT ON swingtrader.ticker_sentiment_heads_v TO anon, authenticated, service_role;
