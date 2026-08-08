-- ---------------------------------------------------------------------------
-- /quote index: search + pagination.
--
-- The directory turned out to hold ~3.7k tickers over a 30-day window, so the
-- first cut (top 200, no controls) hid most of it and gave a visitor no way to
-- reach a specific symbol. This replaces the RPC with a paged, searchable one.
--
-- Return type changes (adds total_count), so the old two-arg signature has to be
-- dropped rather than REPLACEd.
--
-- total_count rides along on every row via count(*) OVER () — one scan answers
-- both "this page" and "how many pages", instead of a second count query. An
-- empty result returns no rows at all, so callers must treat a missing
-- total_count as zero.
-- ---------------------------------------------------------------------------
DROP FUNCTION IF EXISTS swingtrader.get_top_covered_tickers(integer, integer);

CREATE OR REPLACE FUNCTION swingtrader.get_top_covered_tickers(
  p_days integer DEFAULT 30,
  p_limit integer DEFAULT 50,
  p_offset integer DEFAULT 0,
  p_search text DEFAULT NULL
)
RETURNS TABLE (
  ticker text,
  mention_count bigint,
  scored_count bigint,
  avg_sentiment double precision,
  last_day date,
  company_name text,
  sector text,
  total_count bigint
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = swingtrader, public
AS $$
  WITH params AS (
    SELECT
      NULLIF(btrim(COALESCE(p_search, '')), '') AS q_raw,
      -- LIKE metacharacters in user input would silently turn a search into a
      -- wildcard ('%' matches everything). Escape them and pair with ESCAPE '\'.
      replace(replace(replace(
        NULLIF(btrim(COALESCE(p_search, '')), ''),
        '\', '\\'), '%', '\%'), '_', '\_') AS q_like
  ),
  windowed AS (
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
      -- symbols that get indexed. Drops numeric/foreign codes ('000063.SZ').
      AND d.ticker ~ '^[A-Z][A-Z0-9.\-]{0,11}$'
    GROUP BY d.ticker
    -- An unscored mention carries no impact data, so its quote page would be
    -- thin — exactly what /quote/[symbol] already noindexes.
    HAVING sum(d.scored_count) > 0
  ),
  joined AS (
    SELECT
      w.*,
      t.company_name::text AS company_name,
      t.sector::text AS sector
    FROM windowed w
    LEFT JOIN swingtrader.tickers t ON t.symbol = w.ticker
  ),
  filtered AS (
    SELECT j.*
    FROM joined j, params p
    WHERE p.q_raw IS NULL
       -- Symbols are searched as a prefix (typing "NV" should reach NVDA), but
       -- company names as a substring ("semiconductor" should reach anything in
       -- the name). Only part of the universe has a name, hence the OR.
       OR j.ticker LIKE upper(p.q_like) || '%' ESCAPE '\'
       OR j.company_name ILIKE '%' || p.q_like || '%' ESCAPE '\'
  )
  SELECT
    f.ticker,
    f.mention_count,
    f.scored_count,
    f.avg_sentiment,
    f.last_day,
    f.company_name,
    f.sector,
    count(*) OVER () AS total_count
  FROM filtered f, params p
  ORDER BY
    -- An exact symbol hit outranks coverage: someone typing "F" wants Ford, not
    -- whichever F-prefixed name happens to be loudest this month.
    (p.q_raw IS NOT NULL AND f.ticker = upper(p.q_raw)) DESC,
    f.scored_count DESC,
    f.mention_count DESC,
    f.ticker
  LIMIT greatest(1, least(p_limit, 200))
  OFFSET greatest(0, least(p_offset, 100000));
$$;

GRANT EXECUTE ON FUNCTION swingtrader.get_top_covered_tickers(integer, integer, integer, text)
  TO anon, authenticated, service_role;
