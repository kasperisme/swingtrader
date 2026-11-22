-- The Arena daily digest: email the standings and the day's trades after each session.
--
-- Why: /arena changes every trading day (nine AI agents, one fill at each open), and a
-- visitor who found it once has no way to follow the season short of coming back
-- daily. This is the lead magnet on /arena: leave an email, get one mail per session
-- with the table (rank, movement, return) and every order filled or queued.
--
-- Same shape as drawdown_analysis_subscriptions (20261122120000): email-only, soft
-- unsubscribe through an HMAC-signed link (UNSUBSCRIBE_SECRET, slug "arena"), written
-- only by the service role. Read by services/arena/digest.py.
--
-- arena_digest_sends makes sending idempotent: one row per session, written before
-- any mail goes out, so a re-run of run-day never mails twice.

CREATE TABLE IF NOT EXISTS swingtrader.arena_digest_subscriptions (
  id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email                TEXT NOT NULL,
  status               TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'unsubscribed')),
  source               TEXT,
  user_id              UUID,
  referrer             TEXT,
  user_agent           TEXT,
  metadata             JSONB NOT NULL DEFAULT '{}'::jsonb,
  confirmation_sent_at TIMESTAMPTZ,
  last_sent_session    DATE,
  unsubscribed_at      TIMESTAMPTZ,
  created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS arena_digest_subscriptions_email_key
  ON swingtrader.arena_digest_subscriptions (email);
CREATE INDEX IF NOT EXISTS arena_digest_subscriptions_active_idx
  ON swingtrader.arena_digest_subscriptions (status) WHERE status = 'active';

CREATE TABLE IF NOT EXISTS swingtrader.arena_digest_sends (
  session         DATE PRIMARY KEY,
  championship_id UUID,
  started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at     TIMESTAMPTZ,
  recipients      INTEGER,
  sent            INTEGER,
  failed          INTEGER
);

ALTER TABLE swingtrader.arena_digest_subscriptions ENABLE ROW LEVEL SECURITY;
ALTER TABLE swingtrader.arena_digest_sends         ENABLE ROW LEVEL SECURITY;

GRANT ALL ON swingtrader.arena_digest_subscriptions TO service_role;
GRANT ALL ON swingtrader.arena_digest_sends         TO service_role;
