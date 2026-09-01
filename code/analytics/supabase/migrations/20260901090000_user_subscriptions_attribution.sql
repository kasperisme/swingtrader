-- ---------------------------------------------------------------------------
-- user_subscriptions.attribution
--
-- Which ad produced a paying customer.
--
-- Meta reports conversions it *believes* it caused; the email-lead tables carry
-- utm_content and so can be reconciled against real rows, but the subscription
-- table had no attribution at all. That made the only question a paid campaign
-- exists to answer — "which ad is producing revenue, not just sign-ups" —
-- unanswerable from our own data.
--
-- Populated by the stripe-webhook Edge Function from the Stripe session
-- metadata, which the browser filled from the first-touch `nis_attr` cookie
-- (lib/attribution.ts) at checkout. Shape mirrors the other capture sites:
--   {"utm_source","utm_medium","utm_campaign","utm_content","utm_term",
--    "fbclid","ttclid","gclid","landing"}
-- Empty object for an organic subscription; never NULL, so the reconcile query
-- does not have to special-case it.
-- ---------------------------------------------------------------------------

ALTER TABLE swingtrader.user_subscriptions
    ADD COLUMN IF NOT EXISTS attribution JSONB NOT NULL DEFAULT '{}'::jsonb;

COMMENT ON COLUMN swingtrader.user_subscriptions.attribution IS
    'First-touch ad attribution captured at checkout (utm_*, click ids, landing path). {} = organic.';

-- The reconcile path groups paying customers by feature, i.e. utm_content.
CREATE INDEX IF NOT EXISTS idx_user_subscriptions_utm_content
    ON swingtrader.user_subscriptions ((attribution ->> 'utm_content'));
