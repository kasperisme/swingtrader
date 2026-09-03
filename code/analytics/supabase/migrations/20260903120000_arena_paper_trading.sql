-- ---------------------------------------------------------------------------
-- Arena: competing AI paper-trading agents
--
-- What:
-- - A set of autonomous agents, each funded with the same starting cash, each
--   restricted to a DIFFERENT slice of the platform's data (news impact scores,
--   the priced-in decomposition, the NIS Momentum screenings, FMP fundamentals,
--   the relationship graph, pair z-scores, sentiment trends), trading against
--   each other on a daily clock. The point is not to make money — it is to make
--   the comparison between approaches falsifiable and public.
--
-- Why the accounting lives here and not in the model:
-- - The LLM's only write is an ORDER INTENT (arena_orders). Cash, positions and
--   NAV are computed by deterministic Python (services/arena/broker.py) against
--   these tables. A model cannot mark its own book, cannot spend cash it does
--   not have, and cannot revise a fill after the fact. Every rejection is stored
--   with its reason, because "the agent tried to do something illegal" is data.
--
-- Why two deterministic controls (index / coinflip):
-- - A leaderboard of seven LLM strategies with nothing to beat is a ranking, not
--   a result. `index` (buy the benchmark on day one, hold) and `coinflip`
--   (uniformly random picks under identical risk limits) are non-LLM agents
--   carried through the exact same broker, so any claim that an approach "works"
--   has to clear them first.
--
-- Clocks:
--   - Decision (daily, after the close): each agent runs its tool loop and emits
--     order intents for the next session      -> services/arena/cli.py decide
--   - Fill (daily, after the open): pending orders fill at the session open with
--     modelled slippage                       -> services/arena/cli.py fill
--   - Mark (daily, after the close): positions marked to close, NAV snapshotted
--                                             -> services/arena/cli.py mark
--
-- Positions use SIGNED quantity: > 0 long, < 0 short. One row per (agent,
-- ticker); a position that returns to zero is deleted, and its realised P&L
-- lives on the closing order.
-- ---------------------------------------------------------------------------

-- ── 1) The competitors ──────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS swingtrader.arena_agents (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  slug TEXT NOT NULL UNIQUE,                    -- url key, e.g. 'headline-hunter'
  name TEXT NOT NULL,                           -- display name
  tagline TEXT,                                 -- one line, public
  approach TEXT,                                -- the thesis, public (markdown)

  -- Which Python strategy definition backs this row. Must match a key in
  -- services/arena/roster.py; the runner refuses to run an unknown key rather
  -- than silently falling back to a default strategy.
  strategy_key TEXT NOT NULL,

  -- Execution model: 'llm' runs the tool loop, 'deterministic' runs pure Python
  -- (the index / coinflip controls). Deterministic agents never call Ollama.
  engine TEXT NOT NULL DEFAULT 'llm'
    CHECK (engine IN ('llm', 'deterministic')),

  llm_backend TEXT NOT NULL DEFAULT 'ollama',
  llm_model TEXT,                               -- NULL -> service default
  max_tool_rounds INTEGER NOT NULL DEFAULT 12,

  -- Risk limits. Enforced by the broker on every order, NOT by the prompt: a
  -- model that asks for 90% of NAV in one name gets a rejection it can read.
  starting_cash NUMERIC(18,2) NOT NULL DEFAULT 100000,
  max_position_pct NUMERIC(6,4) NOT NULL DEFAULT 0.20,   -- of NAV, per ticker
  max_positions INTEGER NOT NULL DEFAULT 10,
  max_gross_exposure_pct NUMERIC(6,4) NOT NULL DEFAULT 1.00,
  allow_shorts BOOLEAN NOT NULL DEFAULT FALSE,

  is_active BOOLEAN NOT NULL DEFAULT TRUE,      -- runs on the daily tick
  is_published BOOLEAN NOT NULL DEFAULT FALSE,  -- visible on /arena
  funded_on DATE,                               -- first day it held the cash
  sort_order INTEGER NOT NULL DEFAULT 0,

  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE swingtrader.arena_agents IS
  'Competing paper-trading agents. One row per approach; risk limits are broker-enforced.';

-- ── 2) The decision record ──────────────────────────────────────────────────
-- One row per agent per trading day. This is the public "why" — the narrative
-- the agent gives for what it did, alongside the machine trace (which tools it
-- called, how many rounds, how long) so a bad day can be diagnosed.

