-- ---------------------------------------------------------------------------
-- Link scan_jobs, scan_runs, scan_rows, and scan_row_notes to auth.users.
--
-- Strategy:
--   - scan_runs  : nullable user_id (runs can be system-triggered or user-triggered)
--   - scan_rows  : nullable user_id (inherits context from the parent run)
--   - scan_jobs  : nullable user_id (some jobs may be system-level)
--   - scan_row_notes : NOT NULL user_id + RLS (notes are always per-user)
--
-- For scan_row_notes the existing UNIQUE (scan_row_id) is too strict once
-- multiple users can annotate the same row; it is replaced by
-- UNIQUE (scan_row_id, user_id).
-- ---------------------------------------------------------------------------

-- ---------------------------------------------------------------------------
-- scan_runs
-- ---------------------------------------------------------------------------
ALTER TABLE swingtrader.user_scan_runs
    ADD COLUMN IF NOT EXISTS user_id UUID
        REFERENCES auth.users (id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_scan_runs_user_id
    ON swingtrader.user_scan_runs (user_id);

-- ---------------------------------------------------------------------------
-- scan_rows
-- ---------------------------------------------------------------------------
ALTER TABLE swingtrader.user_scan_rows
    ADD COLUMN IF NOT EXISTS user_id UUID
        REFERENCES auth.users (id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_scan_rows_user_id
    ON swingtrader.user_scan_rows (user_id);

-- ---------------------------------------------------------------------------
-- scan_jobs
-- ---------------------------------------------------------------------------
ALTER TABLE swingtrader.user_scan_jobs
    ADD COLUMN IF NOT EXISTS user_id UUID
        REFERENCES auth.users (id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_scan_jobs_user_id
    ON swingtrader.user_scan_jobs (user_id);

ALTER TABLE swingtrader.user_scan_jobs ENABLE ROW LEVEL SECURITY;

-- Authenticated users see only their own jobs; service_role bypasses RLS.
DROP POLICY IF EXISTS scan_jobs_select_own ON swingtrader.user_scan_jobs;
CREATE POLICY scan_jobs_select_own
    ON swingtrader.user_scan_jobs
    FOR SELECT
    TO authenticated
    USING (auth.uid() = user_id);

DROP POLICY IF EXISTS scan_jobs_insert_own ON swingtrader.user_scan_jobs;
CREATE POLICY scan_jobs_insert_own
    ON swingtrader.user_scan_jobs
    FOR INSERT
    TO authenticated
    WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS scan_jobs_update_own ON swingtrader.user_scan_jobs;
CREATE POLICY scan_jobs_update_own
    ON swingtrader.user_scan_jobs
    FOR UPDATE
    TO authenticated
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS scan_jobs_delete_own ON swingtrader.user_scan_jobs;
CREATE POLICY scan_jobs_delete_own
    ON swingtrader.user_scan_jobs
    FOR DELETE
    TO authenticated
    USING (auth.uid() = user_id);

-- ---------------------------------------------------------------------------
-- scan_row_notes
-- ---------------------------------------------------------------------------
-- Drop the single-user unique constraint before adding user_id.
ALTER TABLE swingtrader.user_scan_row_notes
    DROP CONSTRAINT IF EXISTS user_scan_row_notes_scan_row_id_key;

ALTER TABLE swingtrader.user_scan_row_notes
    ADD COLUMN IF NOT EXISTS user_id UUID
        REFERENCES auth.users (id) ON DELETE CASCADE;

-- One note per (row, user) pair.
ALTER TABLE swingtrader.user_scan_row_notes
    DROP CONSTRAINT IF EXISTS user_scan_row_notes_scan_row_id_user_id_key;

ALTER TABLE swingtrader.user_scan_row_notes
    ADD CONSTRAINT user_scan_row_notes_scan_row_id_user_id_key
        UNIQUE (scan_row_id, user_id);

CREATE INDEX IF NOT EXISTS idx_scan_row_notes_user_id
    ON swingtrader.user_scan_row_notes (user_id);

ALTER TABLE swingtrader.user_scan_row_notes ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS scan_row_notes_select_own ON swingtrader.user_scan_row_notes;
CREATE POLICY scan_row_notes_select_own
    ON swingtrader.user_scan_row_notes
    FOR SELECT
    TO authenticated
    USING (auth.uid() = user_id);

DROP POLICY IF EXISTS scan_row_notes_insert_own ON swingtrader.user_scan_row_notes;
CREATE POLICY scan_row_notes_insert_own
    ON swingtrader.user_scan_row_notes
    FOR INSERT
    TO authenticated
    WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS scan_row_notes_update_own ON swingtrader.user_scan_row_notes;
CREATE POLICY scan_row_notes_update_own
    ON swingtrader.user_scan_row_notes
    FOR UPDATE
    TO authenticated
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS scan_row_notes_delete_own ON swingtrader.user_scan_row_notes;
CREATE POLICY scan_row_notes_delete_own
    ON swingtrader.user_scan_row_notes
    FOR DELETE
    TO authenticated
    USING (auth.uid() = user_id);
