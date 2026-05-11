-- Bound hourly news-trends views to last 60 days so their CTEs don't scan the full base table.
-- Original views (in 20260414100000_news_trends_aggregate_views.sql) compute `bucket_counts`
-- and `article_cluster_scores` over every article — the outer WHERE on `bucket_hour`
-- cannot push into those CTEs, which causes statement timeouts on Supabase.
--
-- Filtering inside the view on `published_at` (indexed via idx_news_articles_published_at)
-- bounds the scan up-front so the rollup stays under `statement_timeout`.

CREATE OR REPLACE VIEW swingtrader.news_trends_dimension_hourly_v AS
WITH recent_base AS (
  SELECT *
  FROM swingtrader.news_trends_article_base_v
  WHERE published_at >= (now() - INTERVAL '60 days')
),
recent_points AS (
  SELECT
    r.article_id,
    r.bucket_hour,
    r.confidence_mean,
    e.key AS dimension_key,
    NULLIF(e.value, '')::double precision AS dimension_value
  FROM recent_base r
  CROSS JOIN LATERAL jsonb_each_text(r.impact_jsonb) AS e(key, value)
  WHERE
    jsonb_typeof(r.impact_jsonb) = 'object'
    AND NULLIF(e.value, '') IS NOT NULL
),
bucket_counts AS (
  SELECT
    bucket_hour,
    COUNT(DISTINCT article_id) AS bucket_article_count
  FROM recent_base
  GROUP BY bucket_hour
)
SELECT
  p.bucket_hour,
  p.dimension_key,
  bc.bucket_article_count,
  COUNT(*) AS sample_count,
  COUNT(DISTINCT p.article_id) AS article_count,
  AVG(p.dimension_value) AS dimension_avg,
  COALESCE(
    SUM(p.dimension_value * GREATEST(COALESCE(p.confidence_mean, 1), 0))
      / NULLIF(SUM(GREATEST(COALESCE(p.confidence_mean, 1), 0)), 0),
    AVG(p.dimension_value)
  ) AS dimension_weighted_avg
FROM recent_points p
JOIN bucket_counts bc
  ON bc.bucket_hour = p.bucket_hour
GROUP BY p.bucket_hour, p.dimension_key, bc.bucket_article_count;

