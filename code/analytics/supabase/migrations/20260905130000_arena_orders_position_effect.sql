-- ---------------------------------------------------------------------------
-- arena_orders.position_effect — what a fill DID to the book
--
-- `side` alone stopped being readable the day every agent could short. A SELL
-- is either closing a long or opening a short; a BUY is either opening a long
-- or covering a short. The public order table rendered side as green/red, which
-- inverts the meaning for both short cases: a new bearish position showed in
-- the "exit" colour, and closing a bearish bet showed in the "entry" colour.
--
-- It cannot be inferred reliably after the fact either. `realized_pnl` is set
-- only on the portion of a fill that closes exposure, so side + realized_pnl
-- separates most cases — but not a fill that sells THROUGH zero, closing a long
-- and opening a short in one order, which broker.py explicitly supports and
-- which would be labelled a plain close.
--
-- The broker knows the answer at fill time (it has held, signed and resulting),
-- so it records it instead. Rows written before this migration stay NULL and
-- the UI falls back to showing the bare side, which is what it showed anyway —
-- a wrong label would be worse than an absent one.
-- ---------------------------------------------------------------------------

ALTER TABLE swingtrader.arena_orders
  ADD COLUMN IF NOT EXISTS position_effect TEXT;

ALTER TABLE swingtrader.arena_orders
  DROP CONSTRAINT IF EXISTS arena_orders_position_effect_chk;

ALTER TABLE swingtrader.arena_orders
  ADD CONSTRAINT arena_orders_position_effect_chk CHECK (
    position_effect IS NULL OR position_effect IN (
      'open_long',    -- buy, no position or adding to a long
      'close_long',   -- sell, reducing or closing a long
      'open_short',   -- sell, no position or adding to a short
      'cover_short',  -- buy, reducing or closing a short
      'flip_to_short',-- sell through zero: closed a long AND opened a short
      'flip_to_long'  -- buy through zero: covered a short AND opened a long
    )
  );

COMMENT ON COLUMN swingtrader.arena_orders.position_effect IS
  'What the fill did to the book. Recorded by broker.py at fill time because '
  'side alone is ambiguous once shorting is allowed, and the flip cases cannot '
  'be recovered from side + realized_pnl. NULL on rows written before '
  '2026-09-05 and on unfilled orders.';

-- Republish: the public view is what the /arena pages read. Dropped and
-- recreated rather than CREATE OR REPLACE, which cannot reorder or insert a
-- column, and re-granted because a DROP takes the grants with it.
DROP VIEW IF EXISTS swingtrader.arena_orders_public_v;
CREATE VIEW swingtrader.arena_orders_public_v AS
SELECT
  a.slug AS agent_slug,
  o.id, o.agent_id, o.championship_id, o.decision_id, o.ticker, o.side,
  o.quantity, o.status, o.reject_reason, o.thesis, o.conviction,
  o.stop_price, o.target_price, o.submitted_at, o.intended_for,
  o.filled_at, o.fill_price, o.notional,
  o.realized_pnl, o.realized_pct, o.is_backtest, o.position_effect
FROM swingtrader.arena_orders o
JOIN swingtrader.arena_agents a ON a.id = o.agent_id
WHERE a.is_published;

GRANT SELECT ON swingtrader.arena_orders_public_v TO anon, authenticated, service_role;
