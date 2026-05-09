-- ---------------------------------------------------------------------------
-- Add ticker_subset to user_bulk_analysis_jobs.
--
-- When the user has filters active in the screening view (e.g. only rows with
-- impact > 7, or only stage-2 setups), the bulk-analyse run should respect
-- that selection instead of iterating every row in the scan run. The UI
-- snapshots the filtered ticker list at submit time and stores it here.
--
--   ticker_subset  TEXT[] — when NULL, the worker analyses every row in
--                            scan_run_id (legacy behaviour). When non-NULL,
--                            the worker only analyses rows whose symbol is
--                            in this list.
-- ---------------------------------------------------------------------------

ALTER TABLE swingtrader.user_bulk_analysis_jobs
    ADD COLUMN IF NOT EXISTS ticker_subset TEXT[];

CREATE INDEX IF NOT EXISTS idx_bulk_analysis_jobs_ticker_subset
    ON swingtrader.user_bulk_analysis_jobs USING GIN (ticker_subset)
    WHERE ticker_subset IS NOT NULL;
