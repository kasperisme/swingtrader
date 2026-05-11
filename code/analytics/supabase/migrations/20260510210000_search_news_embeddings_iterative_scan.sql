-- Fix statement timeouts on swingtrader.search_news_embeddings.
--
-- Problem: HNSW does the index scan FIRST, then applies WHERE filters.
-- With the default hnsw.ef_search and a published_at filter, the planner
-- pushes the filter into the index scan and stalls trying to find enough
-- rows that pass the filter — eventually hitting Supabase's statement
-- timeout.
--
-- Fix (per pgvector docs, "Filtering with HNSW"): use a MATERIALIZED CTE
-- so the planner CANNOT push the WHERE clause into the index scan. The
-- inner CTE does an unfiltered HNSW lookup (fast, ~10-50ms); the outer
-- SELECT applies published_at / stream / ticker filters against the
-- materialized candidate pool.
--
-- Both hnsw.iterative_scan and hnsw.ef_search are locked down on Supabase
-- (cannot be set in function clauses), so we rely on the materialized
-- pattern alone. With the default ef_search the candidate pool is ~40
-- rows, which is sufficient for typical news queries where the top
-- semantically-similar results are mostly recent.

CREATE OR REPLACE FUNCTION swingtrader.search_news_embeddings(
  query_embedding float8[],
  match_count integer DEFAULT 20,
  lookback_hours integer DEFAULT 24,
  stream_filter text DEFAULT NULL,
  ticker_filter text[] DEFAULT NULL
)
RETURNS TABLE (
  article_id bigint,
  title text,
  url text,
  source text,
  slug text,
  image_url text,
  article_stream text,
  published_at timestamptz,
  snippet text,
  similarity double precision
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = swingtrader, public, extensions
AS $$
  WITH q AS (
    SELECT query_embedding::vector(1024) AS emb
  ),
  -- MATERIALIZED forces the planner to run this as-is; without it the
  -- outer WHERE clauses get pushed into the HNSW scan and we hit the
  -- filtered-HNSW pathology.
  raw_candidates AS MATERIALIZED (
    SELECT
      e.article_id,
      e.chunk_text,
      e.published_at,
      1 - (e.embedding <=> q.emb) AS similarity
    FROM q, swingtrader.news_article_embeddings e
    ORDER BY e.embedding <=> q.emb
    LIMIT 40
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
  WHERE c.published_at >= NOW() - make_interval(hours => GREATEST(1, lookback_hours))
    AND (stream_filter IS NULL OR na.article_stream = stream_filter)
    AND (
      ticker_filter IS NULL OR EXISTS (
        SELECT 1
        FROM swingtrader.news_article_tickers nat
        WHERE nat.article_id = na.id
          AND upper(nat.ticker) = ANY(
            SELECT upper(t) FROM unnest(ticker_filter) AS t
          )
      )
    )
  ORDER BY c.similarity DESC
  LIMIT GREATEST(1, match_count)
$$;

GRANT EXECUTE ON FUNCTION swingtrader.search_news_embeddings(float8[], integer, integer, text, text[])
  TO anon, authenticated, service_role;
