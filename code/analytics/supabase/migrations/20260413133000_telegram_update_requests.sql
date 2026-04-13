-- ---------------------------------------------------------------------------
-- telegram_update_requests
--
-- Queue table for on-demand Telegram /update requests.
-- Webhook inserts pending rows; Mac worker processes and sends responses.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS swingtrader.telegram_update_requests (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             UUID        NOT NULL REFERENCES auth.users (id) ON DELETE CASCADE,
    chat_id             VARCHAR     NOT NULL,
    status              VARCHAR     NOT NULL DEFAULT 'pending',
    requested_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at          TIMESTAMPTZ,
    completed_at        TIMESTAMPTZ,
    response_preview    TEXT,
    telegram_message_id BIGINT,
    error_text          TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT telegram_update_requests_status_check
      CHECK (status IN ('pending', 'processing', 'completed', 'failed'))
);

CREATE INDEX IF NOT EXISTS idx_tg_update_requests_status_requested_at
    ON swingtrader.telegram_update_requests (status, requested_at ASC);

CREATE INDEX IF NOT EXISTS idx_tg_update_requests_user_requested_at
    ON swingtrader.telegram_update_requests (user_id, requested_at DESC);

CREATE OR REPLACE FUNCTION swingtrader.touch_telegram_update_requests_updated_at()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_telegram_update_requests_updated_at ON swingtrader.telegram_update_requests;
CREATE TRIGGER trg_telegram_update_requests_updated_at
  BEFORE UPDATE ON swingtrader.telegram_update_requests
  FOR EACH ROW EXECUTE FUNCTION swingtrader.touch_telegram_update_requests_updated_at();

ALTER TABLE swingtrader.telegram_update_requests ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tg_update_requests_select_own ON swingtrader.telegram_update_requests;
CREATE POLICY tg_update_requests_select_own ON swingtrader.telegram_update_requests
    FOR SELECT TO authenticated USING (auth.uid() = user_id);

GRANT ALL ON swingtrader.telegram_update_requests TO service_role;
GRANT SELECT ON swingtrader.telegram_update_requests TO authenticated;
