-- ---------------------------------------------------------------------------
-- user_api_keys: per-user API keys for programmatic access to the public API.
-- api_rate_limits: per-key per-minute request counters.
--
-- Key lifecycle:
--   1. User creates a key via the dashboard → SHA-256 hash + display prefix stored.
--   2. API caller sends: Authorization: Bearer <raw_key>
--   3. Server hashes the raw key and calls validate_api_key() which:
--        - Verifies hash exists, not revoked, not expired
--        - Atomically increments the rate-limit bucket for the current minute
--        - Returns user_id, scopes, rate_ok
--
-- Rate limit: 60 requests per minute per key (configurable via function arg).
-- Per-user limit: max 10 active keys.
-- ---------------------------------------------------------------------------

-- ---------------------------------------------------------------------------
-- user_api_keys
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS swingtrader.user_api_keys (
    id           UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id      UUID         NOT NULL REFERENCES auth.users (id) ON DELETE CASCADE,
    name         VARCHAR(100) NOT NULL,
    key_hash     TEXT         NOT NULL UNIQUE,  -- SHA-256 hex of the raw key
    key_prefix   VARCHAR(24)  NOT NULL,         -- e.g. "st_live_a1b2c3d4…"
    scopes       TEXT[]       NOT NULL DEFAULT '{news:read}'::TEXT[],
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    last_used_at TIMESTAMPTZ,
    expires_at   TIMESTAMPTZ,
    revoked_at   TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_user_api_keys_user_id
    ON swingtrader.user_api_keys (user_id);
CREATE INDEX IF NOT EXISTS idx_user_api_keys_key_hash
    ON swingtrader.user_api_keys (key_hash);

ALTER TABLE swingtrader.user_api_keys ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS user_api_keys_select_own ON swingtrader.user_api_keys;
CREATE POLICY user_api_keys_select_own ON swingtrader.user_api_keys
    FOR SELECT TO authenticated USING (auth.uid() = user_id);

DROP POLICY IF EXISTS user_api_keys_insert_own ON swingtrader.user_api_keys;
CREATE POLICY user_api_keys_insert_own ON swingtrader.user_api_keys
    FOR INSERT TO authenticated WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS user_api_keys_update_own ON swingtrader.user_api_keys;
CREATE POLICY user_api_keys_update_own ON swingtrader.user_api_keys
    FOR UPDATE TO authenticated USING (auth.uid() = user_id);

DROP POLICY IF EXISTS user_api_keys_delete_own ON swingtrader.user_api_keys;
CREATE POLICY user_api_keys_delete_own ON swingtrader.user_api_keys
    FOR DELETE TO authenticated USING (auth.uid() = user_id);

GRANT ALL ON swingtrader.user_api_keys TO service_role;
GRANT SELECT, INSERT, UPDATE ON swingtrader.user_api_keys TO authenticated;

-- ---------------------------------------------------------------------------
-- api_rate_limits: 1-minute sliding window buckets
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS swingtrader.api_rate_limits (
    key_id        UUID        NOT NULL REFERENCES swingtrader.user_api_keys (id) ON DELETE CASCADE,
    window_start  TIMESTAMPTZ NOT NULL,
    request_count INTEGER     NOT NULL DEFAULT 1,
    PRIMARY KEY (key_id, window_start)
);

CREATE INDEX IF NOT EXISTS idx_api_rate_limits_window
    ON swingtrader.api_rate_limits (window_start);

GRANT ALL ON swingtrader.api_rate_limits TO service_role;

-- ---------------------------------------------------------------------------
-- FK: news_impact_heads.article_id → news_articles.id
-- (missing from initial schema; enables PostgREST auto-joins)
-- ---------------------------------------------------------------------------
ALTER TABLE swingtrader.news_impact_heads
    DROP CONSTRAINT IF EXISTS fk_news_impact_heads_article;

ALTER TABLE swingtrader.news_impact_heads
    ADD CONSTRAINT fk_news_impact_heads_article
        FOREIGN KEY (article_id) REFERENCES swingtrader.news_articles (id)
        ON DELETE CASCADE;

-- ---------------------------------------------------------------------------
-- validate_api_key()
--
-- Atomically:
--   1. Looks up key by SHA-256 hash; returns nothing if invalid/revoked/expired.
--   2. Stamps last_used_at.
--   3. Upserts the rate-limit bucket for the current minute window.
--   4. Purges stale buckets (>2 h) for this key.
--
-- Returns (key_id, user_id, scopes, rate_ok).
-- rate_ok = false → caller should respond HTTP 429.
--
-- SECURITY DEFINER so the public API (service_role) can call it without
-- exposing the underlying tables directly. anon/authenticated are revoked.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION swingtrader.validate_api_key(
    p_key_hash              TEXT,
    p_rate_limit_per_minute INTEGER DEFAULT 60
)
RETURNS TABLE (
    key_id  UUID,
    user_id UUID,
    scopes  TEXT[],
    rate_ok BOOLEAN
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = swingtrader, public
AS $$
DECLARE
    v_key    swingtrader.user_api_keys%ROWTYPE;
    v_window TIMESTAMPTZ;
    v_count  INTEGER;
BEGIN
    -- 1. Look up key; reject if not found, revoked, or expired
    SELECT * INTO v_key
    FROM swingtrader.user_api_keys
    WHERE key_hash = p_key_hash
      AND revoked_at IS NULL
      AND (expires_at IS NULL OR expires_at > NOW());

    IF NOT FOUND THEN
        RETURN;  -- empty result set signals "invalid key"
    END IF;

    -- 2. Stamp last_used_at (best-effort; concurrent races are acceptable)
    UPDATE swingtrader.user_api_keys
       SET last_used_at = NOW()
     WHERE id = v_key.id;

    -- 3. Atomic rate-limit increment for the current 1-minute bucket
    v_window := date_trunc('minute', NOW());

    INSERT INTO swingtrader.api_rate_limits (key_id, window_start, request_count)
    VALUES (v_key.id, v_window, 1)
    ON CONFLICT (key_id, window_start)
    DO UPDATE SET request_count = swingtrader.api_rate_limits.request_count + 1
    RETURNING request_count INTO v_count;

    -- 4. Best-effort cleanup of buckets older than 2 hours for this key
    DELETE FROM swingtrader.api_rate_limits
     WHERE key_id = v_key.id
       AND window_start < NOW() - INTERVAL '2 hours';

    -- 5. Return result
    RETURN QUERY
    SELECT
        v_key.id,
        v_key.user_id,
        v_key.scopes,
        (v_count <= p_rate_limit_per_minute);
END;
$$;

-- Restrict execution: only service_role may call this function
REVOKE ALL ON FUNCTION swingtrader.validate_api_key(TEXT, INTEGER)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION swingtrader.validate_api_key(TEXT, INTEGER)
    TO service_role;
