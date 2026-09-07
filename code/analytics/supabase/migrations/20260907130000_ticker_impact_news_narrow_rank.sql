-- ---------------------------------------------------------------------------
-- get_ticker_impact_news: rank without touching the wide tables
--
-- Supersedes 20260907120000, which moved the wide COLUMNS out of the ranking
-- and did not help: Postgres reads whole heap PAGES, so selecting fewer columns
-- from news_articles still fetches the row. Measured on GOOGL, that rewrite went
-- from 70,399 buffers to 73,278 — no better.
--
-- The join itself had to go. Two facts make that possible:
--
--   1. `ticker_sentiment_heads.article_ts` IS the published timestamp. Verified
--      over every row in the window, not sampled: 317,095 rows across all
--      tickers, ZERO differing from COALESCE(published_at, created_at). So the
--      bucket boundary can be computed without news_articles.
--   2. impact_magnitude is the only other input to the ranking, and a covering
--      index on news_impact_vectors(article_id) INCLUDE (impact_magnitude)
--      turns that lookup into an index-only scan.
--
-- So the ranking now reads two indexes and no table heap, and news_articles is
-- joined once for the ~105 rows that survive instead of all 8,155.
--
-- Why this matters at all: the function is fast warm (131ms) and was 7.5 SECONDS
-- cold on GOOGL, because cold those 70k buffers are disk reads. /quote lists the
-- most-covered tickers, so the names a visitor clicks first are precisely the
-- ones with the most rows to churn.
-- ---------------------------------------------------------------------------

CREATE INDEX IF NOT EXISTS idx_news_impact_vectors_article_mag
  ON swingtrader.news_impact_vectors (article_id) INCLUDE (impact_magnitude);

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
    SELECT s.article_id,
           avg(s.sentiment_score)::double precision AS sentiment,
           -- Identical to COALESCE(a.published_at, a.created_at); see the
           -- migration header for the check that established that.
           max(s.article_ts) AS published_at
    FROM swingtrader.ticker_sentiment_heads s
    WHERE s.ticker = upper(btrim(p_ticker))
      AND s.article_ts >= now() - make_interval(days => greatest(1, least(p_days, 400)))
    GROUP BY s.article_id
  ),
  ranked AS (
    SELECT h.article_id, h.sentiment, h.published_at,
           COALESCE(v.impact_magnitude, 0)::double precision AS impact_magnitude,
           row_number() OVER (
             PARTITION BY date_trunc('week', h.published_at)
             ORDER BY COALESCE(v.impact_magnitude, 0) DESC, h.published_at DESC
           ) AS rnk
    FROM heads h
    LEFT JOIN swingtrader.news_impact_vectors v ON v.article_id = h.article_id
  ),
  winners AS (
    SELECT * FROM ranked
    WHERE rnk <= greatest(1, p_per_bucket)
    ORDER BY impact_magnitude DESC, published_at DESC
    LIMIT greatest(1, least(p_limit, 400))
  )
  SELECT w.article_id, a.title, a.url, a.source, a.slug,
         w.published_at, w.sentiment, w.impact_magnitude, v.top_dimensions
  FROM winners w
  JOIN swingtrader.news_articles a ON a.id = w.article_id
  LEFT JOIN swingtrader.news_impact_vectors v ON v.article_id = w.article_id
  ORDER BY w.impact_magnitude DESC, w.published_at DESC;
$function$;
