-- ---------------------------------------------------------------------------
-- user_trades: add is_paper flag so users can track paper alongside real
-- trades and filter the portfolio view by book.
--
-- All existing rows default to false (real money) — safe backfill, no app
-- changes required for pre-existing trades.
-- ---------------------------------------------------------------------------

ALTER TABLE swingtrader.user_trades
    ADD COLUMN IF NOT EXISTS is_paper BOOLEAN NOT NULL DEFAULT FALSE;

-- Supports the (user_id, is_paper) filter the trades page uses to slice
-- the ledger into Real-only / Paper-only views, ordered by executed_at.
CREATE INDEX IF NOT EXISTS idx_user_trades_user_paper_executed
    ON swingtrader.user_trades (user_id, is_paper, executed_at DESC);
