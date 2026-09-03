-- ---------------------------------------------------------------------------
-- Arena: championships and the title lineage
--
-- Why:
-- - An open-ended leaderboard has no drama and no end state. Whoever is ahead is
--   ahead "so far", forever, and a bad first week follows an agent for months.
--   A championship is a FIXED WINDOW — every agent starts it on the same day
--   with the same cash — so it can be won, and then run again.
--
-- - The title carries between championships. The winner holds it until another
--   agent wins a later championship; consecutive wins are defences. That is the
--   thing worth following: not "who is up 3% since June" but "who took the belt
--   off whom, and how long did they keep it".
--
-- Consequences for the rest of the schema:
--
--   * Cash and positions are per (agent, championship). Each championship
--     re-funds every agent from scratch — otherwise the "fixed window" is a
--     fiction and season two is just season one continued.
--   * NAV, orders and decisions carry `championship_id`, so standings, returns
--     and drawdowns are computed WITHIN a championship rather than across the
--     whole history. A curve that spans a re-funding is not a curve.
--
-- The reigning champion is DERIVED (`arena_title_lineage_v`), never stored as
-- mutable state. A stored `is_champion` flag is one failed update away from two
-- champions or none; a view over concluded championships cannot disagree with
-- the results it is computed from.
-- ---------------------------------------------------------------------------

-- ── 1) The championships ────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS swingtrader.arena_championships (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  slug TEXT NOT NULL UNIQUE,              -- 'season-1'
  name TEXT NOT NULL,                     -- 'Season 1 — Autumn 2026'
  description TEXT,

  starts_on DATE NOT NULL,
  ends_on DATE NOT NULL,
  CHECK (ends_on >= starts_on),

  status TEXT NOT NULL DEFAULT 'upcoming'
    CHECK (status IN ('upcoming', 'running', 'complete', 'abandoned')),

  starting_cash NUMERIC(18,2) NOT NULL DEFAULT 100000,

  -- A championship replayed over past sessions rather than traded live. Kept on
  -- the championship itself so a whole season can be labelled at once instead of
  -- the page having to infer it from the rows underneath.
  is_backtest BOOLEAN NOT NULL DEFAULT FALSE,

  -- Result, written once by `conclude`.
  champion_agent_id UUID REFERENCES swingtrader.arena_agents(id) ON DELETE SET NULL,
  runner_up_agent_id UUID REFERENCES swingtrader.arena_agents(id) ON DELETE SET NULL,
  champion_return NUMERIC(12,8),
  concluded_at TIMESTAMPTZ,

  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE swingtrader.arena_championships IS
  'A fixed-window competition. Every agent is re-funded at the start; the winner takes the title and holds it until a later championship is won by someone else.';

-- At most one championship may be running at a time. Two overlapping live
-- championships would each try to own the agents'' current positions.
CREATE UNIQUE INDEX IF NOT EXISTS idx_arena_championship_one_running
  ON swingtrader.arena_championships ((status)) WHERE status = 'running';

CREATE OR REPLACE FUNCTION swingtrader.touch_arena_championship()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN NEW.updated_at = NOW(); RETURN NEW; END; $$;

DROP TRIGGER IF EXISTS trg_arena_championships_updated_at ON swingtrader.arena_championships;
CREATE TRIGGER trg_arena_championships_updated_at
  BEFORE UPDATE ON swingtrader.arena_championships
  FOR EACH ROW EXECUTE FUNCTION swingtrader.touch_arena_championship();

-- ── 2) Scope the state and history tables ───────────────────────────────────

ALTER TABLE swingtrader.arena_nav_history
  ADD COLUMN IF NOT EXISTS championship_id UUID REFERENCES swingtrader.arena_championships(id) ON DELETE CASCADE;
ALTER TABLE swingtrader.arena_orders
  ADD COLUMN IF NOT EXISTS championship_id UUID REFERENCES swingtrader.arena_championships(id) ON DELETE CASCADE;
ALTER TABLE swingtrader.arena_decisions
  ADD COLUMN IF NOT EXISTS championship_id UUID REFERENCES swingtrader.arena_championships(id) ON DELETE CASCADE;
ALTER TABLE swingtrader.arena_positions
  ADD COLUMN IF NOT EXISTS championship_id UUID REFERENCES swingtrader.arena_championships(id) ON DELETE CASCADE;
ALTER TABLE swingtrader.arena_accounts
  ADD COLUMN IF NOT EXISTS championship_id UUID REFERENCES swingtrader.arena_championships(id) ON DELETE CASCADE;

-- Re-key the per-agent state on (championship, agent). An agent holds one book
-- per championship, not one book forever.
ALTER TABLE swingtrader.arena_positions
  DROP CONSTRAINT IF EXISTS arena_positions_agent_id_ticker_key;
