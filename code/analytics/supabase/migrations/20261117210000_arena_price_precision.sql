-- ---------------------------------------------------------------------------
-- arena: store per-share prices at full precision
--
-- avg_cost, last_price, fill_price and reference_price were NUMERIC(18,4), and
-- broker.py/store.py rounded to 4 decimals before writing. That is a rounding
-- error of up to 0.00005 per share — invisible on a $30 stock, and a third of
-- the price on a sub-penny one. Agents may short sub-penny names (no minimum
-- price, by design), and Jim Chaos held 20,283,961 CBIH short at ~$0.00015:
--
--   * last_price stored as 0.0001, so the public positions view valued the
--     buy-back at $2,028 when the true figure was $3,043, $1,014 off the NAV;
--   * avg_cost stored as 0.0002 (true 0.00019990), so unrealised P&L read
--     +50% instead of +25% — and the next fill reloads the ROUNDED cost, so a
--     cover would have booked the wrong realised P&L.
--
-- Cash and NAV were never affected: the broker computes them from the exact
-- fill and mark prices in memory. Only the stored copies were rounded.
--
-- Fix: unconstrained NUMERIC on the four price columns (quantity keeps 4dp —
-- shares, not prices). The two public views depending on them are dropped and
-- recreated unchanged, with their SELECT grants restored.
--
-- Backfill: an open position whose cost is sub-penny and that came from ONE
-- opening fill gets its exact cost back from that fill's notional (stored to
-- the cent: $4,054.76 / 20,283,961 sh is exact to ~1e-6 relative). Its mark is
-- recovered from the latest NAV snapshot's market_value / quantity. Filled
-- orders are immutable (trg_arena_orders_immutable), so their fill_price keeps
-- the rounded value; `notional` on those rows is the exact record.
-- ---------------------------------------------------------------------------

DROP VIEW IF EXISTS swingtrader.arena_positions_public_v;
DROP VIEW IF EXISTS swingtrader.arena_orders_public_v;

ALTER TABLE swingtrader.arena_positions
  ALTER COLUMN avg_cost   TYPE NUMERIC,
  ALTER COLUMN last_price TYPE NUMERIC;

ALTER TABLE swingtrader.arena_orders
  ALTER COLUMN fill_price      TYPE NUMERIC,
  ALTER COLUMN reference_price TYPE NUMERIC;

CREATE VIEW swingtrader.arena_positions_public_v AS
SELECT a.slug AS agent_slug,
       p.agent_id,
       p.championship_id,
       p.ticker,
       p.quantity,
       p.avg_cost,
       p.last_price,
       p.marked_at,
       p.opened_at,
       p.quantity * COALESCE(p.last_price, p.avg_cost)                   AS market_value,
       p.quantity * (COALESCE(p.last_price, p.avg_cost) - p.avg_cost)    AS unrealized_pnl,
       CASE
         WHEN p.avg_cost > 0::numeric
           THEN sign(p.quantity) * (COALESCE(p.last_price, p.avg_cost) - p.avg_cost) / p.avg_cost
         ELSE NULL::numeric
       END                                                               AS unrealized_pct
FROM swingtrader.arena_positions p
JOIN swingtrader.arena_agents a ON a.id = p.agent_id
WHERE a.is_published;

CREATE VIEW swingtrader.arena_orders_public_v AS
SELECT a.slug AS agent_slug,
       o.id,
       o.agent_id,
       o.championship_id,
       o.decision_id,
       o.ticker,
       o.side,
       o.quantity,
       o.status,
       o.reject_reason,
       o.thesis,
       o.conviction,
       o.stop_price,
       o.target_price,
       o.submitted_at,
       o.intended_for,
       o.filled_at,
       o.fill_price,
       o.notional,
       o.realized_pnl,
       o.realized_pct,
       o.is_backtest,
       o.position_effect
FROM swingtrader.arena_orders o
JOIN swingtrader.arena_agents a ON a.id = o.agent_id
WHERE a.is_published;

GRANT SELECT ON swingtrader.arena_positions_public_v TO anon, authenticated, service_role;
GRANT SELECT ON swingtrader.arena_orders_public_v    TO anon, authenticated, service_role;

-- Backfill avg_cost: sub-penny positions built from exactly one opening fill.
WITH single_fill AS (
  SELECT o.agent_id, o.championship_id, o.ticker,
         min(abs(o.notional) / o.quantity) AS exact_price,
         min(o.quantity)                   AS qty
  FROM swingtrader.arena_orders o
  WHERE o.status = 'filled'
  GROUP BY o.agent_id, o.championship_id, o.ticker
  HAVING count(*) = 1
     AND bool_and(o.position_effect IN ('open_long', 'open_short'))
)
UPDATE swingtrader.arena_positions p
SET avg_cost = f.exact_price
FROM single_fill f
WHERE p.agent_id = f.agent_id
  AND p.championship_id = f.championship_id
  AND p.ticker = f.ticker
  AND abs(p.quantity) = f.qty
  AND p.avg_cost < 0.01;

-- Backfill last_price: the latest NAV snapshot's exact market value / quantity.
WITH latest AS (
  SELECT DISTINCT ON (n.agent_id, n.championship_id)
         n.agent_id, n.championship_id, n.positions
  FROM swingtrader.arena_nav_history n
  WHERE NOT n.is_backtest
  ORDER BY n.agent_id, n.championship_id, n.as_of DESC
), holdings AS (
  SELECT l.agent_id, l.championship_id,
         h->>'ticker'                                          AS ticker,
         (h->>'market_value')::numeric / (h->>'quantity')::numeric AS exact_mark,
         (h->>'quantity')::numeric                             AS qty
  FROM latest l
  CROSS JOIN LATERAL jsonb_array_elements(l.positions->'holdings') h
)
UPDATE swingtrader.arena_positions p
SET last_price = h.exact_mark
FROM holdings h
WHERE p.agent_id = h.agent_id
  AND p.championship_id = h.championship_id
  AND p.ticker = h.ticker
  AND p.quantity = h.qty
  AND p.last_price < 0.01;
