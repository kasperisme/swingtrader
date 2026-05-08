-- ---------------------------------------------------------------------------
-- onboarding checklist dismissal
--
-- Adds a single column to user_profiles so the on-dashboard onboarding
-- checklist can be dismissed independently of the welcome dialog
-- (welcomed_at). Per-step "visited" flags are stored in user_profiles.metadata
-- under metadata.onboarding_visited.{articles,narrative,screenings} — using
-- the existing JSONB column avoids a migration per checklist item.
-- ---------------------------------------------------------------------------

ALTER TABLE swingtrader.user_profiles
    ADD COLUMN IF NOT EXISTS onboarding_dismissed_at TIMESTAMPTZ;
