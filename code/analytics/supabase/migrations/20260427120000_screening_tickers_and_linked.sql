-- ---------------------------------------------------------------------------
-- Add tickers[] and linked_screening_ids[] to user_scheduled_screenings
--
--   tickers                 TEXT[]  — ticker symbols the agent should focus on
--   linked_screening_ids    UUID[]  — other screenings whose context the agent can read
-- ---------------------------------------------------------------------------

ALTER TABLE swingtrader.user_scheduled_screenings
    ADD COLUMN IF NOT EXISTS tickers              TEXT[]   DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS linked_screening_ids  UUID[]   DEFAULT '{}';

CREATE INDEX IF NOT EXISTS idx_scheduled_screenings_tickers
    ON swingtrader.user_scheduled_screenings USING GIN (tickers);

CREATE INDEX IF NOT EXISTS idx_scheduled_screenings_linked
    ON swingtrader.user_scheduled_screenings USING GIN (linked_screening_ids);