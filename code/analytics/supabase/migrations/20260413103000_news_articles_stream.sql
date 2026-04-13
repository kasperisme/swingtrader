-- Track which ingestion stream produced each article row.
ALTER TABLE swingtrader.news_articles
  ADD COLUMN IF NOT EXISTS article_stream TEXT NOT NULL DEFAULT 'unknown';

COMMENT ON COLUMN swingtrader.news_articles.article_stream IS
  'Ingestion stream label: fmp_stock, fmp_general, x_post, manual_* or unknown';
