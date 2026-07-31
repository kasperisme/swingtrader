-- ---------------------------------------------------------------------------
-- Fix the two post-ingest refresh RPCs score_cli calls at the end of every run.
--
-- Both failed for reasons that come from the role PostgREST logs in as
-- (`authenticator`), not from the SQL itself:
--
--   rolconfig: session_preload_libraries=safeupdate, statement_timeout=8s, lock_timeout=8s
--
-- 1. exec_ticker_sentiment_heads_refresh()
--      -> 21000 "DELETE requires a WHERE clause"
--    `safeupdate` is preloaded into every REST session and rejects unqualified
--    DELETEs. The full-rebuild branch does exactly that. A trivially-true WHERE
--    satisfies the guard without changing semantics.
--
-- 2. exec_ticker_relationship_heads_refresh()
--      -> 57014 "canceling statement due to statement timeout"
--    The full-history rebuild is ~33s over 177k TICKER_RELATIONSHIPS heads
--    (9.8s edges + 23.1s evidence) against an 8s role timeout. It cannot be
--    bounded by a lookback: the edge rows carry LIFETIME aggregates
--    (mention_count, first_seen_at, AVG strength), so refreshing a window would
--    overwrite them with window-only values. The rebuild has to stay whole —
--    what changes is the budget it gets.
--
-- A SET clause on a function overrides role/session GUCs for that function's
-- duration, so raising the budget here does NOT relax the 8s default protecting
-- ordinary API traffic. Only these two batch RPCs (service_role only) get it.
-- ---------------------------------------------------------------------------

-- --- 1. safeupdate-compatible full delete -----------------------------------
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
    -- WHERE TRUE is required, not cosmetic: `safeupdate` is preloaded into REST
    -- sessions and raises 21000 on an unqualified DELETE.
    DELETE FROM swingtrader.ticker_sentiment_heads WHERE TRUE;
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

-- --- 2. batch-sized budget on the two exec wrappers -------------------------
-- Headroom over the measured ~33s (relationship) / ~20s (sentiment) so the RPCs
-- keep working as head volume grows, while staying under the REST gateway's own
-- request ceiling. lock_timeout is raised alongside because both wrappers
-- delete-and-reinsert whole tables that concurrent readers may hold locks on.
-- One SET per statement — ALTER FUNCTION takes a single configuration item.
ALTER FUNCTION swingtrader.exec_ticker_relationship_heads_refresh()
  SET statement_timeout = '300s';
ALTER FUNCTION swingtrader.exec_ticker_relationship_heads_refresh()
  SET lock_timeout = '30s';

ALTER FUNCTION swingtrader.exec_ticker_sentiment_heads_refresh()
  SET statement_timeout = '300s';
ALTER FUNCTION swingtrader.exec_ticker_sentiment_heads_refresh()
  SET lock_timeout = '30s';

-- The inner functions are also called directly (cron / psql), where the caller
-- supplies its own budget; only tighten what the REST path needs.
REVOKE ALL ON FUNCTION swingtrader.refresh_ticker_sentiment_heads(INTERVAL) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION swingtrader.refresh_ticker_sentiment_heads(INTERVAL) TO service_role;
