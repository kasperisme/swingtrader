-- ---------------------------------------------------------------------------
-- Ticker Pair Stats (cointegration / pairs-trading metrics on the graph)
--
-- Why:
-- - The news-derived relationship graph (ticker_relationship_edges) already
--   prunes the candidate set: we only ever test pairs that share a verified
--   economic link, not a blind N^2 universe scan.
-- - Price-derived statistics (hedge ratio, Engle-Granger p-value, OU half-life,
--   rolling spread mean/std) live HERE, in a separate lineage from the
--   news-derived edges, so the relationship-graph refresh never clobbers them
--   and vice versa. The two are stitched together in a view.
--
-- Two clocks (kept up to date by two separate CLIs / cron jobs):
--   - Calibration (slow, weekly): hedge_ratio, coint_pvalue, half_life_days,
--     spread_mean, spread_std  -> services/pairs/calibrate_cli.py
--   - Live signal (fast, daily/intraday): current_spread, current_zscore
--     computed against the STORED calibration -> services/pairs/zscore_cli.py
--
-- Pairs are stored order-normalized (ticker_a < ticker_b): cointegration is a
-- property of the unordered pair, not of a directed rel_type, so one row here
-- serves every relationship type between the same two companies.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS swingtrader.ticker_pair_stats (
  id BIGSERIAL PRIMARY KEY,
  ticker_a TEXT NOT NULL,
  ticker_b TEXT NOT NULL,

  -- Calibration (slow clock) ------------------------------------------------
  hedge_ratio DOUBLE PRECISION,                 -- OLS beta: A ~ alpha + beta*B
  coint_pvalue DOUBLE PRECISION                 -- Engle-Granger ADF p-value on the spread
    CHECK (coint_pvalue IS NULL OR (coint_pvalue >= 0 AND coint_pvalue <= 1)),
  half_life_days DOUBLE PRECISION,              -- OU mean-reversion half-life (NULL if non-reverting)
  spread_mean DOUBLE PRECISION,                 -- rolling-window mean of (A - hedge_ratio*B)
  spread_std DOUBLE PRECISION,                  -- rolling-window std of the spread
  window_days INTEGER NOT NULL DEFAULT 252,     -- calibration lookback used
  n_obs INTEGER,                                -- aligned observations used in the fit
  is_cointegrated BOOLEAN GENERATED ALWAYS AS
    (coint_pvalue IS NOT NULL AND coint_pvalue < 0.05) STORED,
  calibrated_at TIMESTAMPTZ,                     -- last full recalibration

  -- Live signal (fast clock) ------------------------------------------------
  current_price_a DOUBLE PRECISION,
  current_price_b DOUBLE PRECISION,
  current_spread DOUBLE PRECISION,
  current_zscore DOUBLE PRECISION,              -- (current_spread - spread_mean) / spread_std
  zscore_at TIMESTAMPTZ,                         -- last z-score refresh

  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,

  CONSTRAINT ticker_pair_stats_ordered CHECK (ticker_a < ticker_b),
  CONSTRAINT ticker_pair_stats_unique UNIQUE (ticker_a, ticker_b)
);

CREATE INDEX IF NOT EXISTS idx_ticker_pair_stats_a
  ON swingtrader.ticker_pair_stats (ticker_a);

CREATE INDEX IF NOT EXISTS idx_ticker_pair_stats_b
  ON swingtrader.ticker_pair_stats (ticker_b);

-- Surface the live signal cheaply: |z| desc, cointegrated pairs only.
CREATE INDEX IF NOT EXISTS idx_ticker_pair_stats_zscore
  ON swingtrader.ticker_pair_stats (ABS(current_zscore) DESC)
  WHERE current_zscore IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_ticker_pair_stats_coint
  ON swingtrader.ticker_pair_stats (coint_pvalue)
  WHERE coint_pvalue IS NOT NULL AND coint_pvalue < 0.05;

-- Pick up the existing updated_at touch convention.
CREATE OR REPLACE FUNCTION swingtrader.touch_ticker_pair_stats_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_ticker_pair_stats_updated_at ON swingtrader.ticker_pair_stats;
CREATE TRIGGER trg_ticker_pair_stats_updated_at
  BEFORE UPDATE ON swingtrader.ticker_pair_stats
  FOR EACH ROW
  EXECUTE FUNCTION swingtrader.touch_ticker_pair_stats_updated_at();

-- ---------------------------------------------------------------------------
-- Candidate pairs: order-normalized, deduped across rel_types, off the
-- canonicalized graph. This is the whole moat in one view — calibrate_cli only
-- ever fits pairs that appear here, so we test hundreds of news-linked pairs
-- per week, not the tens of thousands a blind universe scan would.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW swingtrader.ticker_pair_candidates_v AS
SELECT
  LEAST(e.from_ticker, e.to_ticker)    AS ticker_a,
  GREATEST(e.from_ticker, e.to_ticker) AS ticker_b,
  SUM(e.article_count)                 AS article_count,
  SUM(e.mention_count)                 AS mention_count,
  MAX(e.strength_avg)                  AS strength_max_any,
  MAX(e.last_seen_at)                  AS last_seen_at,
  array_agg(DISTINCT e.rel_type)       AS rel_types
FROM swingtrader.ticker_relationship_network_resolved_v e
WHERE e.from_ticker <> ''
  AND e.to_ticker <> ''
  AND e.from_ticker <> e.to_ticker
GROUP BY
  LEAST(e.from_ticker, e.to_ticker),
  GREATEST(e.from_ticker, e.to_ticker);

-- ---------------------------------------------------------------------------
-- The stitched view: every news-derived edge, now carrying its pair's live
-- cointegration metrics. A news event triggers the existing graph traversal
-- (get_relationship_neighborhood / relationshipsGetNeighborhood) and every
-- returned edge already has is_cointegrated + current_zscore on it — no new
-- plumbing for the UI/agent layer.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW swingtrader.ticker_relationship_network_pairs_v AS
SELECT
  e.from_ticker,
  e.to_ticker,
  e.rel_type,
  e.strength_avg,
  e.strength_max,
  e.mention_count,
  e.article_count,
  e.first_seen_at,
  e.last_seen_at,
  s.hedge_ratio,
  s.coint_pvalue,
  s.is_cointegrated,
  s.half_life_days,
  s.spread_mean,
  s.spread_std,
  s.current_zscore,
  s.zscore_at,
  s.calibrated_at
FROM swingtrader.ticker_relationship_network_resolved_v e
LEFT JOIN swingtrader.ticker_pair_stats s
  ON s.ticker_a = LEAST(e.from_ticker, e.to_ticker)
 AND s.ticker_b = GREATEST(e.from_ticker, e.to_ticker);

GRANT SELECT ON swingtrader.ticker_pair_stats TO anon, authenticated, service_role;
GRANT SELECT ON swingtrader.ticker_pair_candidates_v TO anon, authenticated, service_role;
GRANT SELECT ON swingtrader.ticker_relationship_network_pairs_v TO anon, authenticated, service_role;
GRANT INSERT, UPDATE ON swingtrader.ticker_pair_stats TO service_role;
GRANT USAGE, SELECT ON SEQUENCE swingtrader.ticker_pair_stats_id_seq TO service_role;
