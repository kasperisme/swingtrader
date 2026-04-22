-- Add processing_status to news_articles to track LLM head completion.
--   complete — all heads scored without error
--   partial  — at least one head succeeded but at least one failed (e.g. timeout)
--   failed   — every head failed (e.g. API key expired / total outage)
-- NULL means the article predates this column or was loaded from cache without re-scoring.
ALTER TABLE swingtrader.news_articles
ADD COLUMN IF NOT EXISTS processing_status text CHECK (
  processing_status IN ('complete', 'partial', 'failed')
);