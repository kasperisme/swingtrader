-- ---------------------------------------------------------------------------
-- user_trades: per-user trade ledger (buy/sell × long/short)
--
-- Semantics:
--   side            : 'buy' | 'sell' (execution direction)
--   position_side   : 'long' | 'short' (which side of the book)
-- Examples:
--   Open long:   buy  + long
--   Close long:  sell + long
--   Open short:  sell + short
--   Cover short: buy  + short
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS swingtrader.user_trades (
    id              BIGSERIAL PRIMARY KEY,
    user_id         UUID        NOT NULL REFERENCES auth.users (id) ON DELETE CASCADE,
    side            VARCHAR     NOT NULL CHECK (side IN ('buy', 'sell')),
    position_side   VARCHAR     NOT NULL CHECK (position_side IN ('long', 'short')),
    ticker          VARCHAR     NOT NULL,
    quantity        NUMERIC     NOT NULL CHECK (quantity > 0),
    price_per_unit  NUMERIC     NOT NULL CHECK (price_per_unit >= 0),
    currency        VARCHAR     NOT NULL DEFAULT 'USD',
    executed_at     TIMESTAMPTZ NOT NULL,
    broker          VARCHAR,
    account_label   VARCHAR,
    notes           TEXT,
    metadata_json   JSONB       NOT NULL DEFAULT '{}'::JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_user_trades_user_executed
    ON swingtrader.user_trades (user_id, executed_at DESC);

CREATE INDEX IF NOT EXISTS idx_user_trades_user_ticker
    ON swingtrader.user_trades (user_id, ticker);

CREATE OR REPLACE FUNCTION swingtrader.touch_user_trades_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_user_trades_updated_at ON swingtrader.user_trades;

CREATE TRIGGER trg_user_trades_updated_at
    BEFORE UPDATE ON swingtrader.user_trades
    FOR EACH ROW
    EXECUTE FUNCTION swingtrader.touch_user_trades_updated_at();

ALTER TABLE swingtrader.user_trades ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS user_trades_select_own ON swingtrader.user_trades;
CREATE POLICY user_trades_select_own
    ON swingtrader.user_trades
    FOR SELECT
    TO authenticated
    USING (auth.uid() = user_id);

DROP POLICY IF EXISTS user_trades_insert_own ON swingtrader.user_trades;
CREATE POLICY user_trades_insert_own
    ON swingtrader.user_trades
    FOR INSERT
    TO authenticated
    WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS user_trades_update_own ON swingtrader.user_trades;
CREATE POLICY user_trades_update_own
    ON swingtrader.user_trades
    FOR UPDATE
    TO authenticated
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS user_trades_delete_own ON swingtrader.user_trades;
CREATE POLICY user_trades_delete_own
    ON swingtrader.user_trades
    FOR DELETE
    TO authenticated
    USING (auth.uid() = user_id);

GRANT ALL ON swingtrader.user_trades TO anon, authenticated, service_role;
