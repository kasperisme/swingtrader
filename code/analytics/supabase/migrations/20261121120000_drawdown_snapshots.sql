-- ---------------------------------------------------------------------------
-- drawdown: point-in-time snapshots that FMP and FRED cannot give back later
--
-- Why: the drawdown recon (services/drawdown/SPEC.md) needs two histories that
-- do not exist anywhere in the platform:
--
--   * analyst consensus estimates AS THEY STOOD on each day. FMP's
--     /stable/analyst-estimates returns only the current consensus, so the
--     revision path (did the AI epicenter's FY+1 EPS get cut during the
--     drawdown?) is lost unless it is snapshotted daily. It drives the
--     flush-vs-bust label and is the only outcome-based check on the
--     fundamental_damage label that does not depend on returns.
--   * macro series (HY OAS, real yields, 2y/10y, NFCI, broad dollar, USDJPY,
--     VIX). FRED keeps history, but vintages get revised; storing the value as
--     first observed keeps a backtest of the regime label point-in-time.
--
-- Both are append-only by intent: a snapshot row describes what was known on
-- snapshot_date / fetched_at. Re-running a day upserts the same keys.
-- Service-role only (no anon/authenticated grants): research inputs, not a
-- public surface.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS swingtrader.drawdown_estimate_snapshots (
  snapshot_date        DATE        NOT NULL,
  symbol               TEXT        NOT NULL,
  fiscal_date          DATE        NOT NULL,   -- fiscal period end the estimate is for
  eps_avg              NUMERIC,
  eps_high             NUMERIC,
  eps_low              NUMERIC,
  revenue_avg          NUMERIC,
  revenue_high         NUMERIC,
  revenue_low          NUMERIC,
  ebitda_avg           NUMERIC,
  net_income_avg       NUMERIC,
  num_analysts_eps     INTEGER,
  num_analysts_revenue INTEGER,
  fetched_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (snapshot_date, symbol, fiscal_date)
);

CREATE INDEX IF NOT EXISTS drawdown_estimate_snapshots_symbol_idx
  ON swingtrader.drawdown_estimate_snapshots (symbol, fiscal_date, snapshot_date);

CREATE TABLE IF NOT EXISTS swingtrader.drawdown_macro_snapshots (
  series_id   TEXT        NOT NULL,   -- e.g. FRED:BAMLH0A0HYM2, FMP:USDJPY
  obs_date    DATE        NOT NULL,
  value       NUMERIC,
  source      TEXT        NOT NULL,   -- fred | fmp
  first_seen  DATE        NOT NULL,   -- snapshot run that first stored this obs
  fetched_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (series_id, obs_date)
);

ALTER TABLE swingtrader.drawdown_estimate_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE swingtrader.drawdown_macro_snapshots    ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON swingtrader.drawdown_estimate_snapshots FROM anon, authenticated;
REVOKE ALL ON swingtrader.drawdown_macro_snapshots    FROM anon, authenticated;
GRANT ALL ON swingtrader.drawdown_estimate_snapshots TO service_role;
GRANT ALL ON swingtrader.drawdown_macro_snapshots    TO service_role;

-- Run manifest: written LAST by each run. A day's snapshots are trusted only when
-- this row says status = 'complete' (more than 5% of symbols failing, or any macro
-- series failing, makes it 'partial'). Row presence alone proves nothing.
CREATE TABLE IF NOT EXISTS swingtrader.drawdown_snapshot_runs (
  snapshot_date        DATE        PRIMARY KEY,
  status               TEXT        NOT NULL CHECK (status IN ('complete', 'partial')),
  universe             INTEGER     NOT NULL,
  estimate_rows        INTEGER     NOT NULL,
  estimate_failed      INTEGER     NOT NULL,
  estimate_no_coverage INTEGER     NOT NULL,
  macro_rows           INTEGER     NOT NULL,
  macro_failed         JSONB       NOT NULL DEFAULT '[]'::jsonb,
  finished_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE swingtrader.drawdown_snapshot_runs ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON swingtrader.drawdown_snapshot_runs FROM anon, authenticated;
GRANT ALL ON swingtrader.drawdown_snapshot_runs TO service_role;
