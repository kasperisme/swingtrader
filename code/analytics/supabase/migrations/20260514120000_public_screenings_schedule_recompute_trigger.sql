-- ---------------------------------------------------------------------------
-- Auto-recompute public_screenings.next_run_at when the schedule or timezone
-- changes.
--
-- Background: the scheduler advances `next_run_at` by ONE step from its
-- previous value when a fire is queued. It never recomputes from scratch on
-- schedule changes, which means an edit from (say) "0 16 * * 1-5" to
-- "0,30 * * * 1-5" leaves a stale `next_run_at` anchored to the old cadence
-- — so the new schedule appears not to fire.
--
-- This trigger nulls `next_run_at` whenever `schedule` or `timezone` actually
-- changes; the next scheduler tick re-initializes it from `last_run_at`.
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION swingtrader.recompute_public_screenings_next_run_at()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    NEW.next_run_at = NULL;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_public_screenings_recompute_next_run_at
    ON swingtrader.public_screenings;
CREATE TRIGGER trg_public_screenings_recompute_next_run_at
    BEFORE UPDATE OF schedule, timezone ON swingtrader.public_screenings
    FOR EACH ROW
    WHEN (OLD.schedule IS DISTINCT FROM NEW.schedule
       OR OLD.timezone IS DISTINCT FROM NEW.timezone)
    EXECUTE FUNCTION swingtrader.recompute_public_screenings_next_run_at();