CREATE UNIQUE INDEX IF NOT EXISTS idx_arena_positions_champ_agent_ticker
  ON swingtrader.arena_positions (championship_id, agent_id, ticker);

ALTER TABLE swingtrader.arena_accounts
  DROP CONSTRAINT IF EXISTS arena_accounts_pkey CASCADE;
CREATE UNIQUE INDEX IF NOT EXISTS idx_arena_accounts_champ_agent
  ON swingtrader.arena_accounts (championship_id, agent_id);

-- A decision is unique per (championship, agent, date) — the same calendar day
-- can legitimately appear in a live championship and in a replayed one.
ALTER TABLE swingtrader.arena_decisions
  DROP CONSTRAINT IF EXISTS arena_decisions_agent_id_decision_date_key;
CREATE UNIQUE INDEX IF NOT EXISTS idx_arena_decisions_champ_agent_date
  ON swingtrader.arena_decisions (championship_id, agent_id, decision_date);

ALTER TABLE swingtrader.arena_nav_history
  DROP CONSTRAINT IF EXISTS arena_nav_history_agent_id_as_of_key;
CREATE UNIQUE INDEX IF NOT EXISTS idx_arena_nav_champ_agent_asof
  ON swingtrader.arena_nav_history (championship_id, agent_id, as_of);

CREATE INDEX IF NOT EXISTS idx_arena_nav_championship
  ON swingtrader.arena_nav_history (championship_id, agent_id, as_of DESC);
CREATE INDEX IF NOT EXISTS idx_arena_orders_championship
  ON swingtrader.arena_orders (championship_id, agent_id);

GRANT SELECT ON swingtrader.arena_championships TO anon, authenticated, service_role;
GRANT INSERT, UPDATE, DELETE ON swingtrader.arena_championships TO service_role;

ALTER TABLE swingtrader.arena_championships ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Authenticated access to schemas" ON swingtrader.arena_championships;
CREATE POLICY "Authenticated access to schemas"
  ON swingtrader.arena_championships FOR SELECT TO authenticated USING (true);

-- ── 3) Standings, per championship ──────────────────────────────────────────

DROP VIEW IF EXISTS swingtrader.arena_leaderboard_v;
CREATE VIEW swingtrader.arena_leaderboard_v AS
WITH latest AS (
  SELECT DISTINCT ON (n.championship_id, n.agent_id)
    n.championship_id, n.agent_id, n.as_of, n.nav, n.cash,
    n.long_value, n.short_value, n.n_positions, n.daily_return,
    n.cumulative_return, n.drawdown
  FROM swingtrader.arena_nav_history n
  ORDER BY n.championship_id, n.agent_id, n.as_of DESC
),
curve AS (
  SELECT n.championship_id, n.agent_id,
         COUNT(*) AS nav_days,
         MIN(n.drawdown) AS max_drawdown,
         AVG(n.daily_return) AS mean_daily_return,
         STDDEV_SAMP(n.daily_return) AS stdev_daily_return
  FROM swingtrader.arena_nav_history n
  WHERE n.daily_return IS NOT NULL
  GROUP BY 1, 2
),
closes AS (
  SELECT o.championship_id, o.agent_id,
         COUNT(*) AS closed_trades,
         COUNT(*) FILTER (WHERE o.realized_pnl > 0) AS winning_trades,
         SUM(o.realized_pnl) AS realized_pnl,
         AVG(o.realized_pct) AS avg_realized_pct
  FROM swingtrader.arena_orders o
  WHERE o.status = 'filled' AND o.realized_pnl IS NOT NULL
  GROUP BY 1, 2
),
fills AS (
  SELECT o.championship_id, o.agent_id, COUNT(*) AS filled_orders
  FROM swingtrader.arena_orders o
  WHERE o.status = 'filled'
  GROUP BY 1, 2
)
SELECT
  c.id                                      AS championship_id,
  c.slug                                    AS championship_slug,
  c.name                                    AS championship_name,
  c.status                                  AS championship_status,
  c.starts_on,
  c.ends_on,
  c.is_backtest                             AS championship_is_backtest,
  a.id,
  a.slug,
  a.name,
  a.tagline,
  a.inspiration,
  a.engine,
  a.sort_order,
  c.starting_cash,
  l.as_of,
  l.nav,
  l.cash,
  l.long_value,
  l.short_value,
  l.n_positions,
  l.daily_return,
  l.cumulative_return                       AS total_return,
  cv.max_drawdown,
  cv.nav_days,
  CASE
    WHEN cv.stdev_daily_return IS NULL OR cv.stdev_daily_return = 0 OR cv.nav_days < 20
      THEN NULL
    ELSE (cv.mean_daily_return / cv.stdev_daily_return) * SQRT(252)
  END                                       AS sharpe,
  COALESCE(f.filled_orders, 0)              AS filled_orders,
  COALESCE(cl.closed_trades, 0)             AS closed_trades,
  COALESCE(cl.winning_trades, 0)            AS winning_trades,
  CASE WHEN COALESCE(cl.closed_trades, 0) > 0
       THEN cl.winning_trades::NUMERIC / cl.closed_trades
       ELSE NULL END                        AS win_rate,
  cl.realized_pnl,
  cl.avg_realized_pct,
  (c.champion_agent_id = a.id)              AS is_champion
