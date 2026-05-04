-- ---------------------------------------------------------------------------
-- user_bulk_analysis_jobs
--
-- Tracks fire-and-forget bulk per-ticker technical-analysis jobs. One job per
-- "Analyze all" click on a scan run. The Python worker
-- (services.bulk_analysis) picks up status='queued' rows on its 1-min tick,
-- iterates the run's tickers via Ollama, writes the result into
-- user_ticker_chart_workspace.ai_chat_messages and the call into
-- user_scan_row_notes.status, then marks the job done.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS swingtrader.user_bulk_analysis_jobs (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id      UUID NOT NULL REFERENCES auth.users (id) ON DELETE CASCADE,
    scan_run_id  BIGINT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'queued'
                 CHECK (status IN ('queued', 'running', 'done', 'error', 'cancelled')),
    total_tickers     INTEGER NOT NULL DEFAULT 0,
    completed_tickers INTEGER NOT NULL DEFAULT 0,
    failed_tickers    INTEGER NOT NULL DEFAULT 0,
    started_at    TIMESTAMPTZ,
    finished_at   TIMESTAMPTZ,
    error_message TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_bulk_analysis_jobs_user
    ON swingtrader.user_bulk_analysis_jobs (user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_bulk_analysis_jobs_run
    ON swingtrader.user_bulk_analysis_jobs (scan_run_id, created_at DESC);

-- Worker tick uses this to pick up queued jobs (oldest first) and to count
-- currently running jobs for concurrency control.
CREATE INDEX IF NOT EXISTS idx_bulk_analysis_jobs_status_created
    ON swingtrader.user_bulk_analysis_jobs (status, created_at);

ALTER TABLE swingtrader.user_bulk_analysis_jobs ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS bulk_analysis_jobs_select_own ON swingtrader.user_bulk_analysis_jobs;
CREATE POLICY bulk_analysis_jobs_select_own
    ON swingtrader.user_bulk_analysis_jobs
    FOR SELECT
    TO authenticated
    USING (auth.uid() = user_id);

DROP POLICY IF EXISTS bulk_analysis_jobs_insert_own ON swingtrader.user_bulk_analysis_jobs;
CREATE POLICY bulk_analysis_jobs_insert_own
    ON swingtrader.user_bulk_analysis_jobs
    FOR INSERT
    TO authenticated
    WITH CHECK (auth.uid() = user_id);

-- Updates are performed by the worker (service_role bypasses RLS); allow the
-- owner to cancel via a status flip.
DROP POLICY IF EXISTS bulk_analysis_jobs_update_own ON swingtrader.user_bulk_analysis_jobs;
CREATE POLICY bulk_analysis_jobs_update_own
    ON swingtrader.user_bulk_analysis_jobs
    FOR UPDATE
    TO authenticated
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);
