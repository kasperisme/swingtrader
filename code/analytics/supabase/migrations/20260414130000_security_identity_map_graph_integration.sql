-- ---------------------------------------------------------------------------
-- Unified security identity map + graph integration
--
-- Goal:
-- - Keep ticker aliases and company-name aliases in one table.
-- - Resolve graph edges to canonical tickers through that map.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS swingtrader.security_identity_map (
  id BIGSERIAL PRIMARY KEY,
  alias_kind TEXT NOT NULL
    CHECK (alias_kind IN ('ticker', 'company_name', 'isin', 'figi', 'cusip', 'lei', 'other')),
  alias_value TEXT NOT NULL,
  alias_value_norm TEXT GENERATED ALWAYS AS (
    lower(regexp_replace(btrim(alias_value), '\s+', ' ', 'g'))
  ) STORED,
  canonical_ticker TEXT NOT NULL,
  canonical_company_name TEXT,
  confidence DOUBLE PRECISION NOT NULL DEFAULT 1.0
    CHECK (confidence >= 0.0 AND confidence <= 1.0),
  source TEXT NOT NULL DEFAULT 'manual',
  verified BOOLEAN NOT NULL DEFAULT FALSE,
  metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT security_identity_map_alias_unique UNIQUE (alias_kind, alias_value_norm)
);

CREATE INDEX IF NOT EXISTS idx_security_identity_map_canonical_ticker
  ON swingtrader.security_identity_map (canonical_ticker);

CREATE INDEX IF NOT EXISTS idx_security_identity_map_verified_confidence
  ON swingtrader.security_identity_map (verified DESC, confidence DESC);

CREATE OR REPLACE FUNCTION swingtrader.touch_security_identity_map_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_security_identity_map_updated_at ON swingtrader.security_identity_map;
CREATE TRIGGER trg_security_identity_map_updated_at
  BEFORE UPDATE ON swingtrader.security_identity_map
  FOR EACH ROW
  EXECUTE FUNCTION swingtrader.touch_security_identity_map_updated_at();

-- Deterministic ticker bootstrap (symbol -> itself)
INSERT INTO swingtrader.security_identity_map (
  alias_kind,
  alias_value,
  canonical_ticker,
  canonical_company_name,
  confidence,
  source,
  verified,
  metadata_json
)
SELECT DISTINCT
  'ticker' AS alias_kind,
  t.symbol AS alias_value,
  upper(btrim(t.symbol)) AS canonical_ticker,
  t.company_name AS canonical_company_name,
  1.0 AS confidence,
  'swingtrader.tickers' AS source,
  TRUE AS verified,
  '{}'::jsonb AS metadata_json
FROM swingtrader.tickers t
WHERE t.symbol IS NOT NULL
  AND btrim(t.symbol) <> ''
ON CONFLICT (alias_kind, alias_value_norm) DO NOTHING;

CREATE OR REPLACE FUNCTION swingtrader.resolve_canonical_ticker(
  p_alias_value TEXT,
  p_alias_kind TEXT DEFAULT 'ticker'
)
RETURNS TEXT
LANGUAGE sql
STABLE
AS $$
  SELECT COALESCE(
    (
      SELECT sim.canonical_ticker
      FROM swingtrader.security_identity_map sim
      WHERE sim.alias_kind = p_alias_kind
        AND sim.alias_value_norm = lower(regexp_replace(btrim(COALESCE(p_alias_value, '')), '\s+', ' ', 'g'))
      ORDER BY sim.verified DESC, sim.confidence DESC, sim.id ASC
      LIMIT 1
    ),
    upper(btrim(COALESCE(p_alias_value, '')))
  );
$$;

-- Canonicalized graph view for adjacency traversal.
CREATE OR REPLACE VIEW swingtrader.ticker_relationship_network_resolved_v AS
WITH canonicalized AS (
  SELECT
    swingtrader.resolve_canonical_ticker(e.from_ticker, 'ticker') AS from_ticker,
    swingtrader.resolve_canonical_ticker(e.to_ticker, 'ticker') AS to_ticker,
    e.rel_type,
    e.strength_avg,
    e.strength_max,
    e.mention_count,
    e.article_count,
    e.first_seen_at,
    e.last_seen_at
  FROM swingtrader.ticker_relationship_edges e
),
collapsed AS (
  SELECT
    c.from_ticker,
    c.to_ticker,
    c.rel_type,
    SUM(c.strength_avg * GREATEST(c.mention_count, 1)) / NULLIF(SUM(GREATEST(c.mention_count, 1)), 0) AS strength_avg,
    MAX(c.strength_max) AS strength_max,
    SUM(c.mention_count) AS mention_count,
    SUM(c.article_count) AS article_count,
    MIN(c.first_seen_at) AS first_seen_at,
    MAX(c.last_seen_at) AS last_seen_at
  FROM canonicalized c
  WHERE c.from_ticker <> ''
    AND c.to_ticker <> ''
    AND c.from_ticker <> c.to_ticker
  GROUP BY c.from_ticker, c.to_ticker, c.rel_type
)
SELECT
  from_ticker,
  to_ticker,
  rel_type,
  strength_avg,
  strength_max,
  mention_count,
  article_count,
  first_seen_at,
  last_seen_at
FROM collapsed;

GRANT SELECT ON swingtrader.security_identity_map TO anon, authenticated, service_role;
GRANT SELECT ON swingtrader.ticker_relationship_network_resolved_v TO anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION swingtrader.resolve_canonical_ticker(TEXT, TEXT) TO anon, authenticated, service_role;
