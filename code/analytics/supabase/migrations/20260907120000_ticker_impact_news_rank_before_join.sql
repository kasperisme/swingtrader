-- ---------------------------------------------------------------------------
-- get_ticker_impact_news: rank first, join second
--
-- The function returns at most ~105 rows (2 per week over a year) but was
-- building all of them the expensive way round: join every candidate article to
-- news_articles AND news_impact_vectors, carrying title/url/source/slug through
-- a sort and a window function, and only THEN keep two per week.
--
-- For a heavily-covered ticker that is 8,155 wide rows in, 105 out. Measured on
-- the live database for GOOGL:
--
--   Buffers: shared hit=70399        Execution Time: 131 ms   (warm)
--
-- 70k buffers for 105 rows. Warm that is 131ms and invisible; COLD those are
-- disk reads, and the same call took 7.5 SECONDS — which is what a visitor got
-- on the first click of the day. And because /quote lists the most-covered
-- tickers, the names people click first are exactly the ones with the most rows
-- to churn: GOOGL, AAPL and NVDA measured 0.74-7.5s cold against 0.09-0.15s for
-- a thinly-covered name.
--
-- The rewrite keeps the identical result and moves the wide join to the end:
--
--   1. `heads`  — unchanged, 22ms, already well indexed.
--   2. `narrow` — join only the columns the RANKING needs: article_id,
--      published_at, impact_magnitude. No title, no url, no slug.
--   3. rank + filter + LIMIT on that narrow set.
--   4. join news_articles for the ~105 survivors only.
--
-- Same rows, same order, same signature.
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION swingtrader.get_ticker_impact_news(
  p_ticker text,
  p_days integer DEFAULT 365,
  p_limit integer DEFAULT 150,
  p_per_bucket integer DEFAULT 2
)
RETURNS TABLE(
  article_id bigint, title text, url text, source text, slug text,
  published_at timestamp with time zone, sentiment double precision,
  impact_magnitude double precision, top_dimensions jsonb
)
LANGUAGE sql
STABLE SECURITY DEFINER
SET search_path TO 'swingtrader', 'public'
AS $function$
  WITH heads AS (
    SELECT s.article_id, avg(s.sentiment_score)::double precision AS sentiment
    FROM swingtrader.ticker_sentiment_heads s
    WHERE s.ticker = upper(btrim(p_ticker))
      AND s.article_ts >= now() - make_interval(days => greatest(1, least(p_days, 400)))
    GROUP BY s.article_id
  ),
  -- Only what the ranking reads. Keeping title/url/source/slug out of here is
  -- the entire point: they are ~570 of the 587 bytes per row and none of the
  -- rows that get discarded ever needed them.
  narrow AS (
    SELECT h.article_id,
           h.sentiment,
           COALESCE(a.published_at, a.created_at) AS published_at,
           COALESCE(v.impact_magnitude, 0)::double precision AS impact_magnitude
    FROM heads h
    JOIN swingtrader.news_articles a ON a.id = h.article_id
    LEFT JOIN swingtrader.news_impact_vectors v ON v.article_id = h.article_id
  ),
  bucketed AS (
    SELECT n.*,
           row_number() OVER (
             PARTITION BY date_trunc('week', n.published_at)
             ORDER BY n.impact_magnitude DESC, n.published_at DESC
           ) AS rnk
    FROM narrow n
  ),
  winners AS (
    SELECT * FROM bucketed
    WHERE rnk <= greatest(1, p_per_bucket)
    ORDER BY impact_magnitude DESC, published_at DESC
    LIMIT greatest(1, least(p_limit, 400))
  )
  -- The wide columns are fetched once, for the survivors only.
  SELECT w.article_id, a.title, a.url, a.source, a.slug,
         w.published_at, w.sentiment, w.impact_magnitude, v.top_dimensions
  FROM winners w
  JOIN swingtrader.news_articles a ON a.id = w.article_id
  LEFT JOIN swingtrader.news_impact_vectors v ON v.article_id = w.article_id
  ORDER BY w.impact_magnitude DESC, w.published_at DESC;
$function$;
