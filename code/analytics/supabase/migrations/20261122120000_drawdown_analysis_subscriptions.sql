-- Correction stress test: email updates when a new analysis is published.
--
-- Why: /correction is the drawdown stress test (services/drawdown). It is republished
-- whenever the panel reviews a new day, and a reader who found it once has no way to
-- know a new one exists. This is the lead magnet behind the header link and the
-- site-wide promo: leave an email and get one mail per new analysis.
--
-- Mirrors news_briefing_subscriptions / market_screening_email_subscriptions:
-- email-only, no account, soft unsubscribe through an HMAC-signed link
-- (UNSUBSCRIBE_SECRET, slug "correction"), written only by the service role.
--
-- drawdown_analysis_notifications makes sending idempotent: one row per as_of, written
-- before any mail goes out (services/drawdown/notify.py), so a re-run never mails twice.

CREATE TABLE IF NOT EXISTS swingtrader.drawdown_analysis_subscriptions (
  id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email                TEXT NOT NULL,
  status               TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'unsubscribed')),
  source               TEXT,
  user_id              UUID,
  referrer             TEXT,
  user_agent           TEXT,
  metadata             JSONB NOT NULL DEFAULT '{}'::jsonb,
  confirmation_sent_at TIMESTAMPTZ,
  last_notified_as_of  DATE,
  unsubscribed_at      TIMESTAMPTZ,
  created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS drawdown_analysis_subscriptions_email_key
  ON swingtrader.drawdown_analysis_subscriptions (email);
CREATE INDEX IF NOT EXISTS drawdown_analysis_subscriptions_active_idx
  ON swingtrader.drawdown_analysis_subscriptions (status) WHERE status = 'active';

CREATE TABLE IF NOT EXISTS swingtrader.drawdown_analysis_notifications (
  as_of       DATE PRIMARY KEY,
  started_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at TIMESTAMPTZ,
  recipients  INTEGER,
  sent        INTEGER,
  failed      INTEGER
);

ALTER TABLE swingtrader.drawdown_analysis_subscriptions ENABLE ROW LEVEL SECURITY;
ALTER TABLE swingtrader.drawdown_analysis_notifications ENABLE ROW LEVEL SECURITY;
-- No policies: anon/authenticated get nothing; the service role bypasses RLS.

GRANT ALL ON swingtrader.drawdown_analysis_subscriptions TO service_role;
GRANT ALL ON swingtrader.drawdown_analysis_notifications TO service_role;
