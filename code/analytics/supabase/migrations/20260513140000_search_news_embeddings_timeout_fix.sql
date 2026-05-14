-- ---------------------------------------------------------------------------
-- search_news_embeddings: timeout fix.
--
-- Symptom: function hits Supabase's statement_timeout (57014) when called
-- with a wide ticker_filter (~68 tickers) plus the lookback window.
--
-- Root cause analysis:
--   1. The EXISTS subquery wrapped both `nat.ticker` and the unnest output
--      in upper(...) — preventing any regular btree on `(ticker)` or
--      `(article_id, ticker)` from being used, so each of the 40 candidate
--      rows triggered a sequential scan over news_article_tickers.
--   2. The function inherited the role's statement_timeout (no SET LOCAL),
--      so a marginal query couldn't recover from cold caches.
--
-- Fixes in this migration:
--   - SET LOCAL statement_timeout = '60s' on the function so cold-cache
--     runs don't get killed by the role default. Still bounded; just gives
--     the planner room to finish.
--   - Pre-uppercase the ticker_filter once via WITH so the inner join can
--     use the existing index on news_article_tickers(ticker) (which is
--     already stored uppercase from the ingestion pipeline).
--   - Convert EXISTS → semi-join via INNER JOIN with DISTINCT on candidate
--     ids, which lets the planner pick a hash/merge strategy instead of a
--     per-row nested loop.
--   - Materialize the candidate pool list once and feed it to the join.
-- ---------------------------------------------------------------------------

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
SET statement_timeout = '60s'
AS $$
  WITH
    q AS (
      SELECT (query_embedding)::vector(1024) AS emb
    ),
    -- MATERIALIZED prevents the planner from pushing outer filters into
    -- the HNSW index scan (pgvector "Filtering with HNSW" guidance).
    raw_candidates AS MATERIALIZED (
      SELECT
        e.article_id,
        e.chunk_text,
        e.published_at,
        1 - (e.embedding <=> q.emb) AS similarity
      FROM q, swingtrader.news_article_embeddings e
      ORDER BY e.embedding <=> q.emb
      LIMIT 40
    ),
    -- Pre-compute the uppercased ticker filter once so we can do a direct
    -- equality join against the existing index on news_article_tickers.
    tf AS (
      SELECT array_agg(DISTINCT upper(t)) AS tickers
      FROM unnest(COALESCE(ticker_filter, ARRAY[]::text[])) AS t
      WHERE t IS NOT NULL AND length(t) > 0
    ),
    -- For ticker-filtered queries: collect the candidate ids that have at
    -- least one matching ticker. Done as a hash semi-join, not per-row
    -- EXISTS subqueries.
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
  WHERE c.published_at >= NOW() - make_interval(hours => GREATEST(1, lookback_hours))
    AND (stream_filter IS NULL OR na.article_stream = stream_filter)
    AND (
      ticker_filter IS NULL
      OR cardinality(COALESCE(ticker_filter, ARRAY[]::text[])) = 0
      OR c.article_id IN (SELECT cipt.aid FROM candidate_ids_passing_ticker cipt)
    )
  ORDER BY c.similarity DESC
  LIMIT GREATEST(1, match_count)
$$;

GRANT EXECUTE ON FUNCTION swingtrader.search_news_embeddings(float8[], integer, integer, text, text[])
  TO anon, authenticated, service_role;

-- Belt-and-suspenders: ensure the index the join relies on exists. The
-- ticker column is already stored uppercase by the ingestion pipeline so
-- a plain btree is sufficient.
CREATE INDEX IF NOT EXISTS idx_news_article_tickers_ticker_article
  ON swingtrader.news_article_tickers (ticker, article_id);
