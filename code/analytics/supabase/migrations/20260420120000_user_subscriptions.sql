-- ---------------------------------------------------------------------------
-- user_subscriptions
--
-- Tracks Stripe subscriptions per user. Created by the Stripe webhook Edge
-- Function on checkout.session.completed / customer.subscription.* events.
-- user_id is nullable so a row can be created before the user has a Supabase
-- auth account (payment first, then account creation).
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS swingtrader.user_subscriptions (
    id                      UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Supabase auth user — set once they create an account
    user_id                 UUID        REFERENCES auth.users(id) ON DELETE SET NULL,

    -- Email from Stripe — used to link subscription before account exists
    email                   TEXT        NOT NULL,

    -- Stripe identifiers
    stripe_customer_id      TEXT        UNIQUE,
    stripe_subscription_id  TEXT        UNIQUE,

    -- Subscription state
    status                  TEXT        NOT NULL DEFAULT 'incomplete',
    plan                    TEXT        NOT NULL,   -- 'investor' | 'trader'
    billing_interval        TEXT        NOT NULL,   -- 'monthly' | 'annual'
    phase                   TEXT        NOT NULL DEFAULT 'phase1',
    grandfathered           BOOLEAN     NOT NULL DEFAULT TRUE,
    current_period_end      TIMESTAMPTZ,

    CONSTRAINT valid_status CHECK (
        status IN ('active', 'trialing', 'past_due', 'canceled', 'unpaid', 'incomplete', 'incomplete_expired')
    ),
    CONSTRAINT valid_plan CHECK (plan IN ('investor', 'trader')),
    CONSTRAINT valid_interval CHECK (billing_interval IN ('monthly', 'annual'))
);

CREATE INDEX IF NOT EXISTS idx_user_subscriptions_user_id
    ON swingtrader.user_subscriptions (user_id);

CREATE INDEX IF NOT EXISTS idx_user_subscriptions_email
    ON swingtrader.user_subscriptions (email);

CREATE INDEX IF NOT EXISTS idx_user_subscriptions_stripe_customer
    ON swingtrader.user_subscriptions (stripe_customer_id);

-- Auto-update updated_at
CREATE OR REPLACE FUNCTION swingtrader.touch_user_subscriptions()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN NEW.updated_at = NOW(); RETURN NEW; END;
$$;

CREATE TRIGGER trg_user_subscriptions_updated_at
    BEFORE UPDATE ON swingtrader.user_subscriptions
    FOR EACH ROW EXECUTE FUNCTION swingtrader.touch_user_subscriptions();

-- RLS
ALTER TABLE swingtrader.user_subscriptions ENABLE ROW LEVEL SECURITY;

-- Authenticated users can read their own subscription
CREATE POLICY "users_read_own_subscription"
    ON swingtrader.user_subscriptions FOR SELECT
    TO authenticated
    USING (user_id = auth.uid());

-- Service role bypasses RLS (webhook writes)
GRANT ALL ON TABLE swingtrader.user_subscriptions TO service_role;
GRANT USAGE ON SEQUENCE swingtrader.user_subscriptions_id_seq TO service_role;

-- ---------------------------------------------------------------------------
-- Helper: link pending subscriptions when a user creates their account.
-- Call this from a post-signup trigger or on first login.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION swingtrader.link_subscription_on_signup()
RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER AS $$
BEGIN
    UPDATE swingtrader.user_subscriptions
    SET user_id = NEW.id
    WHERE email = NEW.email
      AND user_id IS NULL;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_link_subscription_on_signup
    AFTER INSERT ON auth.users
    FOR EACH ROW EXECUTE FUNCTION swingtrader.link_subscription_on_signup();
