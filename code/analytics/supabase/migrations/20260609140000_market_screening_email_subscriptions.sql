-- ---------------------------------------------------------------------------
-- Market screening EMAIL subscriptions: the lightweight, email-only delivery
-- list that powers the "Send me the results" CTA across the site (article
-- bridge CTA + the screenings gallery Subscribe buttons).
--
-- This is deliberately separate from the two existing tables:
--   * early_access_signups            — a waitlist / lead capture. No delivery
--                                       intent; conversions are manual.
--   * market_screening_subscriptions  — auth-only (user_id FK). In-app +
--                                       Telegram delivery for signed-in users.
--
-- This table answers "which email wants which screening results, on which
-- channel" with no account required. One row per (email, screening). A signup
-- is idempotent; unsubscribing is a soft status flip (status='unsubscribed')
-- so we keep an auditable record and support one-click re-subscribe.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS swingtrader.market_screening_email_subscriptions (
    id                    UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    email                 TEXT        NOT NULL,
    market_screening_id   UUID        NOT NULL
                            REFERENCES swingtrader.market_screenings (id) ON DELETE CASCADE,
    -- Delivery channel. 'email' today; 'telegram' reserved for parity with the
    -- authed flow without another migration.
    channel               TEXT        NOT NULL DEFAULT 'email',
    -- 'active' | 'unsubscribed'. Soft-delete so we keep the history and can
    -- re-subscribe in place.
    status                TEXT        NOT NULL DEFAULT 'active',
    -- Best-effort attribution: where the subscribe came from (article_bridge,
    -- gallery_subscribe, gallery_footer, …) and the auth user if one existed.
    source                TEXT        NOT NULL DEFAULT 'email_subscribe',
    user_id               UUID        REFERENCES auth.users (id) ON DELETE SET NULL,
    referrer              TEXT,
    user_agent            TEXT,
    metadata              JSONB       NOT NULL DEFAULT '{}'::jsonb,
    confirmation_sent_at  TIMESTAMPTZ,
    unsubscribed_at       TIMESTAMPTZ,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- One subscription per email per screening. Re-subscribe upserts this row.
-- NOTE: plain `email` (not lower(email)) so the column list matches the
-- `onConflict: "email,market_screening_id"` target used by the /api/subscribe
-- upsert — PostgREST's on_conflict cannot reference an expression index, and
-- the app already normalises email to lowercase before every write.
CREATE UNIQUE INDEX IF NOT EXISTS idx_mse_subscriptions_unique
    ON swingtrader.market_screening_email_subscriptions (email, market_screening_id);

-- Delivery query: "all active subscribers for screening X".
CREATE INDEX IF NOT EXISTS idx_mse_subscriptions_screening_active
    ON swingtrader.market_screening_email_subscriptions (market_screening_id, status);

-- "All screenings this email follows" (powers the unsubscribe page summary).
CREATE INDEX IF NOT EXISTS idx_mse_subscriptions_email
    ON swingtrader.market_screening_email_subscriptions (lower(email));

ALTER TABLE swingtrader.market_screening_email_subscriptions ENABLE ROW LEVEL SECURITY;

-- No client-side policies: all writes/reads go through the /api/subscribe and
-- /api/unsubscribe routes using the service_role key. anon/authenticated cannot
-- touch this table directly (prevents email-list scraping + spammy inserts).
GRANT ALL ON swingtrader.market_screening_email_subscriptions TO service_role;

COMMENT ON TABLE swingtrader.market_screening_email_subscriptions IS
    'Email-only, no-account delivery list for market screening results. One row per (email, screening). Service-role access only.';
