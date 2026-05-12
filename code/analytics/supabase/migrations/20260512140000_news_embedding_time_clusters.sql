-- Hourly / daily embedding clusters over swingtrader.news_article_embeddings (UTC buckets).
-- Populated by services/news/embeddings/time_bucket_clustering.py
--   (scripts/cluster_news_embedding_buckets.py).
--
-- Per bucket: run metadata, one centroid row per cluster (float8[] + nearest-chunk reverse text),
-- one article assignment row per article.

DROP TABLE IF EXISTS swingtrader.news_embedding_time_clusters;
DROP TABLE IF EXISTS swingtrader.news_embedding_time_cluster_runs;

-- ── Hourly ─────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS swingtrader.news_embedding_hourly_cluster_runs (
  bucket_start TIMESTAMPTZ NOT NULL,
  embedding_model TEXT NOT NULL,
  n_clusters INTEGER NOT NULL CHECK (n_clusters >= 1),
  article_count INTEGER NOT NULL CHECK (article_count >= 0),
  chunk_rows_used INTEGER NOT NULL CHECK (chunk_rows_used >= 0),
  embedding_dim INTEGER NOT NULL CHECK (embedding_dim >= 1),
  computed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (bucket_start, embedding_model)
);

CREATE TABLE IF NOT EXISTS swingtrader.news_embedding_hourly_cluster_centroids (
  bucket_start TIMESTAMPTZ NOT NULL,
  embedding_model TEXT NOT NULL,
  cluster_index INTEGER NOT NULL CHECK (cluster_index >= 0),
  centroid DOUBLE PRECISION[] NOT NULL,
  reverse_embedding_text TEXT NOT NULL,
  reverse_embedding_article_id BIGINT REFERENCES swingtrader.news_articles (id) ON DELETE SET NULL,
  reverse_embedding_chunk_index INTEGER,
  member_count INTEGER NOT NULL DEFAULT 0 CHECK (member_count >= 0),
  computed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (bucket_start, embedding_model, cluster_index),
  FOREIGN KEY (bucket_start, embedding_model)
    REFERENCES swingtrader.news_embedding_hourly_cluster_runs (bucket_start, embedding_model)
    ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS swingtrader.news_embedding_hourly_cluster_articles (
  bucket_start TIMESTAMPTZ NOT NULL,
  embedding_model TEXT NOT NULL,
  article_id BIGINT NOT NULL REFERENCES swingtrader.news_articles (id) ON DELETE CASCADE,
  cluster_index INTEGER NOT NULL CHECK (cluster_index >= 0),
  computed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (bucket_start, embedding_model, article_id),
  FOREIGN KEY (bucket_start, embedding_model, cluster_index)
    REFERENCES swingtrader.news_embedding_hourly_cluster_centroids (bucket_start, embedding_model, cluster_index)
    ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_news_embedding_hourly_cluster_articles_bucket
  ON swingtrader.news_embedding_hourly_cluster_articles (bucket_start DESC);

CREATE INDEX IF NOT EXISTS idx_news_embedding_hourly_cluster_articles_article
  ON swingtrader.news_embedding_hourly_cluster_articles (article_id);

-- ── Daily ───────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS swingtrader.news_embedding_daily_cluster_runs (
  bucket_start TIMESTAMPTZ NOT NULL,
  embedding_model TEXT NOT NULL,
  n_clusters INTEGER NOT NULL CHECK (n_clusters >= 1),
  article_count INTEGER NOT NULL CHECK (article_count >= 0),
  chunk_rows_used INTEGER NOT NULL CHECK (chunk_rows_used >= 0),
  embedding_dim INTEGER NOT NULL CHECK (embedding_dim >= 1),
  computed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (bucket_start, embedding_model)
);

CREATE TABLE IF NOT EXISTS swingtrader.news_embedding_daily_cluster_centroids (
  bucket_start TIMESTAMPTZ NOT NULL,
  embedding_model TEXT NOT NULL,
  cluster_index INTEGER NOT NULL CHECK (cluster_index >= 0),
  centroid DOUBLE PRECISION[] NOT NULL,
  reverse_embedding_text TEXT NOT NULL,
  reverse_embedding_article_id BIGINT REFERENCES swingtrader.news_articles (id) ON DELETE SET NULL,
  reverse_embedding_chunk_index INTEGER,
  member_count INTEGER NOT NULL DEFAULT 0 CHECK (member_count >= 0),
  computed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (bucket_start, embedding_model, cluster_index),
  FOREIGN KEY (bucket_start, embedding_model)
    REFERENCES swingtrader.news_embedding_daily_cluster_runs (bucket_start, embedding_model)
    ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS swingtrader.news_embedding_daily_cluster_articles (
  bucket_start TIMESTAMPTZ NOT NULL,
  embedding_model TEXT NOT NULL,
  article_id BIGINT NOT NULL REFERENCES swingtrader.news_articles (id) ON DELETE CASCADE,
  cluster_index INTEGER NOT NULL CHECK (cluster_index >= 0),
  computed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (bucket_start, embedding_model, article_id),
  FOREIGN KEY (bucket_start, embedding_model, cluster_index)
    REFERENCES swingtrader.news_embedding_daily_cluster_centroids (bucket_start, embedding_model, cluster_index)
    ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_news_embedding_daily_cluster_articles_bucket
  ON swingtrader.news_embedding_daily_cluster_articles (bucket_start DESC);

CREATE INDEX IF NOT EXISTS idx_news_embedding_daily_cluster_articles_article
  ON swingtrader.news_embedding_daily_cluster_articles (article_id);

COMMENT ON COLUMN swingtrader.news_embedding_hourly_cluster_centroids.reverse_embedding_text IS
  'Short theme label: Ollama reads member chunks in this cluster (same bucket); reverse_embedding_* ids point at nearest chunk to centroid within the cluster.';
COMMENT ON COLUMN swingtrader.news_embedding_daily_cluster_centroids.reverse_embedding_text IS
  'Short theme label: Ollama reads member chunks in this cluster (same bucket); reverse_embedding_* ids point at nearest chunk to centroid within the cluster.';
