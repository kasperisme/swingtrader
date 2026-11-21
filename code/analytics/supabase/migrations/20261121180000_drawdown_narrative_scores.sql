-- ---------------------------------------------------------------------------
-- drawdown: the narrative stress test, published to /correction
--
-- Why: services/drawdown/narrative.py asks, for every name with a priced-in
-- reconstruction, whether the revenue growth its share price REQUIRES (10y
-- reverse DCF re-solved at today's close) still fits inside what analysts
-- FORECAST (3y consensus from drawdown_estimate_snapshots, faded to terminal
-- growth) once a correction cuts those forecasts. It is a description of
-- whether a narrative is funded, NOT a return forecast: the priced-in
-- walk-forward found implied growth alone is no return signal
-- (strategylab/research/PRICED-IN-FINDINGS.md §6), and the judged
-- priced_in_pct layer is not used at all.
--
-- One row per (as_of, ticker). The run row is written LAST; a day is shown on
-- the site only once its run row exists, so a half-written day never renders.
-- `seal_sha256` hashes the ranked list so the 2026-11-21 groups can be graded
-- later without anyone being able to re-rank them after the fact.
--
-- `declines` (what the price refuses to pay for) is stored for completeness but
-- is members-only on /quote; the public /correction pages never select it.
-- Service-role only, like the rest of the drawdown_* family: the site reads it
-- through the service client.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS swingtrader.drawdown_narrative_scores (
  as_of                DATE        NOT NULL,
  ticker               TEXT        NOT NULL,
  company              TEXT,
  sector               TEXT,
  grp                  TEXT        NOT NULL CHECK (grp IN ('on_top','holds','fragile','drowns','not_cash_flow','refused')),
  rank                 INTEGER,
  reason               TEXT,
  thesis               TEXT,
  breaks_if            TEXT,
  price                DOUBLE PRECISION,
  close_date           DATE,
  drawdown_from_peak   DOUBLE PRECISION,
  move_since_model     DOUBLE PRECISION,
  required_cagr        DOUBLE PRECISION,
  consensus_3y         DOUBLE PRECISION,
  supported_cagr       DOUBLE PRECISION,
  breakeven_cut        DOUBLE PRECISION,
  margin_used          DOUBLE PRECISION,
  upside_to_median     DOUBLE PRECISION,
  n_targets            INTEGER,
  targets_predate_drop BOOLEAN,
  model_as_of          DATE,
  epicenter            BOOLEAN,
  epicenter_linked     BOOLEAN,
  linked_with          TEXT,
  beta                 DOUBLE PRECISION,
  exposure             TEXT CHECK (exposure IN ('low','medium','high')),
  flags                TEXT,
  crux                 TEXT,
  position             TEXT,
  pays_for             JSONB,
  declines             JSONB,
  created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (as_of, ticker)
);

CREATE INDEX IF NOT EXISTS drawdown_narrative_scores_ticker_idx
  ON swingtrader.drawdown_narrative_scores (ticker, as_of DESC);
CREATE INDEX IF NOT EXISTS drawdown_narrative_scores_grp_idx
  ON swingtrader.drawdown_narrative_scores (as_of, grp, rank);

CREATE TABLE IF NOT EXISTS swingtrader.drawdown_narrative_runs (
  as_of             DATE        PRIMARY KEY,
  estimate_snapshot DATE        NOT NULL,
  drop_date         DATE        NOT NULL,
  universe          INTEGER     NOT NULL,
  groups            JSONB       NOT NULL,
  params            JSONB       NOT NULL,
  seal_sha256       TEXT        NOT NULL,
  finished_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE swingtrader.drawdown_narrative_scores ENABLE ROW LEVEL SECURITY;
ALTER TABLE swingtrader.drawdown_narrative_runs   ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON swingtrader.drawdown_narrative_scores FROM anon, authenticated;
REVOKE ALL ON swingtrader.drawdown_narrative_runs   FROM anon, authenticated;
GRANT ALL ON swingtrader.drawdown_narrative_scores TO service_role;
GRANT ALL ON swingtrader.drawdown_narrative_runs   TO service_role;
