-- Secondary embedding table for Supabase Edge Runtime model parity (gte-small).
-- Query-time embeddings from Edge Functions should match this dimension/model.

CREATE TABLE IF NOT EXISTS swingtrader.news_article_embeddings_gte (
  id BIGSERIAL PRIMARY KEY,
  article_id BIGINT NOT NULL REFERENCES swingtrader.news_articles(id) ON DELETE CASCADE,
  chunk_index INTEGER NOT NULL,
  chunk_hash TEXT NOT NULL,
  chunk_text TEXT NOT NULL,
  embedding vector(384) NOT NULL,
  embedding_model TEXT NOT NULL DEFAULT 'gte-small',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (article_id, chunk_index, embedding_model)
);

CREATE INDEX IF NOT EXISTS idx_news_article_embeddings_gte_article
  ON swingtrader.news_article_embeddings_gte (article_id, embedding_model);

CREATE INDEX IF NOT EXISTS idx_news_article_embeddings_gte_vec_cos
  ON swingtrader.news_article_embeddings_gte
  USING ivfflat (embedding vector_cosine_ops)
  WITH (lists = 100);

CREATE OR REPLACE FUNCTION swingtrader.search_news_article_embeddings_gte(
  query_embedding float8[],
  match_count integer DEFAULT 20,
  lookback_days integer DEFAULT 30,
  stream_filter text DEFAULT NULL
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
    SELECT query_embedding::vector(384) AS emb
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
    e.chunk_text AS snippet,
    1 - (e.embedding <=> q.emb) AS similarity
  FROM q
  JOIN swingtrader.news_article_embeddings_gte e ON TRUE
  JOIN swingtrader.news_articles na ON na.id = e.article_id
  WHERE
    COALESCE(na.published_at, na.created_at) >= NOW() - make_interval(days => GREATEST(1, lookback_days))
    AND (stream_filter IS NULL OR na.article_stream = stream_filter)
  ORDER BY e.embedding <=> q.emb
  LIMIT GREATEST(1, match_count)
$$;

GRANT EXECUTE ON FUNCTION swingtrader.search_news_article_embeddings_gte(float8[], integer, integer, text)
  TO anon, authenticated, service_role;
