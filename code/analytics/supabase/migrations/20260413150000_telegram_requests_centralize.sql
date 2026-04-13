-- ---------------------------------------------------------------------------
-- Centralize telegram requests queue for multiple commands.
-- Extends existing telegram_update_requests to support /update and /search.
-- ---------------------------------------------------------------------------

ALTER TABLE swingtrader.telegram_update_requests
    ADD COLUMN IF NOT EXISTS request_type VARCHAR NOT NULL DEFAULT 'update',
    ADD COLUMN IF NOT EXISTS request_text TEXT;

ALTER TABLE swingtrader.telegram_update_requests
    DROP CONSTRAINT IF EXISTS telegram_update_requests_request_type_check;

ALTER TABLE swingtrader.telegram_update_requests
    ADD CONSTRAINT telegram_update_requests_request_type_check
    CHECK (request_type IN ('update', 'search'));

CREATE INDEX IF NOT EXISTS idx_tg_update_requests_type_status_requested_at
    ON swingtrader.telegram_update_requests (request_type, status, requested_at ASC);
