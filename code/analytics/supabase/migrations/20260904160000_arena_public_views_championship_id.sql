-- ---------------------------------------------------------------------------
-- arena public views: expose championship_id
--
-- The championships migration added `championship_id` to the base tables but
-- did not add it to the public views. The UI then scoped its reads by that
-- column, so every query failed with 42703 — and because the server actions
-- catch errors and return an empty array, the failure surfaced as "No sessions
-- marked yet" on charts for agents that had 46 sessions of history.
--
-- Silent-empty is the worst failure shape available here: a broken query and a
-- genuinely new agent look identical on the page. The columns are added to all
-- four views, not just the NAV one, so per-championship scoping is available
-- everywhere rather than only where it happened to be needed first.
-- ---------------------------------------------------------------------------

DROP VIEW IF EXISTS swingtrader.arena_nav_history_public_v;
CREATE VIEW swingtrader.arena_nav_history_public_v AS
SELECT
  a.slug AS agent_slug,
  n.agent_id, n.championship_id, n.as_of, n.nav, n.cash,
  n.long_value, n.short_value, n.n_positions,
  n.daily_return, n.cumulative_return, n.drawdown, n.is_backtest,
  -- The book as it stood at this close, so the site can show the portfolio for
  -- a selected day rather than only the live one.
  n.positions
FROM swingtrader.arena_nav_history n
JOIN swingtrader.arena_agents a ON a.id = n.agent_id
WHERE a.is_published;

DROP VIEW IF EXISTS swingtrader.arena_orders_public_v;
CREATE VIEW swingtrader.arena_orders_public_v AS
SELECT
  a.slug AS agent_slug,
  o.id, o.agent_id, o.championship_id, o.decision_id, o.ticker, o.side,
  o.quantity, o.status, o.reject_reason, o.thesis, o.conviction,
  o.stop_price, o.target_price, o.submitted_at, o.intended_for,
  o.filled_at, o.fill_price, o.notional,
  o.realized_pnl, o.realized_pct, o.is_backtest
FROM swingtrader.arena_orders o
JOIN swingtrader.arena_agents a ON a.id = o.agent_id
WHERE a.is_published;

DROP VIEW IF EXISTS swingtrader.arena_decisions_public_v;
CREATE VIEW swingtrader.arena_decisions_public_v AS
SELECT
  a.slug AS agent_slug,
  d.id, d.agent_id, d.championship_id, d.decision_date, d.status, d.narrative,
  d.rounds_used, d.tools_called, d.resources,
  d.orders_requested, d.orders_accepted, d.orders_rejected,
  d.nav_at_decision, d.cash_at_decision, d.duration_ms, d.finished_at,
  d.is_backtest
FROM swingtrader.arena_decisions d
JOIN swingtrader.arena_agents a ON a.id = d.agent_id
WHERE a.is_published AND d.status IN ('ok', 'skipped');

DROP VIEW IF EXISTS swingtrader.arena_positions_public_v;
CREATE VIEW swingtrader.arena_positions_public_v AS
SELECT
  a.slug AS agent_slug,
  p.agent_id, p.championship_id, p.ticker, p.quantity, p.avg_cost,
  p.last_price, p.marked_at, p.opened_at,
  (p.quantity * COALESCE(p.last_price, p.avg_cost))                    AS market_value,
  (p.quantity * (COALESCE(p.last_price, p.avg_cost) - p.avg_cost))     AS unrealized_pnl,
  CASE WHEN p.avg_cost > 0
       THEN SIGN(p.quantity) * (COALESCE(p.last_price, p.avg_cost) - p.avg_cost) / p.avg_cost
       ELSE NULL END                                                   AS unrealized_pct
FROM swingtrader.arena_positions p
JOIN swingtrader.arena_agents a ON a.id = p.agent_id
WHERE a.is_published;

GRANT SELECT ON swingtrader.arena_nav_history_public_v TO anon, authenticated, service_role;
GRANT SELECT ON swingtrader.arena_orders_public_v      TO anon, authenticated, service_role;
GRANT SELECT ON swingtrader.arena_decisions_public_v   TO anon, authenticated, service_role;
GRANT SELECT ON swingtrader.arena_positions_public_v   TO anon, authenticated, service_role;
