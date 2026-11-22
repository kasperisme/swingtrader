-- Drawdown stress test: add the columns that 20261121180000 only declares.
--
-- Why: drawdown_narrative_scores was created from the first version of
-- 20261121180000. Its later columns (earnings quality, cost of equity, the agent
-- review, the council-4 value basis and events) were added INSIDE that file's
-- CREATE TABLE IF NOT EXISTS, which is a no-op on a table that already exists. So a
-- database created from the first version never got them, and
-- services/drawdown/narrative.write_db (which writes all of them) fails there.
-- Idempotent: every column is ADD COLUMN IF NOT EXISTS; a fresh database that ran the
-- current 20261121180000 already has them all and this is a no-op.

ALTER TABLE swingtrader.drawdown_narrative_scores
  ADD COLUMN IF NOT EXISTS margin_basis         TEXT CHECK (margin_basis IN ('consensus','quality','midcycle')),
  ADD COLUMN IF NOT EXISTS breakeven_consensus  DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS breakeven_quality    DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS quality_margin       DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS cash_conversion      DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS cash_margin          DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS consensus_margin     DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS quality              TEXT NOT NULL DEFAULT 'unknown' CHECK (quality IN ('clean','watch','weak','unknown')),
  ADD COLUMN IF NOT EXISTS quality_flags        TEXT,
  ADD COLUMN IF NOT EXISTS cfo_to_ni            DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS accruals             DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS sbc_to_revenue       DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS share_growth         DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS one_off_share        DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS quality_years        INTEGER,
  ADD COLUMN IF NOT EXISTS cost_of_equity       DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS midcycle_margin      DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS hist_net_margin      DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS loss_making          BOOLEAN,
  ADD COLUMN IF NOT EXISTS sector_pct           DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS value_basis          TEXT,
  ADD COLUMN IF NOT EXISTS events               TEXT,
  ADD COLUMN IF NOT EXISTS rule_grp             TEXT CHECK (rule_grp IN ('on_top','holds','fragile','drowns','not_cash_flow','refused')),
  ADD COLUMN IF NOT EXISTS correction_cut       DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS judgement            JSONB;
