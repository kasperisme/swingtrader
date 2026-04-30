-- Add status tracking to user_screening_results for concurrency control.
-- status: 'running' while executing, 'done' on success, 'error' on failure.
-- started_at: when execution began (used to detect stuck jobs).

ALTER TABLE swingtrader.user_screening_results
  ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'done',
  ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ;

-- Backfill: treat all existing rows as done (run_at approximates started_at).
UPDATE swingtrader.user_screening_results
  SET started_at = run_at
  WHERE started_at IS NULL;

-- Fast lookup for concurrency check (count running jobs).
CREATE INDEX IF NOT EXISTS idx_screening_results_status_running
  ON swingtrader.user_screening_results (screening_id, started_at DESC)
  WHERE status = 'running';