CREATE OR REPLACE VIEW swingtrader.news_trends_cluster_hourly_v AS
WITH recent_base AS (
  SELECT *
  FROM swingtrader.news_trends_article_base_v
  WHERE published_at >= (now() - INTERVAL '60 days')
),
recent_points AS (
  SELECT
    r.article_id,
    r.bucket_hour,
    r.confidence_mean,
    e.key AS dimension_key,
    NULLIF(e.value, '')::double precision AS dimension_value
  FROM recent_base r
  CROSS JOIN LATERAL jsonb_each_text(r.impact_jsonb) AS e(key, value)
  WHERE
    jsonb_typeof(r.impact_jsonb) = 'object'
    AND NULLIF(e.value, '') IS NOT NULL
),
dimension_cluster_map AS (
  SELECT *
  FROM (
    VALUES
      ('interest_rate_sensitivity_duration', 'MACRO_SENSITIVITY'),
      ('interest_rate_sensitivity_debt', 'MACRO_SENSITIVITY'),
      ('dollar_sensitivity', 'MACRO_SENSITIVITY'),
      ('inflation_sensitivity', 'MACRO_SENSITIVITY'),
      ('credit_spread_sensitivity', 'MACRO_SENSITIVITY'),
      ('commodity_input_exposure', 'MACRO_SENSITIVITY'),
      ('energy_cost_intensity', 'MACRO_SENSITIVITY'),
      ('sector_financials', 'SECTOR_ROTATION'),
      ('sector_technology', 'SECTOR_ROTATION'),
      ('sector_healthcare', 'SECTOR_ROTATION'),
      ('sector_energy', 'SECTOR_ROTATION'),
      ('sector_realestate', 'SECTOR_ROTATION'),
      ('sector_consumer', 'SECTOR_ROTATION'),
      ('sector_industrials', 'SECTOR_ROTATION'),
      ('sector_utilities', 'SECTOR_ROTATION'),
      ('revenue_predictability', 'BUSINESS_MODEL'),
      ('revenue_cyclicality', 'BUSINESS_MODEL'),
      ('pricing_power_structural', 'BUSINESS_MODEL'),
      ('pricing_power_cyclical', 'BUSINESS_MODEL'),
      ('capex_intensity', 'BUSINESS_MODEL'),
      ('debt_burden', 'FINANCIAL_STRUCTURE'),
      ('floating_rate_debt_ratio', 'FINANCIAL_STRUCTURE'),
      ('debt_maturity_nearterm', 'FINANCIAL_STRUCTURE'),
      ('financial_health', 'FINANCIAL_STRUCTURE'),
      ('earnings_quality', 'FINANCIAL_STRUCTURE'),
      ('accruals_ratio', 'FINANCIAL_STRUCTURE'),
      ('buyback_capacity', 'FINANCIAL_STRUCTURE'),
      ('revenue_growth_rate', 'GROWTH_PROFILE'),
      ('eps_growth_rate', 'GROWTH_PROFILE'),
      ('eps_acceleration', 'GROWTH_PROFILE'),
      ('forward_growth_expectations', 'GROWTH_PROFILE'),
      ('earnings_revision_trend', 'GROWTH_PROFILE'),
      ('valuation_multiple', 'VALUATION_POSITIONING'),
      ('factor_value', 'VALUATION_POSITIONING'),
      ('short_interest_ratio', 'VALUATION_POSITIONING'),
      ('short_squeeze_risk', 'VALUATION_POSITIONING'),
      ('price_momentum', 'VALUATION_POSITIONING'),
      ('china_revenue_exposure', 'GEOGRAPHY_TRADE'),
      ('emerging_market_exposure', 'GEOGRAPHY_TRADE'),
      ('domestic_revenue_concentration', 'GEOGRAPHY_TRADE'),
      ('tariff_sensitivity', 'GEOGRAPHY_TRADE'),
      ('upstream_concentration', 'SUPPLY_CHAIN_EXPOSURE'),
      ('geographic_supply_risk', 'SUPPLY_CHAIN_EXPOSURE'),
      ('inventory_intensity', 'SUPPLY_CHAIN_EXPOSURE'),
      ('input_specificity', 'SUPPLY_CHAIN_EXPOSURE'),
      ('supplier_bargaining_power', 'SUPPLY_CHAIN_EXPOSURE'),
      ('downstream_customer_concentration', 'SUPPLY_CHAIN_EXPOSURE'),
      ('institutional_appeal', 'MARKET_BEHAVIOUR'),
      ('institutional_ownership_change', 'MARKET_BEHAVIOUR'),
      ('short_squeeze_potential', 'MARKET_BEHAVIOUR'),
      ('earnings_surprise_volatility', 'MARKET_BEHAVIOUR')
  ) AS t(dimension_key, cluster_id)
),
article_cluster_scores AS (
  SELECT
    p.article_id,
    p.bucket_hour,
    m.cluster_id,
    AVG(p.dimension_value) AS article_cluster_score,
    MAX(p.confidence_mean) AS confidence_mean
  FROM recent_points p
  JOIN dimension_cluster_map m
    ON m.dimension_key = p.dimension_key
  GROUP BY p.article_id, p.bucket_hour, m.cluster_id
),
bucket_counts AS (
  SELECT
    bucket_hour,
    COUNT(DISTINCT article_id) AS bucket_article_count
  FROM recent_base
  GROUP BY bucket_hour
)
SELECT
  a.bucket_hour,
  a.cluster_id,
  bc.bucket_article_count,
  COUNT(*) AS article_count,
  AVG(a.article_cluster_score) AS cluster_avg,
  COALESCE(
    SUM(a.article_cluster_score * GREATEST(COALESCE(a.confidence_mean, 1), 0))
      / NULLIF(SUM(GREATEST(COALESCE(a.confidence_mean, 1), 0)), 0),
    AVG(a.article_cluster_score)
  ) AS cluster_weighted_avg
FROM article_cluster_scores a
JOIN bucket_counts bc
  ON bc.bucket_hour = a.bucket_hour
GROUP BY a.bucket_hour, a.cluster_id, bc.bucket_article_count;

GRANT SELECT ON
  swingtrader.news_trends_dimension_hourly_v,
  swingtrader.news_trends_cluster_hourly_v
TO anon, authenticated, service_role;
