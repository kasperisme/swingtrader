-- ---------------------------------------------------------------------------
-- news_trends_ticker_daily_v: read the materialized heads, and give
-- ticker_coverage_daily the last column the trends board needs
--
-- Symptom: PostgREST logging SQLSTATE 57014 ("canceling statement due to
-- statement timeout") in a loop, on
--
--   SELECT ... FROM swingtrader.news_trends_ticker_daily_v
--   WHERE bucket_day >= $1 ORDER BY bucket_day, ticker LIMIT $2 OFFSET $3
--
-- That is lib/trends.ts `buildTickerIndex`, which pages the view with
-- `.range()`. It backs `getTrendingLookup`, which runs on EVERY article page —
-- so the failure is continuous, not occasional. Measured at offset 0: 8,250ms
-- against the REST role's 8s statement_timeout. It was not intermittent; it sat
-- just over the edge on the first page.
--
-- Where the time went, measured separately:
--
--   mentions CTE (news_article_tickers JOIN news_articles)   1.11s
--   sentiment CTE via ticker_sentiment_heads_v (a VIEW)      5.00s
--   the same aggregate via ticker_sentiment_heads (a TABLE)  1.69s
--
-- The sentiment half was 60% of the cost, and it was reading the exploding view
-- when the whole point of 20260615120000_ticker_sentiment_heads_materialization
-- was to replace that view with a pre-exploded, indexed table. This view simply
-- never got moved over.
--
-- Verified equivalent before swapping, not assumed: the full 120-day aggregate
-- (bucket_day, ticker, scored_count, avg_sentiment, weighted_sentiment) was
-- computed from both sources and diffed both ways — 48,525 rows each, zero rows
-- only in the view, zero only in the table. No dependent views exist, and the
-- output column list and types are unchanged, so CREATE OR REPLACE is safe.
--
-- Change 2 is the one that actually fixes the hot path. ticker_coverage_daily
-- already materializes this view (that is what refresh_ticker_coverage_daily
-- does) and is ~70ms to read, but it was missing `weighted_sentiment`, which is
-- the one column the trends board needs and the reason lib/trends.ts was still
-- reading the live view at all. Adding it lets that caller move to the table —
-- the same trade refresh_ticker_coverage_daily's own comment already argues for.
-- ---------------------------------------------------------------------------

-- 1. The view stops exploding ticker_sentiment_heads_v on every read. -------

CREATE OR REPLACE VIEW swingtrader.news_trends_ticker_daily_v AS
WITH mentions AS (
    SELECT date_trunc('day'::text, COALESCE(a.published_at, a.created_at))::date AS bucket_day,
           nat.ticker,
           count(DISTINCT nat.article_id) AS mention_count
      FROM swingtrader.news_article_tickers nat
      JOIN swingtrader.news_articles a ON a.id = nat.article_id
     WHERE COALESCE(a.published_at, a.created_at) >= (now() - '120 days'::interval)
     GROUP BY (date_trunc('day'::text, COALESCE(a.published_at, a.created_at))::date), nat.ticker
), sentiment AS (
    SELECT date_trunc('day'::text, s.article_ts)::date AS bucket_day,
           s.ticker,
           count(*) AS scored_count,
           avg(s.sentiment_score) AS avg_sentiment,
           COALESCE(
             sum(s.sentiment_score * GREATEST(COALESCE(s.confidence, 1::double precision), 0::double precision))
               / NULLIF(sum(GREATEST(COALESCE(s.confidence, 1::double precision), 0::double precision)), 0::double precision),
             avg(s.sentiment_score)
           ) AS weighted_sentiment
      -- Was ticker_sentiment_heads_v. Same rows, ~3.3s cheaper.
      FROM swingtrader.ticker_sentiment_heads s
     WHERE s.article_ts >= (now() - '120 days'::interval)
     GROUP BY (date_trunc('day'::text, s.article_ts)::date), s.ticker
)
SELECT m.bucket_day,
       m.ticker,
       m.mention_count,
       COALESCE(sn.scored_count, 0::bigint) AS scored_count,
       sn.avg_sentiment,
       sn.weighted_sentiment
  FROM mentions m
  LEFT JOIN sentiment sn ON sn.bucket_day = m.bucket_day AND sn.ticker = m.ticker::text;

-- 2. The rollup carries weighted_sentiment, so callers can leave the view. ---

ALTER TABLE swingtrader.ticker_coverage_daily
    ADD COLUMN IF NOT EXISTS weighted_sentiment DOUBLE PRECISION;

COMMENT ON COLUMN swingtrader.ticker_coverage_daily.weighted_sentiment IS
    'Confidence-weighted mean sentiment for the ticker-day, carried through from '
    'news_trends_ticker_daily_v so the trends board can read this rollup instead '
    'of recomputing the view on every article page render.';

CREATE OR REPLACE FUNCTION swingtrader.refresh_ticker_coverage_daily()
RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'swingtrader', 'pg_temp'
AS $$
DECLARE
  v_count INTEGER := 0;
BEGIN
  DELETE FROM swingtrader.ticker_coverage_daily WHERE TRUE;  -- safeupdate needs a WHERE

  INSERT INTO swingtrader.ticker_coverage_daily
    (bucket_day, ticker, mention_count, scored_count, avg_sentiment, weighted_sentiment)
  SELECT
    d.bucket_day,
    d.ticker::text,
    d.mention_count,
    d.scored_count,
    d.avg_sentiment,
    d.weighted_sentiment
  FROM swingtrader.news_trends_ticker_daily_v d
  -- Same shape gate the sitemap applies, so the hub lists exactly the symbols
  -- that get indexed. Drops numeric/foreign codes ('000063.SZ').
  WHERE d.ticker ~ '^[A-Z][A-Z0-9.\-]{0,11}$';

  GET DIAGNOSTICS v_count = ROW_COUNT;
  RETURN v_count;
END;
$$;
