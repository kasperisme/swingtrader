-- The assembled system prompt, published.
--
-- `roster.py` is the source of truth and `arena_agents` is its projection. The
-- prompt is part of an agent's DEFINITION, exactly like its tool surface and its
-- risk limits, so it belongs in the projection alongside them rather than living
-- only in Python where the site cannot reach it.
--
-- Publishing it is what turns the downloadable spec at /agent/<slug>/spec from a
-- description into something reproducible: across the roster the model, broker,
-- limits and universe are identical, so the prompt and the tool surface ARE the
-- experiment. A reader who can see neither cannot check the claim.
--
-- Nullable, and empty for the two deterministic controls — they have no model to
-- prompt, which is the point of them.

ALTER TABLE swingtrader.arena_agents
  ADD COLUMN IF NOT EXISTS system_prompt text;

-- Recreated rather than altered: Postgres cannot add a column to the middle of a
-- view. The column list below is the live definition plus `system_prompt`.
DROP VIEW IF EXISTS swingtrader.arena_agents_public_v;
CREATE VIEW swingtrader.arena_agents_public_v AS
SELECT
  a.id,
  a.slug,
  a.name,
  a.tagline,
  a.approach,
  a.inspiration,
  a.tool_surface,
  a.system_prompt,
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

GRANT SELECT ON swingtrader.arena_agents_public_v TO anon, authenticated, service_role;
