-- ---------------------------------------------------------------------------
-- user_telegram_connections: general-purpose Telegram account linkage
--
-- Decoupled from user_narrative_preferences so any feature can send
-- personalised Telegram messages without coupling to the narrative system.
--
-- Also removes the Telegram-specific columns that were added to
-- user_narrative_preferences in the previous migrations.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS swingtrader.user_telegram_connections (
    id                      UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id                 UUID        NOT NULL UNIQUE REFERENCES auth.users (id) ON DELETE CASCADE,
    chat_id                 VARCHAR,                    -- set after user completes /start flow
    -- One-time link token for the deep-link connect flow (expires after 15 min)
    link_token              VARCHAR,
    link_expires_at         TIMESTAMPTZ,
    connected_at            TIMESTAMPTZ,                -- when chat_id was first set
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_telegram_connections_link_token
    ON swingtrader.user_telegram_connections (link_token)
    WHERE link_token IS NOT NULL;

CREATE OR REPLACE FUNCTION swingtrader.touch_telegram_connections_updated_at()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN NEW.updated_at = NOW(); RETURN NEW; END; $$;

DROP TRIGGER IF EXISTS trg_telegram_connections_updated_at ON swingtrader.user_telegram_connections;
CREATE TRIGGER trg_telegram_connections_updated_at
    BEFORE UPDATE ON swingtrader.user_telegram_connections
    FOR EACH ROW EXECUTE FUNCTION swingtrader.touch_telegram_connections_updated_at();

ALTER TABLE swingtrader.user_telegram_connections ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS telegram_connections_select_own ON swingtrader.user_telegram_connections;
CREATE POLICY telegram_connections_select_own ON swingtrader.user_telegram_connections
    FOR SELECT TO authenticated USING (auth.uid() = user_id);

DROP POLICY IF EXISTS telegram_connections_insert_own ON swingtrader.user_telegram_connections;
CREATE POLICY telegram_connections_insert_own ON swingtrader.user_telegram_connections
    FOR INSERT TO authenticated WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS telegram_connections_update_own ON swingtrader.user_telegram_connections;
CREATE POLICY telegram_connections_update_own ON swingtrader.user_telegram_connections
    FOR UPDATE TO authenticated
    USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS telegram_connections_delete_own ON swingtrader.user_telegram_connections;
CREATE POLICY telegram_connections_delete_own ON swingtrader.user_telegram_connections
    FOR DELETE TO authenticated USING (auth.uid() = user_id);

GRANT ALL ON swingtrader.user_telegram_connections TO anon, authenticated, service_role;

-- Remove Telegram-specific columns from user_narrative_preferences
-- (delivery_method stays — it controls whether to use Telegram for narratives)
ALTER TABLE swingtrader.user_narrative_preferences
    DROP COLUMN IF EXISTS telegram_chat_id,
    DROP COLUMN IF EXISTS telegram_link_token,
    DROP COLUMN IF EXISTS telegram_link_expires_at;