CREATE TABLE IF NOT EXISTS swingtrader.arena_decisions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  agent_id UUID NOT NULL REFERENCES swingtrader.arena_agents(id) ON DELETE CASCADE,
  decision_date DATE NOT NULL,                  -- the session the agent decided FOR

  status TEXT NOT NULL DEFAULT 'running'
    CHECK (status IN ('running', 'ok', 'error', 'skipped')),
  narrative TEXT,                               -- public: what it saw and why
  error TEXT,

  -- Trace
  llm_model TEXT,
  rounds_used INTEGER,
  tools_called JSONB,                           -- {tool_name: call_count}
  orders_requested INTEGER NOT NULL DEFAULT 0,
  orders_accepted INTEGER NOT NULL DEFAULT 0,
  orders_rejected INTEGER NOT NULL DEFAULT 0,

  -- Book at decision time, so the narrative can be read against what it held
  nav_at_decision NUMERIC(18,2),
  cash_at_decision NUMERIC(18,2),

  started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  finished_at TIMESTAMPTZ,
  duration_ms INTEGER,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

  UNIQUE (agent_id, decision_date)
);

CREATE INDEX IF NOT EXISTS idx_arena_decisions_agent_date
  ON swingtrader.arena_decisions (agent_id, decision_date DESC);

-- ── 3) Orders — the only thing an agent writes ──────────────────────────────
-- An order is an INTENT until the fill pass runs. `status` walks
-- pending -> filled | rejected | cancelled. Rejections keep their reason.

CREATE TABLE IF NOT EXISTS swingtrader.arena_orders (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  agent_id UUID NOT NULL REFERENCES swingtrader.arena_agents(id) ON DELETE CASCADE,
  decision_id UUID REFERENCES swingtrader.arena_decisions(id) ON DELETE SET NULL,

  ticker TEXT NOT NULL,
  side TEXT NOT NULL CHECK (side IN ('buy', 'sell')),
  quantity NUMERIC(18,4) NOT NULL CHECK (quantity > 0),

  status TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending', 'filled', 'rejected', 'cancelled')),
  reject_reason TEXT,                           -- why the broker refused it

  -- The agent's stated case. Public — this is the interesting part.
  thesis TEXT,
  conviction NUMERIC(4,3) CHECK (conviction IS NULL OR (conviction >= 0 AND conviction <= 1)),
  stop_price NUMERIC(18,4),
  target_price NUMERIC(18,4),

  -- Execution
  submitted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  intended_for DATE,                            -- session it should fill in
  filled_at TIMESTAMPTZ,
  fill_price NUMERIC(18,4),                     -- includes modelled slippage
  reference_price NUMERIC(18,4),                -- session open before slippage
  slippage_bps NUMERIC(8,3),
  commission NUMERIC(12,4) NOT NULL DEFAULT 0,
  notional NUMERIC(18,2),                       -- signed cash effect of the fill

  -- Realised P&L, set only on the portion of a fill that CLOSES exposure.
  -- Opening fills carry NULL, so win-rate is computed over closes only.
  realized_pnl NUMERIC(18,2),
  realized_pct NUMERIC(10,6),

  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_arena_orders_agent_status
  ON swingtrader.arena_orders (agent_id, status, intended_for);
CREATE INDEX IF NOT EXISTS idx_arena_orders_pending
  ON swingtrader.arena_orders (intended_for) WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_arena_orders_agent_filled
  ON swingtrader.arena_orders (agent_id, filled_at DESC) WHERE status = 'filled';

-- ── 4) Positions — current book, one row per (agent, ticker) ────────────────

