-- Embedding search optimization for ~440K rows, 1024-dim vectors.
--   1. Denormalize published_at into embeddings table (avoids JOIN during vector scan)
--   2. Switch IVFFlat (lists=100) → HNSW (m=16, ef_construction=64)
--   3. Create SQL search function for UI RPC (oversample + post-filter pattern)
--
-- Expected runtime: ~15-30 min (dominated by HNSW index build).

-- Override Supabase statement timeout for long-running operations
SET statement_timeout = '60min';
SET maintenance_work_mem = '2GB';

-- ── Step 1: Add published_at column ────────────────────────────────────────────

ALTER TABLE swingtrader.news_article_embeddings
  ADD COLUMN IF NOT EXISTS published_at timestamptz;

-- Backfill in batches of 50K to avoid long-running single UPDATE
DO $$
DECLARE
  updated int;
BEGIN
  LOOP
    UPDATE swingtrader.news_article_embeddings e
    SET published_at = COALESCE(a.published_at, a.created_at)
    FROM swingtrader.news_articles a
    WHERE a.id = e.article_id
      AND e.published_at IS NULL
      AND e.id IN (
        SELECT e2.id FROM swingtrader.news_article_embeddings e2
        WHERE e2.published_at IS NULL
        ORDER BY e2.id LIMIT 50000
      );
    GET DIAGNOSTICS updated = ROW_COUNT;
    RAISE NOTICE 'Backfilled % rows', updated;
    EXIT WHEN updated = 0;
  END LOOP;
END;
$$;

-- Btree for time-bounded pre-filtering
CREATE INDEX IF NOT EXISTS idx_news_article_embeddings_published
  ON swingtrader.news_article_embeddings (published_at DESC)
  WHERE published_at IS NOT NULL;

-- ── Step 2: Replace IVFFlat with HNSW ─────────────────────────────────────────
-- IVFFlat lists=100 was sized for ~10K rows. HNSW is O(log n) at any scale.
-- ef_construction=64 (pgvector default) for reasonable build time;
-- query-time recall is controlled by hnsw.ef_search (set per-function to 100).

DROP INDEX IF EXISTS swingtrader.idx_news_article_embeddings_vec_cos;

CREATE INDEX idx_news_article_embeddings_vec_hnsw
  ON swingtrader.news_article_embeddings
  USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 64);

-- ── Step 3: SQL search function for UI RPC ────────────────────────────────────
-- Callable via: supabase.rpc('search_news_embeddings', { query_embedding, ... })
-- Oversample 4× then post-filter by stream/tickers.

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
  candidates AS (
    SELECT
      e.article_id,
      e.chunk_text,
      1 - (e.embedding <=> q.emb) AS similarity
    FROM q, swingtrader.news_article_embeddings e
    WHERE e.published_at >= NOW() - make_interval(hours => GREATEST(1, lookback_hours))
    ORDER BY e.embedding <=> q.emb
    LIMIT GREATEST(1, match_count) * 4
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
  FROM candidates c
  JOIN swingtrader.news_articles na ON na.id = c.article_id
  WHERE (stream_filter IS NULL OR na.article_stream = stream_filter)
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
