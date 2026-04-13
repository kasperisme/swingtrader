-- ---------------------------------------------------------------------------
-- Soft-delete support for screening runs.
-- ---------------------------------------------------------------------------

ALTER TABLE swingtrader.user_scan_runs
    ADD COLUMN IF NOT EXISTS status VARCHAR;

UPDATE swingtrader.user_scan_runs
SET status = 'active'
WHERE status IS NULL;

ALTER TABLE swingtrader.user_scan_runs
    ALTER COLUMN status SET DEFAULT 'active',
    ALTER COLUMN status SET NOT NULL;

ALTER TABLE swingtrader.user_scan_runs
    DROP CONSTRAINT IF EXISTS user_scan_runs_status_check;

ALTER TABLE swingtrader.user_scan_runs
    ADD CONSTRAINT user_scan_runs_status_check
    CHECK (status IN ('active', 'deleted'));

CREATE INDEX IF NOT EXISTS idx_user_scan_runs_user_status_created
    ON swingtrader.user_scan_runs (user_id, status, created_at DESC);
