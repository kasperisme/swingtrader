-- ---------------------------------------------------------------------------
-- search_news_embeddings: an as-of bound, and a plan that survives the cache
--
-- Two changes, because either alone leaves the function unusable in a replay:
--
-- 1. NEW PARAMETER `as_of timestamptz DEFAULT NULL`. The window was anchored at
--    NOW() server-side with no way to move it, so a Jul-Sep backtest calling
--    this got September headlines. With `as_of` set, the window is
--    [as_of - lookback_hours, as_of]. NULL keeps the old behaviour exactly, so
--    every existing caller is unaffected.
--
-- 2. LANGUAGE plpgsql + dynamic SQL, to fix the plan. The old function was
--    LANGUAGE sql + SECURITY DEFINER, so PostgreSQL could not inline it and
--    planned the body with `lookback_hours` as a parameter. After five calls
--    the plan cache switched to a GENERIC plan, which cannot estimate
--    `published_at >= NOW() - make_interval(hours => $3)`, assumed a large
--    fraction of 1.85M rows qualified, and chose the 17GB ivfflat index over
--    the btree. Measured on the live database, same query, same data:
--
--      force_custom_plan   idx_news_article_embeddings_published      695 ms
--      force_generic_plan  idx_news_article_embeddings_vec_cos     137 s (timeout)
--
--    `ALTER FUNCTION ... SET plan_cache_mode` (migration 20260904180000) did
--    NOT fix it: the setting is present in proconfig and the function still
--    took 40s. Setting the same GUC at SESSION level made the identical body
--    run in 73-829 ms, so the value was not reaching the plan the SQL function
--    body actually used.
--
--    The reliable fix is to stop relying on the planner guessing a selectivity
--    it cannot see. The window bounds are computed in plpgsql and interpolated
--    as LITERALS via format(%L), so the planner reads them off the published_at
--    histogram and estimates correctly. The SQL text differs per call, so there
--    is no cached plan to go generic — which is the point. Parse+plan is ~1-3ms
--    against an alternative measured in tens of seconds.
--
--    The embedding stays a USING parameter ($1): it does not affect selectivity,
--    pgvector index scans accept a Param operand, and interpolating a 1024-dim
--    vector would add ~15KB of SQL text per call for nothing.
--
--    ORDER BY ... LIMIT deliberately stays INSIDE the materialised CTE. Moving
--    it out would force an exact distance scan over the whole window — fine at
--    24h (2,365 vectors) but ruinous at the 365-day window the /articles page
--    can request (~1.4M). Keeping it lets the planner still choose ivfflat when
--    the window genuinely is huge, which is the one case where that is correct.
--
-- DROP + CREATE rather than CREATE OR REPLACE: a new parameter changes the
-- signature, and leaving both overloads in place would make 5-argument calls
-- ambiguous ("function is not unique"). Grants are restored below; the previous
-- ACL was {PUBLIC, postgres, anon, authenticated, service_role} = EXECUTE.
--
-- Verify:
--   -- fast, and bounded to the past:
--   SELECT max(published_at) FROM swingtrader.search_news_embeddings(
--     (SELECT embedding::double precision[] FROM swingtrader.news_article_embeddings LIMIT 1),
--     12, 168, NULL, NULL, '2026-08-15 23:59:59+00'::timestamptz);
--   -- must be <= 2026-08-15, and must return in well under a second
-- ---------------------------------------------------------------------------

DROP FUNCTION IF EXISTS swingtrader.search_news_embeddings(
  double precision[], integer, integer, text, text[]
);

CREATE FUNCTION swingtrader.search_news_embeddings(
  query_embedding double precision[],
  match_count integer DEFAULT 20,
  lookback_hours integer DEFAULT 24,
  stream_filter text DEFAULT NULL::text,
  ticker_filter text[] DEFAULT NULL::text[],
  as_of timestamp with time zone DEFAULT NULL::timestamp with time zone
)
RETURNS TABLE(
  article_id bigint, title text, url text, source text, slug text,
  image_url text, article_stream text, published_at timestamp with time zone,
  snippet text, similarity double precision
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path TO 'swingtrader', 'public', 'extensions'
SET statement_timeout TO '60s'
AS $function$
DECLARE
  win_end   timestamptz := COALESCE(as_of, NOW());
  win_start timestamptz := COALESCE(as_of, NOW())
                           - make_interval(hours => GREATEST(1, lookback_hours));
  -- Over-fetch so the stream and ticker filters below still have candidates
  -- after they cut the set down.
  cap       integer := GREATEST(40, GREATEST(1, match_count) * 4);
BEGIN
  RETURN QUERY EXECUTE format($q$
    WITH raw_candidates AS MATERIALIZED (
      SELECT
        e.article_id,
        e.chunk_text,
        e.published_at,
        1 - (e.embedding <=> $1) AS similarity
      FROM swingtrader.news_article_embeddings e
      WHERE e.published_at >= %1$L::timestamptz
        AND e.published_at <= %2$L::timestamptz
      ORDER BY e.embedding <=> $1
      LIMIT %3$s
    ),
    tf AS (
      SELECT array_agg(DISTINCT upper(t)) AS tickers
      FROM unnest(COALESCE($2, ARRAY[]::text[])) AS t
      WHERE t IS NOT NULL AND length(t) > 0
    ),
    candidate_ids_passing_ticker AS (
      SELECT DISTINCT nat.article_id AS aid
      FROM swingtrader.news_article_tickers nat, tf
      WHERE tf.tickers IS NOT NULL
        AND nat.article_id IN (SELECT rc.article_id FROM raw_candidates rc)
        AND nat.ticker = ANY(tf.tickers)
    )
    SELECT
      na.id AS article_id,
      na.title::text,
      na.url::text,
      na.source::text,
      na.slug::text,
      na.image_url::text,
      na.article_stream::text,
      COALESCE(na.published_at, na.created_at) AS published_at,
      c.chunk_text AS snippet,
      c.similarity
    FROM raw_candidates c
    JOIN swingtrader.news_articles na ON na.id = c.article_id
    WHERE ($3::text IS NULL OR na.article_stream = $3::text)
      AND (
        $2 IS NULL
        OR cardinality(COALESCE($2, ARRAY[]::text[])) = 0
        OR c.article_id IN (SELECT cipt.aid FROM candidate_ids_passing_ticker cipt)
      )
    ORDER BY c.similarity DESC
    LIMIT %4$s
  $q$, win_start, win_end, cap, GREATEST(1, match_count))
  USING query_embedding::vector(1024), ticker_filter, stream_filter;
END;
$function$;

GRANT EXECUTE ON FUNCTION swingtrader.search_news_embeddings(
  double precision[], integer, integer, text, text[], timestamp with time zone
) TO PUBLIC, anon, authenticated, service_role;
