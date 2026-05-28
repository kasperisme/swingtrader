-- ---------------------------------------------------------------------------
-- user_trade_reviews: AI post-trade review chats keyed by the closing trade
--
-- A "review" lives on the trade row that flattens a position back to zero
-- (the closing fill). The position itself is derived client/server-side by
-- replaying user_trades; we just need a stable key (the closing trade id)
-- and a place to persist the chat + final AI summary so users can revisit.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS swingtrader.user_trade_reviews (
    id                  BIGSERIAL PRIMARY KEY,
    user_id             UUID        NOT NULL REFERENCES auth.users (id) ON DELETE CASCADE,
    closing_trade_id    BIGINT      NOT NULL REFERENCES swingtrader.user_trades (id) ON DELETE CASCADE,
    ticker              VARCHAR     NOT NULL,
    -- Frozen snapshot of the derived position at the time the review was
    -- created (side, qty, avgEntry, avgExit, openedAt, closedAt, realizedPnl,
    -- holdingDays, openTradeIds, closeTradeIds). Lets the review survive even
    -- if the underlying trade rows are later edited.
    position_snapshot   JSONB       NOT NULL,
    -- Chat history: [{role, content, chartAnnotations?, personaReports?}].
    messages            JSONB       NOT NULL DEFAULT '[]'::JSONB,
    -- AI-generated final summary of the review.
    summary             TEXT,
    -- Persona scores from the orchestrator's final pass:
    -- {execution: 0-100, timing: 0-100, risk_mgmt: 0-100, lesson: 0-100}
    scores              JSONB,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, closing_trade_id)
);

CREATE INDEX IF NOT EXISTS idx_user_trade_reviews_user_created
    ON swingtrader.user_trade_reviews (user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_user_trade_reviews_user_ticker
    ON swingtrader.user_trade_reviews (user_id, ticker);

CREATE OR REPLACE FUNCTION swingtrader.touch_user_trade_reviews_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_user_trade_reviews_updated_at ON swingtrader.user_trade_reviews;

CREATE TRIGGER trg_user_trade_reviews_updated_at
    BEFORE UPDATE ON swingtrader.user_trade_reviews
    FOR EACH ROW
    EXECUTE FUNCTION swingtrader.touch_user_trade_reviews_updated_at();

ALTER TABLE swingtrader.user_trade_reviews ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS user_trade_reviews_select_own ON swingtrader.user_trade_reviews;
CREATE POLICY user_trade_reviews_select_own
    ON swingtrader.user_trade_reviews
    FOR SELECT
    TO authenticated
    USING (auth.uid() = user_id);

DROP POLICY IF EXISTS user_trade_reviews_insert_own ON swingtrader.user_trade_reviews;
CREATE POLICY user_trade_reviews_insert_own
    ON swingtrader.user_trade_reviews
    FOR INSERT
    TO authenticated
    WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS user_trade_reviews_update_own ON swingtrader.user_trade_reviews;
CREATE POLICY user_trade_reviews_update_own
    ON swingtrader.user_trade_reviews
    FOR UPDATE
    TO authenticated
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS user_trade_reviews_delete_own ON swingtrader.user_trade_reviews;
CREATE POLICY user_trade_reviews_delete_own
    ON swingtrader.user_trade_reviews
    FOR DELETE
    TO authenticated
    USING (auth.uid() = user_id);

GRANT ALL ON swingtrader.user_trade_reviews TO anon, authenticated, service_role;
