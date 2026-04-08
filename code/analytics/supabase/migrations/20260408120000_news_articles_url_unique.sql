-- One row per canonical article URL (dedupe by URL). Multiple NULL/empty URLs still allowed.
CREATE UNIQUE INDEX IF NOT EXISTS idx_news_articles_url_unique
  ON swingtrader.news_articles (url)
  WHERE url IS NOT NULL AND trim(url) <> '';
