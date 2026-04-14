-- Pre-aggregated views for News Trends charts.
-- Goal: avoid scanning/parsing every raw row in the UI path.

-- Supporting indexes for faster joins/bucketing.
CREATE INDEX IF NOT EXISTS idx_news_articles_published_at
  ON swingtrader.news_articles (published_at);

CREATE INDEX IF NOT EXISTS idx_news_impact_vectors_created_at
  ON swingtrader.news_impact_vectors (created_at);

CREATE INDEX IF NOT EXISTS idx_news_impact_heads_created_at_cluster
  ON swingtrader.news_impact_heads (created_at, cluster);

-- 1) Article-level base rows with parsed vectors + mean confidence.
CREATE OR REPLACE VIEW swingtrader.news_trends_article_base_v AS
WITH head_confidence AS (
  SELECT
    nih.article_id,
    AVG(nih.confidence) AS confidence_mean
  FROM swingtrader.news_impact_heads nih
  GROUP BY nih.article_id
)
SELECT
  niv.article_id,
  COALESCE(na.published_at, niv.created_at) AS published_at,
  date_trunc('day', COALESCE(na.published_at, niv.created_at)) AS bucket_day,
  date_trunc('hour', COALESCE(na.published_at, niv.created_at)) AS bucket_hour,
  (niv.impact_json::jsonb) AS impact_jsonb,
  hc.confidence_mean,
  na.id,
  na.title,
  na.url,
  na.source,
  na.slug,
  na.image_url,
  na.created_at AS article_created_at
FROM swingtrader.news_impact_vectors niv
LEFT JOIN swingtrader.news_articles na
  ON na.id = niv.article_id
LEFT JOIN head_confidence hc
  ON hc.article_id = niv.article_id;

-- 2) One row per article/dimension with numeric value.
CREATE OR REPLACE VIEW swingtrader.news_trends_dimension_points_v AS
SELECT
  b.article_id,
  b.published_at,
  b.bucket_day,
  b.bucket_hour,
  b.confidence_mean,
  e.key AS dimension_key,
  NULLIF(e.value, '')::double precision AS dimension_value
FROM swingtrader.news_trends_article_base_v b
CROSS JOIN LATERAL jsonb_each_text(b.impact_jsonb) AS e(key, value)
WHERE
  jsonb_typeof(b.impact_jsonb) = 'object'
  AND NULLIF(e.value, '') IS NOT NULL;

-- 3) Dimension aggregates (daily / hourly), weighted and unweighted.
CREATE OR REPLACE VIEW swingtrader.news_trends_dimension_daily_v AS
WITH bucket_counts AS (
  SELECT
    bucket_day,
    COUNT(DISTINCT article_id) AS bucket_article_count
  FROM swingtrader.news_trends_article_base_v
  GROUP BY bucket_day
)
SELECT
  p.bucket_day,
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
FROM swingtrader.news_trends_dimension_points_v p
JOIN bucket_counts bc
  ON bc.bucket_day = p.bucket_day
GROUP BY p.bucket_day, p.dimension_key, bc.bucket_article_count;

CREATE OR REPLACE VIEW swingtrader.news_trends_dimension_hourly_v AS
WITH bucket_counts AS (
  SELECT
    bucket_hour,
    COUNT(DISTINCT article_id) AS bucket_article_count
  FROM swingtrader.news_trends_article_base_v
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
FROM swingtrader.news_trends_dimension_points_v p
JOIN bucket_counts bc
  ON bc.bucket_hour = p.bucket_hour
GROUP BY p.bucket_hour, p.dimension_key, bc.bucket_article_count;

-- 4) Cluster rollups from dimensions, matching UI logic:
--    per-article cluster = mean(dimensions in cluster), then weighted mean by bucket.
CREATE OR REPLACE VIEW swingtrader.news_trends_cluster_daily_v AS
WITH dimension_cluster_map AS (
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
    p.bucket_day,
    m.cluster_id,
    AVG(p.dimension_value) AS article_cluster_score,
    MAX(p.confidence_mean) AS confidence_mean
  FROM swingtrader.news_trends_dimension_points_v p
  JOIN dimension_cluster_map m
    ON m.dimension_key = p.dimension_key
  GROUP BY p.article_id, p.bucket_day, m.cluster_id
),
bucket_counts AS (
  SELECT
    bucket_day,
    COUNT(DISTINCT article_id) AS bucket_article_count
  FROM swingtrader.news_trends_article_base_v
  GROUP BY bucket_day
)
SELECT
  a.bucket_day,
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
  ON bc.bucket_day = a.bucket_day
GROUP BY a.bucket_day, a.cluster_id, bc.bucket_article_count;

CREATE OR REPLACE VIEW swingtrader.news_trends_cluster_hourly_v AS
WITH dimension_cluster_map AS (
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
  FROM swingtrader.news_trends_dimension_points_v p
  JOIN dimension_cluster_map m
    ON m.dimension_key = p.dimension_key
  GROUP BY p.article_id, p.bucket_hour, m.cluster_id
),
bucket_counts AS (
  SELECT
    bucket_hour,
    COUNT(DISTINCT article_id) AS bucket_article_count
  FROM swingtrader.news_trends_article_base_v
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

-- 5) Head-level aggregates for diagnostics/trend overlays.
CREATE OR REPLACE VIEW swingtrader.news_trends_heads_daily_v AS
WITH bucket_counts AS (
  SELECT
    bucket_day,
    COUNT(DISTINCT article_id) AS bucket_article_count
  FROM swingtrader.news_trends_article_base_v
  GROUP BY bucket_day
)
SELECT
  date_trunc('day', nih.created_at) AS bucket_day,
  nih.cluster,
  bc.bucket_article_count,
  COUNT(*) AS head_count,
  COUNT(DISTINCT nih.article_id) AS article_count,
  AVG(nih.confidence) AS confidence_avg
FROM swingtrader.news_impact_heads nih
JOIN bucket_counts bc
  ON bc.bucket_day = date_trunc('day', nih.created_at)
GROUP BY date_trunc('day', nih.created_at), nih.cluster, bc.bucket_article_count;

CREATE OR REPLACE VIEW swingtrader.news_trends_heads_hourly_v AS
WITH bucket_counts AS (
  SELECT
    bucket_hour,
    COUNT(DISTINCT article_id) AS bucket_article_count
  FROM swingtrader.news_trends_article_base_v
  GROUP BY bucket_hour
)
SELECT
  date_trunc('hour', nih.created_at) AS bucket_hour,
  nih.cluster,
  bc.bucket_article_count,
  COUNT(*) AS head_count,
  COUNT(DISTINCT nih.article_id) AS article_count,
  AVG(nih.confidence) AS confidence_avg
FROM swingtrader.news_impact_heads nih
JOIN bucket_counts bc
  ON bc.bucket_hour = date_trunc('hour', nih.created_at)
GROUP BY date_trunc('hour', nih.created_at), nih.cluster, bc.bucket_article_count;

-- Make views queryable via API roles.
GRANT SELECT ON
  swingtrader.news_trends_article_base_v,
  swingtrader.news_trends_dimension_points_v,
  swingtrader.news_trends_dimension_daily_v,
  swingtrader.news_trends_dimension_hourly_v,
  swingtrader.news_trends_cluster_daily_v,
  swingtrader.news_trends_cluster_hourly_v,
  swingtrader.news_trends_heads_daily_v,
  swingtrader.news_trends_heads_hourly_v
TO anon, authenticated, service_role;
