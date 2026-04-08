-- Hero/thumbnail image URL from news API (e.g. FMP `image` field), not binary storage.
ALTER TABLE swingtrader.news_articles
  ADD COLUMN IF NOT EXISTS image_url TEXT;
