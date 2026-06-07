-- ---------------------------------------------------------------------------
-- Add linked_scan_sources[] to user_scheduled_screenings
--
--   linked_scan_sources   TEXT[] — scan-run `source` strings the agent FOLLOWS.
--
-- Unlike `linked_scan_run_ids` (pinned, frozen run IDs), a followed source is
-- resolved at run time to the NEWEST active `user_scan_runs` row for that
-- (user_id, source). As fresh runs land periodically (e.g. market-screening
-- fan-out writing `source = 'market_screening:{slug}'` per subscriber), the
-- agent auto-switches to the latest run without any edit. An agent may mix
-- pinned IDs and followed sources; a source is either followed or pinned,
-- never both (enforced in the UI).
-- ---------------------------------------------------------------------------

ALTER TABLE swingtrader.user_scheduled_screenings
    ADD COLUMN IF NOT EXISTS linked_scan_sources TEXT[] DEFAULT '{}';

COMMENT ON COLUMN swingtrader.user_scheduled_screenings.linked_scan_sources IS
    'Scan-run source strings followed-latest; engine resolves each to the newest '
    'active user_scan_runs.id for this user at run time.';

CREATE INDEX IF NOT EXISTS idx_scheduled_screenings_linked_sources
    ON swingtrader.user_scheduled_screenings USING GIN (linked_scan_sources);

-- Resolver filters user_scan_runs by (user_id, status, source) and picks the
-- newest by scan_date. The existing idx_user_scan_runs_user_status_created does
-- not cover `source`, so add a source-aware index for the latest-per-source lookup.
CREATE INDEX IF NOT EXISTS idx_user_scan_runs_user_status_source_date
    ON swingtrader.user_scan_runs (user_id, status, source, scan_date DESC);
