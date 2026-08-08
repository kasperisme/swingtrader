-- ---------------------------------------------------------------------------
-- Materialize the /quote directory's daily rollup.
--
-- get_top_covered_tickers read news_trends_ticker_daily_v directly, which
-- rescans 120 days of news_article_tickers + news_articles + ticker_sentiment
-- heads on every call: measured 4.6s for a plain page and 7.6s for a search —
-- against the REST role's 8s statement_timeout. That is a page that breaks the
-- first time the corpus grows.
--
-- Same split the topic hubs use: membership stays live, the expensive rollup is
-- materialized and rebuilt post-ingest. A table (not a matview) so it can carry
-- RLS like its siblings.
--
-- Only the daily rollup is stored, NOT the windowed aggregate — that keeps
-- p_days a real parameter and leaves one row per ticker-day (~60k over the full
-- 120 days), which re-aggregates in milliseconds.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS swingtrader.ticker_coverage_daily (
  bucket_day    date   NOT NULL,
  ticker        text   NOT NULL,
  mention_count bigint NOT NULL,
  scored_count  bigint NOT NULL,
  avg_sentiment double precision,
  PRIMARY KEY (bucket_day, ticker)
);

-- The directory filters by window then groups by ticker; search hits ticker
-- directly.
CREATE INDEX IF NOT EXISTS ticker_coverage_daily_ticker_idx
  ON swingtrader.ticker_coverage_daily (ticker);

CREATE OR REPLACE FUNCTION swingtrader.refresh_ticker_coverage_daily()
RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = swingtrader, pg_temp
AS $$
DECLARE
  v_count INTEGER := 0;
BEGIN
  DELETE FROM swingtrader.ticker_coverage_daily WHERE TRUE;  -- safeupdate needs a WHERE

  INSERT INTO swingtrader.ticker_coverage_daily
    (bucket_day, ticker, mention_count, scored_count, avg_sentiment)
  SELECT
    d.bucket_day,
    d.ticker::text,
    d.mention_count,
    d.scored_count,
    d.avg_sentiment
  FROM swingtrader.news_trends_ticker_daily_v d
  -- Same shape gate the sitemap applies, so the hub lists exactly the symbols
  -- that get indexed. Drops numeric/foreign codes ('000063.SZ').
  WHERE d.ticker ~ '^[A-Z][A-Z0-9.\-]{0,11}$';

  GET DIAGNOSTICS v_count = ROW_COUNT;
  RETURN v_count;
END;
$$;

-- Post-ingest entry point, mirroring exec_topic_claims_refresh.
CREATE OR REPLACE FUNCTION swingtrader.exec_ticker_coverage_refresh()
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = swingtrader, pg_temp
AS $$
BEGIN
  PERFORM swingtrader.refresh_ticker_coverage_daily();
END;
$$;

-- Batch budget, same rationale as the sibling refresh RPCs: the REST role
-- carries statement_timeout=8s, which a full rebuild cannot meet. A
-- function-level SET overrides it for this function only.
ALTER FUNCTION swingtrader.exec_ticker_coverage_refresh() SET statement_timeout = '300s';
ALTER FUNCTION swingtrader.exec_ticker_coverage_refresh() SET lock_timeout = '30s';

-- ---------------------------------------------------------------------------
-- The directory RPC, now reading the materialized rollup. Behaviour is
-- unchanged from 20260808140000 — only the source table differs.
-- ---------------------------------------------------------------------------
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
      d.ticker,
      sum(d.mention_count) AS mention_count,
      sum(d.scored_count) AS scored_count,
      sum(d.avg_sentiment * d.scored_count)
        / NULLIF(sum(d.scored_count) FILTER (WHERE d.avg_sentiment IS NOT NULL), 0)
        AS avg_sentiment,
      max(d.bucket_day) AS last_day
    FROM swingtrader.ticker_coverage_daily d
    WHERE d.bucket_day >= (current_date - greatest(1, least(p_days, 120)))
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

-- RLS mirrors the sibling materializations: service_role bypasses, anon+auth read.
ALTER TABLE swingtrader.ticker_coverage_daily ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Public read ticker coverage" ON swingtrader.ticker_coverage_daily;
CREATE POLICY "Public read ticker coverage" ON swingtrader.ticker_coverage_daily
  FOR SELECT TO anon, authenticated USING (true);

GRANT SELECT ON swingtrader.ticker_coverage_daily TO anon, authenticated, service_role;

REVOKE ALL ON FUNCTION swingtrader.refresh_ticker_coverage_daily() FROM PUBLIC;
REVOKE ALL ON FUNCTION swingtrader.exec_ticker_coverage_refresh() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION swingtrader.refresh_ticker_coverage_daily() TO service_role;
GRANT EXECUTE ON FUNCTION swingtrader.exec_ticker_coverage_refresh() TO service_role;

GRANT EXECUTE ON FUNCTION swingtrader.get_top_covered_tickers(integer, integer, integer, text)
  TO anon, authenticated, service_role;

-- Initial build so the page has data before the next ingest.
SELECT swingtrader.refresh_ticker_coverage_daily();
