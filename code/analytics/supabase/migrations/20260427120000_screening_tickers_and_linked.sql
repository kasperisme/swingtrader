-- ---------------------------------------------------------------------------
-- Add tickers[] and linked_scan_run_ids[] to user_scheduled_screenings
--
--   tickers                TEXT[]   — ticker symbols the agent should focus on
--   linked_scan_run_ids    INTEGER[] — scan runs (user_scan_runs) whose data the agent can reference
-- ---------------------------------------------------------------------------

ALTER TABLE swingtrader.user_scheduled_screenings
    ADD COLUMN IF NOT EXISTS tickers                TEXT[]     DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS linked_scan_run_ids    INTEGER[]  DEFAULT '{}';

CREATE INDEX IF NOT EXISTS idx_scheduled_screenings_tickers
    ON swingtrader.user_scheduled_screenings USING GIN (tickers);

CREATE INDEX IF NOT EXISTS idx_scheduled_screenings_linked
    ON swingtrader.user_scheduled_screenings USING GIN (linked_scan_run_ids);