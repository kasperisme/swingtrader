-- Add an ordered event log to each screening run.
--
-- `trace` holds the chronological sequence of events for a run
-- (classify → plan → fetch → analytics → eval → conclude). It is written by
-- persist_and_deliver and is populated even when a run errors or times out, so
-- a failed job can be reconstructed from the database without trawling logs.
--
-- Shape: { started_at, elapsed, event_count, events: [ {seq, dt, stage, event, ...} ] }

ALTER TABLE swingtrader.user_screening_results
  ADD COLUMN IF NOT EXISTS trace JSONB;

COMMENT ON COLUMN swingtrader.user_screening_results.trace IS
  'Ordered event log of the run (classify→plan→fetch→analytics→eval→conclude), persisted even on error/timeout.';
