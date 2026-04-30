-- next_run_at: pre-computed next scheduled execution time per screening.
-- The scheduler tick advances this after queueing each run, enabling missed-run
-- detection without relying on a fixed time window.

ALTER TABLE swingtrader.user_scheduled_screenings
  ADD COLUMN IF NOT EXISTS next_run_at TIMESTAMPTZ;

-- Fast lookup: find all active screenings that are due.
CREATE INDEX IF NOT EXISTS idx_scheduled_screenings_next_run
  ON swingtrader.user_scheduled_screenings (next_run_at ASC)
  WHERE is_active = true AND next_run_at IS NOT NULL;

-- Fast lookup: find queued (due) result rows ordered oldest-first for dispatch.
CREATE INDEX IF NOT EXISTS idx_screening_results_due
  ON swingtrader.user_screening_results (run_at ASC)
  WHERE status = 'due';
