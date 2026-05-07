-- ---------------------------------------------------------------------------
-- user_profiles
--
-- Per-user app state that doesn't belong in auth.users.user_metadata.
-- Designed to grow: free-form `metadata` jsonb for ad-hoc flags so adding a
-- new piece of profile state doesn't require a migration.
--
-- `welcomed_at` drives the first-login welcome dialog: NULL = show, set = skip.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS swingtrader.user_profiles (
    user_id      UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    welcomed_at  TIMESTAMPTZ,
    display_name TEXT,
    metadata     JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_user_profiles_welcomed_at
    ON swingtrader.user_profiles (welcomed_at);

ALTER TABLE swingtrader.user_profiles ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS user_profiles_select_self ON swingtrader.user_profiles;
CREATE POLICY user_profiles_select_self
    ON swingtrader.user_profiles
    FOR SELECT TO authenticated
    USING (user_id = auth.uid());

DROP POLICY IF EXISTS user_profiles_insert_self ON swingtrader.user_profiles;
CREATE POLICY user_profiles_insert_self
    ON swingtrader.user_profiles
    FOR INSERT TO authenticated
    WITH CHECK (user_id = auth.uid());

DROP POLICY IF EXISTS user_profiles_update_self ON swingtrader.user_profiles;
CREATE POLICY user_profiles_update_self
    ON swingtrader.user_profiles
    FOR UPDATE TO authenticated
    USING (user_id = auth.uid())
    WITH CHECK (user_id = auth.uid());

GRANT SELECT, INSERT, UPDATE ON TABLE swingtrader.user_profiles TO authenticated;
GRANT ALL ON TABLE swingtrader.user_profiles TO service_role;

CREATE OR REPLACE FUNCTION swingtrader.set_user_profiles_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS user_profiles_set_updated_at ON swingtrader.user_profiles;
CREATE TRIGGER user_profiles_set_updated_at
    BEFORE UPDATE ON swingtrader.user_profiles
    FOR EACH ROW
    EXECUTE FUNCTION swingtrader.set_user_profiles_updated_at();
