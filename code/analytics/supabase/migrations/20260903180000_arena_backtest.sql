-- ---------------------------------------------------------------------------
-- Arena: mark replayed rows as simulation, not record
--
-- Why:
-- - The arena can be REPLAYED over past sessions (services/arena/backtest.py) to
--   populate a curve rather than waiting months for one to accumulate. Those
--   rows sit in the same tables as live trading, on one continuous curve per
--   agent, which is what makes the leaderboard readable — and exactly why they
--   have to be distinguishable.
--
-- - The distinction is not cosmetic. A replay runs the agents' research tools
--   against TODAY's data while pretending to be a past session, so a replayed
--   decision had access to information that did not exist when it claims to have
--   traded. The prices are honest (each session's own open and close), the
--   reasoning is not. A replayed return is a demonstration that the machinery
--   works end to end; it is NOT evidence that an approach makes money, and
--   anything that publishes it has to say so.
--
-- `backtest_run_id` groups one replay so a bad run can be identified and
-- removed wholesale without touching live rows.
-- ---------------------------------------------------------------------------

ALTER TABLE swingtrader.arena_nav_history
  ADD COLUMN IF NOT EXISTS is_backtest BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS backtest_run_id UUID;

ALTER TABLE swingtrader.arena_orders
  ADD COLUMN IF NOT EXISTS is_backtest BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS backtest_run_id UUID;

ALTER TABLE swingtrader.arena_decisions
  ADD COLUMN IF NOT EXISTS is_backtest BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS backtest_run_id UUID;

COMMENT ON COLUMN swingtrader.arena_nav_history.is_backtest IS
  'Row produced by a historical replay, not by live trading. Prices are point-in-time; the agent research behind it was not.';

CREATE INDEX IF NOT EXISTS idx_arena_nav_backtest
  ON swingtrader.arena_nav_history (backtest_run_id) WHERE backtest_run_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_arena_orders_backtest
  ON swingtrader.arena_orders (backtest_run_id) WHERE backtest_run_id IS NOT NULL;

-- ── Public views: carry the flag through ────────────────────────────────────
-- The page needs it to draw the cutover between the replayed segment and live
-- trading. Views are recreated wholesale (CREATE OR REPLACE cannot add a column
-- in the middle of an existing view definition).

DROP VIEW IF EXISTS swingtrader.arena_nav_history_public_v;
CREATE VIEW swingtrader.arena_nav_history_public_v AS
SELECT
  a.slug AS agent_slug,
  n.agent_id, n.as_of, n.nav, n.cash, n.long_value, n.short_value,
  n.n_positions, n.daily_return, n.cumulative_return, n.drawdown,
  n.is_backtest
FROM swingtrader.arena_nav_history n
JOIN swingtrader.arena_agents a ON a.id = n.agent_id
WHERE a.is_published;

DROP VIEW IF EXISTS swingtrader.arena_orders_public_v;
CREATE VIEW swingtrader.arena_orders_public_v AS
SELECT
  a.slug AS agent_slug,
  o.id, o.agent_id, o.decision_id, o.ticker, o.side, o.quantity, o.status,
  o.reject_reason, o.thesis, o.conviction, o.stop_price, o.target_price,
  o.submitted_at, o.intended_for, o.filled_at, o.fill_price, o.notional,
  o.realized_pnl, o.realized_pct,
  o.is_backtest
FROM swingtrader.arena_orders o
JOIN swingtrader.arena_agents a ON a.id = o.agent_id
WHERE a.is_published;

DROP VIEW IF EXISTS swingtrader.arena_decisions_public_v;
CREATE VIEW swingtrader.arena_decisions_public_v AS
SELECT
  a.slug AS agent_slug,
  d.id, d.agent_id, d.decision_date, d.status, d.narrative,
  d.rounds_used, d.tools_called,
  d.orders_requested, d.orders_accepted, d.orders_rejected,
  d.nav_at_decision, d.cash_at_decision, d.duration_ms, d.finished_at,
  d.is_backtest
FROM swingtrader.arena_decisions d
JOIN swingtrader.arena_agents a ON a.id = d.agent_id
WHERE a.is_published AND d.status IN ('ok', 'skipped');

-- The leaderboard gains a `backtest_days` count so the page can say how much of
-- an agent's curve is simulated instead of implying it is all live record.
DROP VIEW IF EXISTS swingtrader.arena_leaderboard_v;
CREATE VIEW swingtrader.arena_leaderboard_v AS
WITH latest AS (
  SELECT DISTINCT ON (n.agent_id)
    n.agent_id, n.as_of, n.nav, n.cash, n.long_value, n.short_value,
    n.n_positions, n.daily_return, n.cumulative_return, n.drawdown
  FROM swingtrader.arena_nav_history n
  ORDER BY n.agent_id, n.as_of DESC
),
curve AS (
  SELECT
    n.agent_id,
    COUNT(*)                                  AS nav_days,
    MIN(n.drawdown)                           AS max_drawdown,
    AVG(n.daily_return)                       AS mean_daily_return,
    STDDEV_SAMP(n.daily_return)               AS stdev_daily_return
  FROM swingtrader.arena_nav_history n
  WHERE n.daily_return IS NOT NULL
  GROUP BY n.agent_id
),
sim AS (
  SELECT n.agent_id,
         COUNT(*) FILTER (WHERE n.is_backtest)     AS backtest_days,
         MAX(n.as_of) FILTER (WHERE n.is_backtest) AS backtest_through
  FROM swingtrader.arena_nav_history n
  GROUP BY n.agent_id
),
closes AS (
  SELECT
    o.agent_id,
    COUNT(*)                                            AS closed_trades,
    COUNT(*) FILTER (WHERE o.realized_pnl > 0)          AS winning_trades,
    SUM(o.realized_pnl)                                 AS realized_pnl,
    AVG(o.realized_pct)                                 AS avg_realized_pct
  FROM swingtrader.arena_orders o
  WHERE o.status = 'filled' AND o.realized_pnl IS NOT NULL
  GROUP BY o.agent_id
),
fills AS (
  SELECT o.agent_id, COUNT(*) AS filled_orders
  FROM swingtrader.arena_orders o
  WHERE o.status = 'filled'
  GROUP BY o.agent_id
)
SELECT
  a.id,
  a.slug,
  a.name,
  a.tagline,
  a.engine,
  a.sort_order,
  a.starting_cash,
  a.funded_on,
  l.as_of                                   AS as_of,
  l.nav,
  l.cash,
  l.long_value,
  l.short_value,
  l.n_positions,
  l.daily_return,
  l.cumulative_return                       AS total_return,
  c.max_drawdown,
  c.nav_days,
  CASE
    WHEN c.stdev_daily_return IS NULL OR c.stdev_daily_return = 0 OR c.nav_days < 20
      THEN NULL
    ELSE (c.mean_daily_return / c.stdev_daily_return) * SQRT(252)
  END                                       AS sharpe,
  COALESCE(s.backtest_days, 0)              AS backtest_days,
  s.backtest_through,
  COALESCE(f.filled_orders, 0)              AS filled_orders,
  COALESCE(cl.closed_trades, 0)             AS closed_trades,
  COALESCE(cl.winning_trades, 0)            AS winning_trades,
  CASE WHEN COALESCE(cl.closed_trades, 0) > 0
       THEN cl.winning_trades::NUMERIC / cl.closed_trades
       ELSE NULL END                        AS win_rate,
  cl.realized_pnl,
  cl.avg_realized_pct
FROM swingtrader.arena_agents a
LEFT JOIN latest l  ON l.agent_id  = a.id
LEFT JOIN curve  c  ON c.agent_id  = a.id
LEFT JOIN sim    s  ON s.agent_id  = a.id
LEFT JOIN closes cl ON cl.agent_id = a.id
LEFT JOIN fills  f  ON f.agent_id  = a.id
WHERE a.is_published;

GRANT SELECT ON swingtrader.arena_leaderboard_v          TO anon, authenticated, service_role;
GRANT SELECT ON swingtrader.arena_nav_history_public_v   TO anon, authenticated, service_role;
GRANT SELECT ON swingtrader.arena_orders_public_v        TO anon, authenticated, service_role;
GRANT SELECT ON swingtrader.arena_decisions_public_v     TO anon, authenticated, service_role;