FROM swingtrader.arena_championships c
CROSS JOIN swingtrader.arena_agents a
LEFT JOIN latest l  ON l.championship_id  = c.id AND l.agent_id  = a.id
LEFT JOIN curve  cv ON cv.championship_id = c.id AND cv.agent_id = a.id
LEFT JOIN closes cl ON cl.championship_id = c.id AND cl.agent_id = a.id
LEFT JOIN fills  f  ON f.championship_id  = c.id AND f.agent_id  = a.id
WHERE a.is_published
  -- An agent that never got a NAV row in a championship did not take part in it.
  AND l.agent_id IS NOT NULL;

-- ── 4) The title lineage ────────────────────────────────────────────────────
-- Who has held the belt, when they took it, and when they lost it. Derived
-- entirely from concluded championships, so it cannot contradict the results.

DROP VIEW IF EXISTS swingtrader.arena_title_lineage_v;
CREATE VIEW swingtrader.arena_title_lineage_v AS
WITH concluded AS (
  SELECT c.id, c.slug, c.name, c.ends_on, c.concluded_at,
         c.champion_agent_id, c.champion_return,
         ROW_NUMBER() OVER (ORDER BY c.ends_on, c.concluded_at) AS seq
  FROM swingtrader.arena_championships c
  WHERE c.status = 'complete' AND c.champion_agent_id IS NOT NULL
),
-- A new REIGN starts whenever the champion differs from the previous
-- championship's champion. Consecutive wins by the same agent extend the reign
-- rather than starting a new one — those are title defences.
marked AS (
  SELECT *,
         CASE WHEN champion_agent_id
                   IS DISTINCT FROM LAG(champion_agent_id) OVER (ORDER BY seq)
              THEN 1 ELSE 0 END AS starts_reign
  FROM concluded
),
reigns AS (
  SELECT *, SUM(starts_reign) OVER (ORDER BY seq) AS reign_no
  FROM marked
)
SELECT
  r.reign_no,
  r.champion_agent_id                       AS agent_id,
  a.slug                                    AS agent_slug,
  a.name                                    AS agent_name,
  MIN(r.ends_on)                            AS held_from,
  MAX(r.ends_on)                            AS held_through,
  COUNT(*)                                  AS championships_won,
  COUNT(*) - 1                              AS successful_defences,
  ARRAY_AGG(r.slug ORDER BY r.seq)          AS championship_slugs,
  MAX(r.seq) = (SELECT MAX(seq) FROM concluded) AS is_current_holder
FROM reigns r
JOIN swingtrader.arena_agents a ON a.id = r.champion_agent_id
GROUP BY r.reign_no, r.champion_agent_id, a.slug, a.name
ORDER BY MIN(r.ends_on);

DROP VIEW IF EXISTS swingtrader.arena_championships_public_v;
CREATE VIEW swingtrader.arena_championships_public_v AS
SELECT
  c.id, c.slug, c.name, c.description, c.starts_on, c.ends_on, c.status,
  c.starting_cash, c.is_backtest, c.concluded_at, c.champion_return,
  champ.slug AS champion_slug, champ.name AS champion_name,
  ru.slug    AS runner_up_slug, ru.name AS runner_up_name,
  (SELECT COUNT(DISTINCT n.agent_id)
     FROM swingtrader.arena_nav_history n WHERE n.championship_id = c.id) AS entrants
FROM swingtrader.arena_championships c
LEFT JOIN swingtrader.arena_agents champ ON champ.id = c.champion_agent_id
LEFT JOIN swingtrader.arena_agents ru    ON ru.id    = c.runner_up_agent_id
ORDER BY c.starts_on DESC;

GRANT SELECT ON swingtrader.arena_leaderboard_v            TO anon, authenticated, service_role;
GRANT SELECT ON swingtrader.arena_title_lineage_v          TO anon, authenticated, service_role;
GRANT SELECT ON swingtrader.arena_championships_public_v   TO anon, authenticated, service_role;
