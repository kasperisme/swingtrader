-- ---------------------------------------------------------------------------
-- Arena: chris-cameo -> jim-chaos
--
-- The agent's strategy was inverted on 2026-09-13: it no longer buys the
-- accelerating themes the price has not paid for (Chris Camillo's social
-- arbitrage), it SHORTS them — a short-seller's method, modelled on Jim Chanos.
-- A name that parodies Camillo on an agent that bets against his setups is a
-- label that says the opposite of what the agent does.
--
-- Renamed IN PLACE, the same way 20260903200000 renamed the original roster:
-- slug and strategy_key are updated on the existing row, so its id — and the
-- season-1 account, orders, decisions and NAV rows keyed on it — stay attached.
-- `roster.py` alone cannot do this: upsert_agent keys on slug, so syncing the
-- new slug without this migration inserts a second agent and leaves the old
-- row active in the nightly run.
--
-- Guarded so re-running is a no-op and a half-applied run cannot collide on
-- the unique slug index. Apply BEFORE `cli.py sync-roster`.
-- ---------------------------------------------------------------------------

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM swingtrader.arena_agents WHERE slug = 'chris-cameo')
     AND NOT EXISTS (SELECT 1 FROM swingtrader.arena_agents WHERE slug = 'jim-chaos')
  THEN
    UPDATE swingtrader.arena_agents
       SET slug = 'jim-chaos',
           strategy_key = 'jim-chaos',
           name = 'Jim Chaos',
           inspiration = 'Jim Chanos — short seller: bets against stories the numbers do not support.'
     WHERE slug = 'chris-cameo';
  END IF;
END $$;
