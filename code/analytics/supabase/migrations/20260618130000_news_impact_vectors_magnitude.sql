-- ---------------------------------------------------------------------------
-- News impact magnitude (stored) + per-ticker impact-ranked news RPC
--
-- Why:
-- - The public /quote/[symbol] page plots scored news catalysts on the price
--   chart. Selecting "the loudest catalysts, spread across the time range"
--   means ranking a ticker's articles by impact magnitude (sum |dimension| over
--   impact_json). Computing that sum over thousands of rows per request is too
--   slow (NVDA alone has ~11k articles/yr), so we store the magnitude once and
--   maintain it with a cheap per-row trigger.
-- - get_ticker_impact_news returns an impact-ranked, time-spread pool (top-k per
--   ISO week) so markers never clump on the most-recent days — the bug where a
--   high-volume ticker showed only a couple of dots at the right edge.
-- ---------------------------------------------------------------------------

-- sum(|value|) over the numeric entries of an impact vector.
CREATE OR REPLACE FUNCTION swingtrader.impact_vector_magnitude(p_impact jsonb)
RETURNS double precision
LANGUAGE sql
IMMUTABLE
AS $$
  SELECT COALESCE(sum(abs(value::numeric)), 0)::double precision
  FROM jsonb_each_text(
    CASE WHEN jsonb_typeof(p_impact) = 'object' THEN p_impact ELSE '{}'::jsonb END
  ) AS kv(key, value)
  WHERE value ~ '^-?[0-9]+(\.[0-9]+)?$';
$$;

ALTER TABLE swingtrader.news_impact_vectors
  ADD COLUMN IF NOT EXISTS impact_magnitude double precision;

-- Maintain on write. Fires only when impact_json changes (not on the backfill,
-- which only touches impact_magnitude) so there's no recursion.
CREATE OR REPLACE FUNCTION swingtrader.trg_set_impact_magnitude()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  NEW.impact_magnitude := swingtrader.impact_vector_magnitude(NEW.impact_json);
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_news_impact_vectors_magnitude ON swingtrader.news_impact_vectors;
CREATE TRIGGER trg_news_impact_vectors_magnitude
  BEFORE INSERT OR UPDATE OF impact_json ON swingtrader.news_impact_vectors
  FOR EACH ROW
  EXECUTE FUNCTION swingtrader.trg_set_impact_magnitude();

-- One-time backfill.
UPDATE swingtrader.news_impact_vectors
SET impact_magnitude = swingtrader.impact_vector_magnitude(impact_json)
WHERE impact_magnitude IS NULL;

-- ---------------------------------------------------------------------------
-- Per-ticker impact-ranked, time-spread news for the quote page hero.
--   p_days       lookback window (capped to 400)
--   p_limit      max events returned (capped to 400)
--   p_per_bucket max events kept per ISO week (the spread guarantee)
-- Returns the loudest catalysts per week, ordered by impact. SECURITY DEFINER so
-- the public (service-role) quote page reads it under RLS.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION swingtrader.get_ticker_impact_news(
  p_ticker text,
  p_days integer DEFAULT 365,
  p_limit integer DEFAULT 150,
  p_per_bucket integer DEFAULT 2
)
RETURNS TABLE (
  article_id bigint,
  title text,
  url text,
  source text,
  slug text,
  published_at timestamptz,
  sentiment double precision,
  impact_magnitude double precision,
  top_dimensions jsonb
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = swingtrader, public
AS $$
  WITH heads AS (
    SELECT s.article_id, avg(s.sentiment_score)::double precision AS sentiment
    FROM swingtrader.ticker_sentiment_heads s
    WHERE s.ticker = upper(btrim(p_ticker))
      AND s.article_ts >= now() - make_interval(days => greatest(1, least(p_days, 400)))
    GROUP BY s.article_id
  ),
  scored AS (
    SELECT
      h.article_id,
      h.sentiment,
      a.title, a.url, a.source, a.slug,
      COALESCE(a.published_at, a.created_at) AS published_at,
      COALESCE(v.impact_magnitude, 0)::double precision AS impact_magnitude,
      v.top_dimensions
    FROM heads h
    JOIN swingtrader.news_articles a ON a.id = h.article_id
    LEFT JOIN swingtrader.news_impact_vectors v ON v.article_id = h.article_id
  ),
  bucketed AS (
    SELECT scored.*,
      row_number() OVER (
        PARTITION BY date_trunc('week', published_at)
        ORDER BY impact_magnitude DESC, published_at DESC
      ) AS rnk
    FROM scored
  )
  SELECT article_id, title, url, source, slug, published_at,
         sentiment, impact_magnitude, top_dimensions
  FROM bucketed
  WHERE rnk <= greatest(1, p_per_bucket)
  ORDER BY impact_magnitude DESC, published_at DESC
  LIMIT greatest(1, least(p_limit, 400));
$$;

GRANT EXECUTE ON FUNCTION swingtrader.impact_vector_magnitude(jsonb) TO service_role;
GRANT EXECUTE ON FUNCTION swingtrader.get_ticker_impact_news(text, integer, integer, integer)
  TO anon, authenticated, service_role;
