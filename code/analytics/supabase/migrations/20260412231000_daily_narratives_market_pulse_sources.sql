-- Optional article citations for the market_pulse section (title + url from news_articles).
ALTER TABLE swingtrader.daily_narratives
  ADD COLUMN IF NOT EXISTS market_pulse_sources JSONB NOT NULL DEFAULT '[]'::jsonb;

COMMENT ON COLUMN swingtrader.daily_narratives.market_pulse_sources IS
  'Array of {article_id, title, url, published_at?} backing the market_pulse summary';
