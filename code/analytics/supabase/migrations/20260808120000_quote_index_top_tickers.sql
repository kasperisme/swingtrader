-- ---------------------------------------------------------------------------
-- Ticker directory for the public /quote index.
--
-- /quote/[symbol] existed with no parent page, so the ~1.5k indexable quote
-- URLs had no hub linking them and no nav entry pointing at them. This RPC
-- backs that hub: the most-covered tickers over a recent window, so the index
-- ranks by real news-impact coverage rather than listing all 17k symbols the
-- scorer has ever touched.
--
-- Aggregates news_trends_ticker_daily_v (the same daily rollup the /articles
-- trend board reads) rather than ticker_sentiment_heads directly — one row per
-- ticker/day instead of one per scored head. NOTE: that view carries its own
-- 120-day horizon, so p_days is capped there; asking for more silently yields
-- the 120-day window.
--
-- avg_sentiment in the view is a per-day mean over scored_count heads, so the
-- window mean must weight by scored_count — a plain avg(avg_sentiment) would
-- let a 1-article day outweigh a 200-article one.
--
-- SECURITY DEFINER so the logged-out /quote index reads it under RLS, matching
-- get_ticker_impact_news.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION swingtrader.get_top_covered_tickers(
  p_days integer DEFAULT 30,
  p_limit integer DEFAULT 200
)
RETURNS TABLE (
  ticker text,
  mention_count bigint,
  scored_count bigint,
  avg_sentiment double precision,
  last_day date,
  company_name text,
  sector text
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = swingtrader, public
AS $$
  WITH windowed AS (
    SELECT
      d.ticker::text AS ticker,
      sum(d.mention_count) AS mention_count,
      sum(d.scored_count) AS scored_count,
      sum(d.avg_sentiment * d.scored_count)
        / NULLIF(sum(d.scored_count) FILTER (WHERE d.avg_sentiment IS NOT NULL), 0)
        AS avg_sentiment,
      max(d.bucket_day) AS last_day
    FROM swingtrader.news_trends_ticker_daily_v d
    WHERE d.bucket_day >= (current_date - greatest(1, least(p_days, 120)))
      -- Same shape gate the sitemap applies, so the hub lists exactly the
      -- symbols that get indexed and never links a page we tell crawlers to
      -- skip. Drops numeric/foreign-exchange codes ('000020', '000063.SZ').
      AND d.ticker ~ '^[A-Z][A-Z0-9.\-]{0,11}$'
    GROUP BY d.ticker
  )
  SELECT
    w.ticker,
    w.mention_count,
    w.scored_count,
    w.avg_sentiment,
    w.last_day,
    t.company_name::text,
    t.sector::text
  FROM windowed w
  LEFT JOIN swingtrader.tickers t ON t.symbol = w.ticker
  -- Require a scored head: an unscored mention has no impact data, so its quote
  -- page would be thin — exactly what /quote/[symbol] already noindexes.
  WHERE w.scored_count > 0
  ORDER BY w.scored_count DESC, w.mention_count DESC, w.ticker
  LIMIT greatest(1, least(p_limit, 1000));
$$;

GRANT EXECUTE ON FUNCTION swingtrader.get_top_covered_tickers(integer, integer)
  TO anon, authenticated, service_role;