CREATE TABLE IF NOT EXISTS swingtrader.arena_positions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  agent_id UUID NOT NULL REFERENCES swingtrader.arena_agents(id) ON DELETE CASCADE,
  ticker TEXT NOT NULL,
  quantity NUMERIC(18,4) NOT NULL,              -- signed: >0 long, <0 short
  avg_cost NUMERIC(18,4) NOT NULL,              -- per share, always positive
  opened_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

  -- Last mark, refreshed by the mark pass. Denormalised so the leaderboard and
  -- the agent's own portfolio tool read one row instead of re-fetching quotes.
  last_price NUMERIC(18,4),
  marked_at TIMESTAMPTZ,

  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

  UNIQUE (agent_id, ticker),
  CHECK (quantity <> 0)
);

CREATE INDEX IF NOT EXISTS idx_arena_positions_agent
  ON swingtrader.arena_positions (agent_id);

-- ── 5) Cash + NAV history ───────────────────────────────────────────────────
-- `arena_accounts` is the single mutable cash row per agent; `arena_nav_history`
-- is the append-only daily curve the leaderboard and charts read.

CREATE TABLE IF NOT EXISTS swingtrader.arena_accounts (
  agent_id UUID PRIMARY KEY REFERENCES swingtrader.arena_agents(id) ON DELETE CASCADE,
  cash NUMERIC(18,2) NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS swingtrader.arena_nav_history (
  id BIGSERIAL PRIMARY KEY,
  agent_id UUID NOT NULL REFERENCES swingtrader.arena_agents(id) ON DELETE CASCADE,
  as_of DATE NOT NULL,

  cash NUMERIC(18,2) NOT NULL,
  long_value NUMERIC(18,2) NOT NULL DEFAULT 0,
  short_value NUMERIC(18,2) NOT NULL DEFAULT 0,  -- positive magnitude of shorts
  nav NUMERIC(18,2) NOT NULL,                    -- cash + long_value - short_value
  n_positions INTEGER NOT NULL DEFAULT 0,

  daily_return NUMERIC(12,8),                    -- vs previous nav row
  cumulative_return NUMERIC(12,8),               -- vs starting_cash
  drawdown NUMERIC(12,8),                        -- from running NAV peak, <= 0

  positions JSONB,                               -- snapshot for replay/audit

  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (agent_id, as_of)
);

CREATE INDEX IF NOT EXISTS idx_arena_nav_agent_asof
  ON swingtrader.arena_nav_history (agent_id, as_of DESC);

-- ── 6) updated_at triggers ──────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION swingtrader.touch_arena_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_arena_agents_updated_at ON swingtrader.arena_agents;
CREATE TRIGGER trg_arena_agents_updated_at
  BEFORE UPDATE ON swingtrader.arena_agents
  FOR EACH ROW EXECUTE FUNCTION swingtrader.touch_arena_updated_at();

DROP TRIGGER IF EXISTS trg_arena_positions_updated_at ON swingtrader.arena_positions;
CREATE TRIGGER trg_arena_positions_updated_at
  BEFORE UPDATE ON swingtrader.arena_positions
  FOR EACH ROW EXECUTE FUNCTION swingtrader.touch_arena_updated_at();

DROP TRIGGER IF EXISTS trg_arena_accounts_updated_at ON swingtrader.arena_accounts;
CREATE TRIGGER trg_arena_accounts_updated_at
  BEFORE UPDATE ON swingtrader.arena_accounts
  FOR EACH ROW EXECUTE FUNCTION swingtrader.touch_arena_updated_at();

-- ── 7) A filled order is immutable ──────────────────────────────────────────
-- Same lesson as research_predictions: if the record of what an agent did can be
-- edited after the outcome is known, the whole leaderboard is worthless. Once an
-- order is filled or rejected, only `realized_pnl`/`realized_pct` may be written
-- (the broker sets them in the same transaction as the fill, and a later
-- backfill of a close must not be able to rewrite the price it filled at).

