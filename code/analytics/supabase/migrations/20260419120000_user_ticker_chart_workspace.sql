-- Per-user chart workspace: annotations + Chart AI conversation, keyed by ticker.
-- Used by protected/charts; RLS restricts rows to the owning user.

CREATE TABLE IF NOT EXISTS swingtrader.user_ticker_chart_workspace (
    user_id          UUID        NOT NULL REFERENCES auth.users (id) ON DELETE CASCADE,
    ticker           VARCHAR(32) NOT NULL,
    annotations      JSONB       NOT NULL DEFAULT '[]'::JSONB,
    ai_chat_messages JSONB       NOT NULL DEFAULT '[]'::JSONB,
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, ticker)
);

CREATE INDEX IF NOT EXISTS idx_user_chart_workspace_user_updated
    ON swingtrader.user_ticker_chart_workspace (user_id, updated_at DESC);

CREATE OR REPLACE FUNCTION swingtrader.touch_user_ticker_chart_workspace_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_user_ticker_chart_workspace_updated_at
    ON swingtrader.user_ticker_chart_workspace;

CREATE TRIGGER trg_user_ticker_chart_workspace_updated_at
    BEFORE UPDATE ON swingtrader.user_ticker_chart_workspace
    FOR EACH ROW
    EXECUTE FUNCTION swingtrader.touch_user_ticker_chart_workspace_updated_at();

ALTER TABLE swingtrader.user_ticker_chart_workspace ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS user_chart_workspace_select_own ON swingtrader.user_ticker_chart_workspace;
CREATE POLICY user_chart_workspace_select_own
    ON swingtrader.user_ticker_chart_workspace
    FOR SELECT
    TO authenticated
    USING (auth.uid() = user_id);

DROP POLICY IF EXISTS user_chart_workspace_insert_own ON swingtrader.user_ticker_chart_workspace;
CREATE POLICY user_chart_workspace_insert_own
    ON swingtrader.user_ticker_chart_workspace
    FOR INSERT
    TO authenticated
    WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS user_chart_workspace_update_own ON swingtrader.user_ticker_chart_workspace;
CREATE POLICY user_chart_workspace_update_own
    ON swingtrader.user_ticker_chart_workspace
    FOR UPDATE
    TO authenticated
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS user_chart_workspace_delete_own ON swingtrader.user_ticker_chart_workspace;
CREATE POLICY user_chart_workspace_delete_own
    ON swingtrader.user_ticker_chart_workspace
    FOR DELETE
    TO authenticated
    USING (auth.uid() = user_id);

GRANT SELECT, INSERT, UPDATE, DELETE ON swingtrader.user_ticker_chart_workspace TO authenticated, service_role;
