-- Embedding setup for semantic retrieval over scored news.
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS swingtrader.news_article_embedding_jobs (
  article_id BIGINT PRIMARY KEY REFERENCES swingtrader.news_articles(id) ON DELETE CASCADE,
  status TEXT NOT NULL DEFAULT 'pending',
  attempt_count INTEGER NOT NULL DEFAULT 0,
  last_error TEXT,
  last_attempt_at TIMESTAMPTZ,
  completed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS swingtrader.news_article_embeddings (
  id BIGSERIAL PRIMARY KEY,
  article_id BIGINT NOT NULL REFERENCES swingtrader.news_articles(id) ON DELETE CASCADE,
  chunk_index INTEGER NOT NULL,
  chunk_hash TEXT NOT NULL,
  chunk_text TEXT NOT NULL,
  embedding vector(1024) NOT NULL,
  embedding_model TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (article_id, chunk_index, embedding_model)
);

CREATE INDEX IF NOT EXISTS idx_news_article_embedding_jobs_status
  ON swingtrader.news_article_embedding_jobs (status, created_at);

CREATE INDEX IF NOT EXISTS idx_news_article_embeddings_article
  ON swingtrader.news_article_embeddings (article_id, embedding_model);

-- IVFFlat speeds cosine similarity retrieval once rows are populated.
CREATE INDEX IF NOT EXISTS idx_news_article_embeddings_vec_cos
  ON swingtrader.news_article_embeddings
  USING ivfflat (embedding vector_cosine_ops)
  WITH (lists = 100);