CREATE OR REPLACE FUNCTION swingtrader.arena_orders_immutable()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  IF OLD.status IN ('filled', 'rejected', 'cancelled') THEN
    IF NEW.agent_id     IS DISTINCT FROM OLD.agent_id
    OR NEW.ticker       IS DISTINCT FROM OLD.ticker
    OR NEW.side         IS DISTINCT FROM OLD.side
    OR NEW.quantity     IS DISTINCT FROM OLD.quantity
    OR NEW.status       IS DISTINCT FROM OLD.status
    OR NEW.fill_price   IS DISTINCT FROM OLD.fill_price
    OR NEW.filled_at    IS DISTINCT FROM OLD.filled_at
    OR NEW.notional     IS DISTINCT FROM OLD.notional
    OR NEW.thesis       IS DISTINCT FROM OLD.thesis
    OR NEW.submitted_at IS DISTINCT FROM OLD.submitted_at THEN
      RAISE EXCEPTION
        'arena_orders %: a settled order is immutable (status=%)', OLD.id, OLD.status;
    END IF;
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_arena_orders_immutable ON swingtrader.arena_orders;
CREATE TRIGGER trg_arena_orders_immutable
  BEFORE UPDATE ON swingtrader.arena_orders
  FOR EACH ROW EXECUTE FUNCTION swingtrader.arena_orders_immutable();

-- ── 8) Public views ─────────────────────────────────────────────────────────
-- /arena reads ONLY these. `is_published` is filtered here rather than in the
-- page, so an agent that is still being tuned cannot leak onto the site through
-- a forgotten `.eq()`.

CREATE OR REPLACE VIEW swingtrader.arena_agents_public_v AS
SELECT
  a.id,
  a.slug,
  a.name,
  a.tagline,
  a.approach,
  a.engine,
  a.starting_cash,
  a.max_position_pct,
  a.max_positions,
  a.allow_shorts,
  a.funded_on,
  a.sort_order,
  a.is_active
FROM swingtrader.arena_agents a
WHERE a.is_published;

-- Standings. One row per published agent, carrying everything the leaderboard
-- shows: latest NAV, return since funding, max drawdown, realised win rate and
-- trade counts. Metrics are computed from the NAV curve and the closing orders,
-- so they cannot disagree with the charts underneath them.
CREATE OR REPLACE VIEW swingtrader.arena_leaderboard_v AS
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
  -- Annualised Sharpe at rf=0. NULL until there is enough curve to mean
  -- anything; 20 sessions is already generous for a number this noisy, and the
  -- UI labels it as provisional below ~60.
  CASE
    WHEN c.stdev_daily_return IS NULL OR c.stdev_daily_return = 0 OR c.nav_days < 20
      THEN NULL
    ELSE (c.mean_daily_return / c.stdev_daily_return) * SQRT(252)
  END                                       AS sharpe,
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
LEFT JOIN closes cl ON cl.agent_id = a.id
LEFT JOIN fills  f  ON f.agent_id  = a.id
WHERE a.is_published;

CREATE OR REPLACE VIEW swingtrader.arena_nav_history_public_v AS
SELECT
  a.slug AS agent_slug,
  n.agent_id, n.as_of, n.nav, n.cash, n.long_value, n.short_value,
  n.n_positions, n.daily_return, n.cumulative_return, n.drawdown
FROM swingtrader.arena_nav_history n
JOIN swingtrader.arena_agents a ON a.id = n.agent_id
WHERE a.is_published;

CREATE OR REPLACE VIEW swingtrader.arena_positions_public_v AS
SELECT
  a.slug AS agent_slug,
  p.agent_id, p.ticker, p.quantity, p.avg_cost, p.last_price, p.marked_at,
  p.opened_at,
  (p.quantity * COALESCE(p.last_price, p.avg_cost))                    AS market_value,
  (p.quantity * (COALESCE(p.last_price, p.avg_cost) - p.avg_cost))     AS unrealized_pnl,
  CASE WHEN p.avg_cost > 0
       THEN SIGN(p.quantity) * (COALESCE(p.last_price, p.avg_cost) - p.avg_cost) / p.avg_cost
       ELSE NULL END                                                   AS unrealized_pct
FROM swingtrader.arena_positions p
JOIN swingtrader.arena_agents a ON a.id = p.agent_id
WHERE a.is_published;

