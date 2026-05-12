-- ---------------------------------------------------------------------------
-- Subscribed public screenings: surface each subscription as a row in the
-- user's existing user_scheduled_screenings table so subscribed public
-- screenings appear alongside personal screenings in /protected/agents and
-- inherit the per-user Telegram delivery path.
--
-- Two parallel records per subscription:
--   public_screening_subscriptions   — "I want this" (kept; carries
--                                       notifications_enabled + subscribed_at)
--   user_scheduled_screenings        — operational copy linked back via
--                                       source_public_screening_id; receives
--                                       a user_screening_results row each time
--                                       the public screening runs
--
-- Execution stays admin-driven. The scheduler tick skips user_scheduled_screenings
-- rows where source_public_screening_id IS NOT NULL (those don't have their
-- own schedule — they piggyback on the public one).
-- ---------------------------------------------------------------------------

ALTER TABLE swingtrader.user_scheduled_screenings
    ADD COLUMN IF NOT EXISTS source_public_screening_id UUID
        REFERENCES swingtrader.public_screenings (id) ON DELETE CASCADE;

CREATE INDEX IF NOT EXISTS idx_user_scheduled_screenings_source_public
    ON swingtrader.user_scheduled_screenings (source_public_screening_id)
    WHERE source_public_screening_id IS NOT NULL;

-- One operational copy per (user, public screening). The partial-index form
-- leaves regular personal screenings unaffected.
CREATE UNIQUE INDEX IF NOT EXISTS idx_user_scheduled_screenings_user_source_unique
    ON swingtrader.user_scheduled_screenings (user_id, source_public_screening_id)
    WHERE source_public_screening_id IS NOT NULL;
