-- ---------------------------------------------------------------------------
-- telegram_message_log — record every Telegram message sent by the platform
--
-- Populated by the Mac Mini cron (run_daily_narrative.py) and any future
-- server-side Telegram sender.  Read-only from the UI for audit/debug.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS swingtrader.telegram_message_log (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             UUID        NOT NULL REFERENCES auth.users (id) ON DELETE CASCADE,
    chat_id             VARCHAR     NOT NULL,
    -- e.g. 'daily_narrative', 'alert', 'system'
    message_type        VARCHAR     NOT NULL DEFAULT 'daily_narrative',
    message_text        TEXT,
    -- Telegram's own message_id returned from sendMessage; NULL if send failed
    telegram_message_id BIGINT,
    success             BOOLEAN     NOT NULL DEFAULT FALSE,
    error_text          TEXT,
    sent_at             TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_telegram_message_log_user
    ON swingtrader.telegram_message_log (user_id, sent_at DESC);

CREATE INDEX IF NOT EXISTS idx_telegram_message_log_sent_at
    ON swingtrader.telegram_message_log (sent_at DESC);

ALTER TABLE swingtrader.telegram_message_log ENABLE ROW LEVEL SECURITY;

-- Users can see their own message history
DROP POLICY IF EXISTS tg_log_select_own ON swingtrader.telegram_message_log;
CREATE POLICY tg_log_select_own ON swingtrader.telegram_message_log
    FOR SELECT TO authenticated USING (auth.uid() = user_id);

-- Service role (Mac Mini / webhook) writes the rows — anon/authenticated cannot INSERT
GRANT ALL ON swingtrader.telegram_message_log TO service_role;
GRANT SELECT ON swingtrader.telegram_message_log TO authenticated;
