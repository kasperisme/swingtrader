-- ---------------------------------------------------------------------------
-- Public screening results land in the user's scan tables, not the agents
-- (scheduled-screenings) surface. A subscribed public screening is platform-
-- managed — the user did not schedule it. Each run writes:
--
--   user_scan_jobs  — per-subscriber job record (status='completed')
--   user_scan_runs  — per-subscriber scan instance (source=<script_key>)
--   user_scan_rows  — N per-ticker rows tied to the run
--
-- user_screening_results is NOT used for public screenings.
--
-- This migration is purely a cleanup of the transitional model: remove the
-- "operational copy" rows in user_scheduled_screenings that the previous
-- fan-out implementation synthesised for subscribers.
-- ---------------------------------------------------------------------------

DELETE FROM swingtrader.user_scheduled_screenings
WHERE source_public_screening_id IS NOT NULL;
