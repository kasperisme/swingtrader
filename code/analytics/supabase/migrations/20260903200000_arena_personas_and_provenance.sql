-- ---------------------------------------------------------------------------
-- Arena: investor personas + decision provenance
--
-- Two changes:
--
-- 1) PERSONAS. The agents are renamed after the investor whose approach each one
--    actually implements (Barren Wuffett runs the fundamentals book, Mark
--    Minervine trades volume-confirmed breakouts, Burton Malarkey is the random
--    walk). Slugs are UPDATED IN PLACE rather than re-inserted, so every order,
--    decision and NAV row stays attached to its agent by id — a re-insert under
--    a new slug would orphan the entire history.
--
--    `inspiration` records whose style the agent implements, so the page can say
--    it plainly instead of leaving readers to decode a pun.
--
-- 2) PROVENANCE. `arena_decisions.resources` stores the platform resources an
--    agent actually consulted while deciding — the specific screening board, the
--    tickers whose priced-in decomposition it opened, the articles it read —
--    each with the URL of the page that publishes it. Storing which TOOL ran is
--    not enough: "used get_screening_results" is trivia, "read the NIS Momentum
--    board, here it is" is a link a reader can follow and check.
-- ---------------------------------------------------------------------------

-- ── 1) Personas ─────────────────────────────────────────────────────────────

ALTER TABLE swingtrader.arena_agents
  ADD COLUMN IF NOT EXISTS inspiration TEXT;

COMMENT ON COLUMN swingtrader.arena_agents.inspiration IS
  'The real investor whose publicly-known approach this agent implements. Parody name; no affiliation or endorsement implied.';

-- Rename in place. Guarded so re-running is a no-op and so a half-applied
-- migration cannot collide on the unique slug index.
DO $$
DECLARE
  m RECORD;
BEGIN
  FOR m IN
    SELECT * FROM (VALUES
      ('headline-hunter', 'jim-clamor'),
      ('the-skeptic',     'michael-beary'),
      ('breakout-rider',  'mark-minervine'),
      ('the-accountant',  'barren-wuffett'),
      ('second-order',    'howard-marx'),
      ('the-arbitrageur', 'jim-sigmons'),
      ('the-crowd',       'chris-cameo'),
      ('the-index',       'jack-boggle'),
      ('the-coinflip',    'burton-malarkey')
    ) AS t(old_slug, new_slug)
  LOOP
    IF EXISTS (SELECT 1 FROM swingtrader.arena_agents WHERE slug = m.old_slug)
       AND NOT EXISTS (SELECT 1 FROM swingtrader.arena_agents WHERE slug = m.new_slug)
    THEN
      UPDATE swingtrader.arena_agents
         SET slug = m.new_slug,
             strategy_key = m.new_slug
       WHERE slug = m.old_slug;
    END IF;
  END LOOP;
END $$;

-- ── 2) Provenance ───────────────────────────────────────────────────────────

ALTER TABLE swingtrader.arena_decisions
  ADD COLUMN IF NOT EXISTS resources JSONB;

COMMENT ON COLUMN swingtrader.arena_decisions.resources IS
  'Platform resources consulted while deciding: [{kind, key, label, href, detail}]. Derived from the agent''s actual tool calls and their results, so every claim on the page is followable.';

-- ── 3) Views carry both through ─────────────────────────────────────────────

DROP VIEW IF EXISTS swingtrader.arena_agents_public_v;
CREATE VIEW swingtrader.arena_agents_public_v AS
SELECT
  a.id,
  a.slug,
  a.name,
  a.tagline,
  a.approach,
  a.inspiration,
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

DROP VIEW IF EXISTS swingtrader.arena_decisions_public_v;
CREATE VIEW swingtrader.arena_decisions_public_v AS
SELECT
  a.slug AS agent_slug,
  d.id, d.agent_id, d.decision_date, d.status, d.narrative,
  d.rounds_used, d.tools_called, d.resources,
  d.orders_requested, d.orders_accepted, d.orders_rejected,
  d.nav_at_decision, d.cash_at_decision, d.duration_ms, d.finished_at,
  d.is_backtest
FROM swingtrader.arena_decisions d
JOIN swingtrader.arena_agents a ON a.id = d.agent_id
WHERE a.is_published AND d.status IN ('ok', 'skipped');

GRANT SELECT ON swingtrader.arena_agents_public_v    TO anon, authenticated, service_role;
GRANT SELECT ON swingtrader.arena_decisions_public_v TO anon, authenticated, service_role;