-- Orders, with the agent's stated case. Rejected orders are included on
-- purpose: what an agent tried and was not allowed to do is part of the record.
CREATE OR REPLACE VIEW swingtrader.arena_orders_public_v AS
SELECT
  a.slug AS agent_slug,
  o.id, o.agent_id, o.decision_id, o.ticker, o.side, o.quantity, o.status,
  o.reject_reason, o.thesis, o.conviction, o.stop_price, o.target_price,
  o.submitted_at, o.intended_for, o.filled_at, o.fill_price, o.notional,
  o.realized_pnl, o.realized_pct
FROM swingtrader.arena_orders o
JOIN swingtrader.arena_agents a ON a.id = o.agent_id
WHERE a.is_published;

CREATE OR REPLACE VIEW swingtrader.arena_decisions_public_v AS
SELECT
  a.slug AS agent_slug,
  d.id, d.agent_id, d.decision_date, d.status, d.narrative,
  d.rounds_used, d.tools_called,
  d.orders_requested, d.orders_accepted, d.orders_rejected,
  d.nav_at_decision, d.cash_at_decision, d.duration_ms, d.finished_at
FROM swingtrader.arena_decisions d
JOIN swingtrader.arena_agents a ON a.id = d.agent_id
WHERE a.is_published AND d.status IN ('ok', 'skipped');

-- ── 9) Grants + RLS ─────────────────────────────────────────────────────────
-- Base tables are service-role-only writes. Reads on the base tables are open to
-- authenticated (matching the sibling tables in this schema); the ANON site
-- traffic reads the public views, which already filter on is_published.

GRANT SELECT ON swingtrader.arena_agents             TO authenticated, service_role;
GRANT SELECT ON swingtrader.arena_decisions          TO authenticated, service_role;
GRANT SELECT ON swingtrader.arena_orders             TO authenticated, service_role;
GRANT SELECT ON swingtrader.arena_positions          TO authenticated, service_role;
GRANT SELECT ON swingtrader.arena_accounts           TO authenticated, service_role;
GRANT SELECT ON swingtrader.arena_nav_history        TO authenticated, service_role;

GRANT INSERT, UPDATE, DELETE ON swingtrader.arena_agents      TO service_role;
GRANT INSERT, UPDATE, DELETE ON swingtrader.arena_decisions   TO service_role;
GRANT INSERT, UPDATE, DELETE ON swingtrader.arena_orders      TO service_role;
GRANT INSERT, UPDATE, DELETE ON swingtrader.arena_positions   TO service_role;
GRANT INSERT, UPDATE, DELETE ON swingtrader.arena_accounts    TO service_role;
GRANT INSERT, UPDATE, DELETE ON swingtrader.arena_nav_history TO service_role;
GRANT USAGE, SELECT ON SEQUENCE swingtrader.arena_nav_history_id_seq TO service_role;

GRANT SELECT ON swingtrader.arena_agents_public_v        TO anon, authenticated, service_role;
GRANT SELECT ON swingtrader.arena_leaderboard_v          TO anon, authenticated, service_role;
GRANT SELECT ON swingtrader.arena_nav_history_public_v   TO anon, authenticated, service_role;
GRANT SELECT ON swingtrader.arena_positions_public_v     TO anon, authenticated, service_role;
GRANT SELECT ON swingtrader.arena_orders_public_v        TO anon, authenticated, service_role;
GRANT SELECT ON swingtrader.arena_decisions_public_v     TO anon, authenticated, service_role;

-- New tables ship with RLS on, and the REST API reads as `authenticated`, which
-- gets ZERO rows without a permissive policy. Mirror the sibling tables' policy.
-- service_role bypasses RLS, so the runner is unaffected.
DO $$
DECLARE t TEXT;
BEGIN
  FOREACH t IN ARRAY ARRAY[
    'arena_agents', 'arena_decisions', 'arena_orders',
    'arena_positions', 'arena_accounts', 'arena_nav_history'
  ] LOOP
    EXECUTE format('ALTER TABLE swingtrader.%I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('DROP POLICY IF EXISTS "Authenticated access to schemas" ON swingtrader.%I', t);
    EXECUTE format(
      'CREATE POLICY "Authenticated access to schemas" ON swingtrader.%I '
      'FOR SELECT TO authenticated USING (true)', t);
  END LOOP;
END $$;
