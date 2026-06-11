-- ---------------------------------------------------------------------------
-- News briefing subscriptions: the free, no-account email service that sends a
-- nicely structured PDF of the last 24h of news, summaries and impact for the
-- tickers / tags a visitor cares about.
--
-- Mirrors market_screening_email_subscriptions (email-only, soft-unsubscribe,
-- service-role access) but the unit a visitor subscribes to is their OWN
-- watchlist of tickers + tags rather than a curated screening. One briefing per
-- email — editing the watchlist is an in-place update via a signed manage link,
-- no login required.
--
-- Delivery:
--   * On signup we set initial_briefing_requested_at; the Python briefing tick
--     generates + sends the first PDF immediately (within ~1 min).
--   * Thereafter the daily fan-out fires one hour before the NYSE open
--     (08:30 America/New_York, weekdays); last_sent_at makes it idempotent.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS swingtrader.news_briefing_subscriptions (
    id                          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    email                       TEXT        NOT NULL,
    -- The watchlist. Tickers are stored upper-case (AAPL), tags lower-case (ai).
    -- Either may be empty, but the app requires at least one of the two.
    tickers                     TEXT[]      NOT NULL DEFAULT '{}',
    tags                        TEXT[]      NOT NULL DEFAULT '{}',
    -- 'active' | 'unsubscribed'. Soft-delete so we keep history and can
    -- re-subscribe / re-edit in place.
    status                      TEXT        NOT NULL DEFAULT 'active',
    -- Best-effort attribution + auth user if one happened to be signed in.
    source                      TEXT        NOT NULL DEFAULT 'briefing_subscribe',
    user_id                     UUID        REFERENCES auth.users (id) ON DELETE SET NULL,
    referrer                    TEXT,
    user_agent                  TEXT,
    metadata                    JSONB       NOT NULL DEFAULT '{}'::jsonb,
    -- Set on signup (and on any explicit "send me one now"); the tick picks it
    -- up, sends immediately, then clears it. Decouples the immediate send from
    -- the Next.js request so the route never has to render a PDF inline.
    initial_briefing_requested_at TIMESTAMPTZ,
    -- Last time a briefing PDF was delivered. Drives daily-fan-out idempotency
    -- (send only when last_sent_at is before the most recent scheduled fire).
    last_sent_at                TIMESTAMPTZ,
    unsubscribed_at             TIMESTAMPTZ,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- One briefing per email. Re-subscribe / edit upserts this row.
-- Plain `email` (not lower(email)) so the column matches the
-- `onConflict: "email"` target the /api/briefings/subscribe upsert uses —
-- PostgREST's on_conflict cannot reference an expression index, and the app
-- normalises email to lowercase before every write.
CREATE UNIQUE INDEX IF NOT EXISTS idx_briefing_subscriptions_email
    ON swingtrader.news_briefing_subscriptions (email);

-- Daily fan-out: "all active subscriptions, oldest delivery first".
CREATE INDEX IF NOT EXISTS idx_briefing_subscriptions_status_sent
    ON swingtrader.news_briefing_subscriptions (status, last_sent_at);

-- Immediate-send queue: "active subscriptions awaiting their first/forced send".
CREATE INDEX IF NOT EXISTS idx_briefing_subscriptions_initial
    ON swingtrader.news_briefing_subscriptions (initial_briefing_requested_at)
    WHERE initial_briefing_requested_at IS NOT NULL;

ALTER TABLE swingtrader.news_briefing_subscriptions ENABLE ROW LEVEL SECURITY;

-- No client-side policies: all writes/reads go through the /api/briefings/*
-- routes (service_role key) and the Python tick (service-role Supabase client).
-- anon/authenticated cannot touch this table directly (prevents email-list
-- scraping + spammy inserts).
GRANT ALL ON swingtrader.news_briefing_subscriptions TO service_role;

COMMENT ON TABLE swingtrader.news_briefing_subscriptions IS
    'Free, no-account email briefing list. One row per email; each row is a watchlist of tickers + tags that receives a daily 24h-news PDF. Service-role access only.';
