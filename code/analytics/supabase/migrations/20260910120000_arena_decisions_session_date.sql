-- ---------------------------------------------------------------------------
-- arena_decisions.session_date — the session the agent actually READ
--
-- `decision_date` does not hold the date the agent decided. It holds
-- `intended_for`: the session the resulting orders fill in. `decide.py` passes
-- it straight into `open_decision`, and the column name has been lying about
-- its contents ever since.
--
-- That is not cosmetic. The agent page renders `decision_date` as the heading
-- of each entry, so every entry in every agent's log is labelled one session
-- late, and two visible defects fall out of it:
--
--   * A decision appears on 2026-09-07 — Labor Day, a session that never
--     happened. The agent read Friday the 4th; the orders were merely aimed at
--     the next session, which the holiday then moved.
--   * 2026-09-08 is absent from the log despite being a real session with NAV
--     rows, because its decision was stamped 09-09.
--
-- Both are the same off-by-one. Re-labelling turns the season's entries from
-- (3, 4, 7, 9, 10 Sept) into (2, 3, 4, 8, 9 Sept): the phantom holiday goes,
-- the missing session appears, and no session from the 3rd onward is left
-- without a decision.
--
-- WHY ADD RATHER THAN RENAME. `decision_date` is load-bearing: it is half the
-- upsert key that makes a re-run overwrite an attempt instead of doubling it
-- (`championship_id, agent_id, decision_date`), and `app/actions/arena.ts`
-- deliberately joins orders on `decision_id` because the two dates do not line
-- up. Renaming a key column mid-championship buys nothing that a correct
-- second column does not.
--
-- THE BACKFILL is the same rule `run_decide` applies live: the session an agent
-- read is the last one it had a mark for before the orders' target date. It is
-- verifiable rather than assumed — `nav_at_decision` on each row equals that
-- session's NAV exactly, which is how the mapping above was confirmed.
--
-- A decision with no earlier NAV row keeps NULL rather than guessing; the UI
-- falls back to `decision_date` for those.
-- ---------------------------------------------------------------------------

ALTER TABLE swingtrader.arena_decisions
    ADD COLUMN IF NOT EXISTS session_date DATE;

COMMENT ON COLUMN swingtrader.arena_decisions.session_date IS
    'The trading session whose close the agent read when it decided. This is the '
    'date to show a reader. NULL only for a decision with no preceding NAV mark.';

COMMENT ON COLUMN swingtrader.arena_decisions.decision_date IS
    'The session the resulting orders are INTENDED FOR (the next open), not the '
    'session the agent read — see session_date. Half of the upsert key '
    '(championship_id, agent_id, decision_date), so a re-run for the same target '
    'session overwrites the attempt rather than doubling the record.';

UPDATE swingtrader.arena_decisions d
SET session_date = (
    SELECT MAX(n.as_of)
    FROM swingtrader.arena_nav_history n
    WHERE n.agent_id = d.agent_id
      AND n.championship_id = d.championship_id
      AND n.as_of < d.decision_date
)
WHERE d.session_date IS NULL;

-- Republish the view with the new column. Recreated in full rather than
-- patched, because a view cannot gain a column in place.
DROP VIEW IF EXISTS swingtrader.arena_decisions_public_v;
CREATE VIEW swingtrader.arena_decisions_public_v AS
SELECT
  a.slug AS agent_slug,
  d.id, d.agent_id, d.championship_id, d.session_date, d.decision_date,
  d.status, d.narrative,
  d.rounds_used, d.tools_called, d.resources,
  d.orders_requested, d.orders_accepted, d.orders_rejected,
  d.nav_at_decision, d.cash_at_decision, d.duration_ms, d.finished_at,
  d.is_backtest
FROM swingtrader.arena_decisions d
JOIN swingtrader.arena_agents a ON a.id = d.agent_id
WHERE a.is_published AND d.status IN ('ok', 'skipped');

GRANT SELECT ON swingtrader.arena_decisions_public_v TO anon, authenticated, service_role;
