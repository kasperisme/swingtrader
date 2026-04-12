-- ---------------------------------------------------------------------------
-- Add Telegram link token columns to user_narrative_preferences
--
-- Used for the one-time deep-link flow:
--   1. UI generates a token → stores here with 15-min expiry
--   2. User clicks t.me/Bot?start=<token>
--   3. Bot reads /start payload → looks up token → saves chat_id → clears token
-- ---------------------------------------------------------------------------

ALTER TABLE swingtrader.user_narrative_preferences
    ADD COLUMN IF NOT EXISTS telegram_link_token     VARCHAR,
    ADD COLUMN IF NOT EXISTS telegram_link_expires_at TIMESTAMPTZ;

CREATE UNIQUE INDEX IF NOT EXISTS idx_narrative_prefs_link_token
    ON swingtrader.user_narrative_preferences (telegram_link_token)
    WHERE telegram_link_token IS NOT NULL;
