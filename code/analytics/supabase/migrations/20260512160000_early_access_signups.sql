-- ---------------------------------------------------------------------------
-- Early access signups: waitlist captured when a visitor (anonymous OR
-- authenticated) clicks "Subscribe" on a public screening in the gallery.
--
-- We do not auto-create a real subscription row. The product is in early-
-- access mode; conversions to `public_screening_subscriptions` happen later
-- via an admin/manual approval flow.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS swingtrader.early_access_signups (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    email               TEXT        NOT NULL,
    public_screening_id UUID        REFERENCES swingtrader.public_screenings (id) ON DELETE SET NULL,
    user_id             UUID        REFERENCES auth.users (id) ON DELETE SET NULL,
    source              TEXT        NOT NULL DEFAULT 'gallery_subscribe',
    referrer            TEXT,
    user_agent          TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- One signup per email per screening (NULL screening_id treated as distinct).
CREATE UNIQUE INDEX IF NOT EXISTS idx_early_access_signups_unique
    ON swingtrader.early_access_signups (lower(email), public_screening_id);

CREATE INDEX IF NOT EXISTS idx_early_access_signups_screening
    ON swingtrader.early_access_signups (public_screening_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_early_access_signups_created
    ON swingtrader.early_access_signups (created_at DESC);

ALTER TABLE swingtrader.early_access_signups ENABLE ROW LEVEL SECURITY;

-- No client-side policies: all writes/reads go through the server action
-- using the service_role key. anon/authenticated cannot touch this table
-- directly (prevents email-list scraping + scrubs spammy direct inserts).

GRANT ALL ON swingtrader.early_access_signups TO service_role;
