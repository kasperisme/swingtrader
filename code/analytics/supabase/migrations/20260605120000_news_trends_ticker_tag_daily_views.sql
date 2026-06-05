-- Daily trend aggregates for ticker mentions and theme tags.
-- Powers the "Trending now" scoreboard on /articles and the trending-tag
-- highlights on /articles/[slug]. Goal: never scan/unnest raw rows in the UI
-- path — the views pre-bucket to (day, ticker) and (day, tag).
--
-- Both views are bounded to a rolling 120-day window so the published_at /
-- ticker indexes do the work and the UI (ISR-cached) reads stay cheap.

-- Supporting index for the tag unnest scan (time-bounded WHERE).
CREATE INDEX IF NOT EXISTS idx_news_articles_published_created
  ON swingtrader.news_articles (COALESCE(published_at, created_at));

-- 1) Ticker mentions per day, with sentiment overlay.
--    mention_count  = # articles mentioning the ticker that day (all mentions)
--    scored_count   = # of those with an LLM sentiment head
--    avg_sentiment  = mean sentiment over scored mentions  ∈ [-1, 1]
--    weighted_sentiment = confidence-weighted mean sentiment
CREATE OR REPLACE VIEW swingtrader.news_trends_ticker_daily_v AS
WITH mentions AS (
  SELECT
    date_trunc('day', COALESCE(a.published_at, a.created_at))::date AS bucket_day,
    nat.ticker,
    COUNT(DISTINCT nat.article_id) AS mention_count
  FROM swingtrader.news_article_tickers nat
  JOIN swingtrader.news_articles a ON a.id = nat.article_id
  WHERE COALESCE(a.published_at, a.created_at) >= NOW() - INTERVAL '120 days'
  GROUP BY 1, 2
),
sentiment AS (
  SELECT
    date_trunc('day', s.article_ts)::date AS bucket_day,
    s.ticker,
    COUNT(*) AS scored_count,
    AVG(s.sentiment_score) AS avg_sentiment,
    COALESCE(
      SUM(s.sentiment_score * GREATEST(COALESCE(s.confidence, 1), 0))
        / NULLIF(SUM(GREATEST(COALESCE(s.confidence, 1), 0)), 0),
      AVG(s.sentiment_score)
    ) AS weighted_sentiment
  FROM swingtrader.ticker_sentiment_heads_v s
  WHERE s.article_ts >= NOW() - INTERVAL '120 days'
  GROUP BY 1, 2
)
SELECT
  m.bucket_day,
  m.ticker,
  m.mention_count,
  COALESCE(sn.scored_count, 0) AS scored_count,
  sn.avg_sentiment,
  sn.weighted_sentiment
FROM mentions m
LEFT JOIN sentiment sn
  ON sn.bucket_day = m.bucket_day AND sn.ticker = m.ticker;

-- 2) Theme-tag frequency per day.
--    search_tags holds lowercase theme/event slugs PLUS uppercase tickers in
--    one array. Tickers are covered by view (1); here we keep theme slugs only
--    via `tag = lower(tag)` (tickers are uppercase by construction).
CREATE OR REPLACE VIEW swingtrader.news_trends_tag_daily_v AS
SELECT
  date_trunc('day', COALESCE(a.published_at, a.created_at))::date AS bucket_day,
  tag,
  COUNT(*) AS article_count
FROM swingtrader.news_articles a
CROSS JOIN LATERAL unnest(a.search_tags) AS tag
WHERE COALESCE(a.published_at, a.created_at) >= NOW() - INTERVAL '120 days'
  AND a.processing_status IS DISTINCT FROM 'failed'
  AND tag = lower(tag)        -- theme slugs only (tickers are uppercase)
  AND length(tag) >= 2
GROUP BY 1, 2;

-- Make views queryable via API roles (public scoreboard reads with anon).
GRANT SELECT ON
  swingtrader.news_trends_ticker_daily_v,
  swingtrader.news_trends_tag_daily_v
TO anon, authenticated, service_role;
