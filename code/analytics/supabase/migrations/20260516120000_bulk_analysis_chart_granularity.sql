-- Snapshot chart OHLC granularity (and optional date window) from the screenings UI
-- at bulk-analyze submit time. Worker uses these instead of hard-coded daily 6mo.

ALTER TABLE swingtrader.user_bulk_analysis_jobs
    ADD COLUMN IF NOT EXISTS chart_granularity TEXT NOT NULL DEFAULT '1day'
        CHECK (chart_granularity IN ('1hour', '4hour', '1day', '1week')),
    ADD COLUMN IF NOT EXISTS chart_date_from DATE,
    ADD COLUMN IF NOT EXISTS chart_date_to DATE;
