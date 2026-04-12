-- Fix PL/pgSQL ambiguity: RETURNS TABLE column names (key_id, user_id, …) shadow
-- swingtrader.api_rate_limits.key_id in ON CONFLICT / DELETE, breaking RPC and
-- causing every API key lookup to error → clients see "Invalid API key".

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
    SELECT * INTO v_key
    FROM swingtrader.user_api_keys
    WHERE key_hash = p_key_hash
      AND revoked_at IS NULL
      AND (expires_at IS NULL OR expires_at > NOW());

    IF NOT FOUND THEN
        RETURN;
    END IF;

    UPDATE swingtrader.user_api_keys u
       SET last_used_at = NOW()
     WHERE u.id = v_key.id;

    v_window := date_trunc('minute', NOW());

    INSERT INTO swingtrader.api_rate_limits (key_id, window_start, request_count)
    VALUES (v_key.id, v_window, 1)
    ON CONFLICT ON CONSTRAINT api_rate_limits_pkey
    DO UPDATE SET request_count = swingtrader.api_rate_limits.request_count + EXCLUDED.request_count
    RETURNING request_count INTO v_count;

    DELETE FROM swingtrader.api_rate_limits a
     WHERE a.key_id = v_key.id
       AND a.window_start < NOW() - INTERVAL '2 hours';

    RETURN QUERY
    SELECT
        v_key.id,
        v_key.user_id,
        v_key.scopes,
        (v_count <= p_rate_limit_per_minute);
END;
$$;
