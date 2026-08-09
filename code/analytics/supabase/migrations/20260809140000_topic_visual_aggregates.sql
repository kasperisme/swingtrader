-- ---------------------------------------------------------------------------
-- Aggregates behind the topic hub's charts.
--
-- Both shapes come back in ONE jsonb payload because the page's cost is round
-- trips, not query work (~140ms of network vs a few ms over a few hundred rows).
-- Two separate selects would have doubled the hop count for nothing.
--
-- Aggregated in Postgres rather than by pulling the claims: the claim TEXT is
-- the bulk of that table, and the page needs counts, not prose.
--
--   byTicker  which names the story actually moves — mean impact per ticker,
--             with the claim count next to it. The interesting part is that the
--             two disagree: on the defence topic LMT is the most-mentioned name
--             (239 claims) but sits near the BOTTOM on mean impact (+0.24),
--             while HII is barely mentioned (20) and tops it (+0.45).
--   byMonth   the escalation arc the page describes in prose but never showed.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION swingtrader.get_topic_visuals(p_slug text)
RETURNS jsonb
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = swingtrader, public
AS $$
  WITH per_ticker AS (
    SELECT
      t AS ticker,
      count(*)::int AS claims,
      round(avg(impact)::numeric, 3)::float8 AS mean_impact,
      count(*) FILTER (WHERE impact > 0)::int AS positive,
      count(*) FILTER (WHERE impact < 0)::int AS negative
    FROM swingtrader.topic_claim_stats,
         LATERAL unnest(COALESCE(tickers, '{}')) t
    WHERE topic_slug = p_slug
    GROUP BY t
  ),
  per_month AS (
    SELECT
      to_char(date_trunc('month', article_ts), 'YYYY-MM') AS month,
      count(*)::int AS claims,
      round(avg(impact)::numeric, 3)::float8 AS mean_impact,
      count(*) FILTER (WHERE impact > 0)::int AS positive,
      count(*) FILTER (WHERE impact < 0)::int AS negative
    FROM swingtrader.topic_claim_stats
    WHERE topic_slug = p_slug
    GROUP BY 1
  )
  SELECT jsonb_build_object(
    'byTicker', (
      SELECT COALESCE(jsonb_agg(to_jsonb(p) ORDER BY p.mean_impact DESC), '[]'::jsonb)
      FROM per_ticker p
    ),
    'byMonth', (
      SELECT COALESCE(jsonb_agg(to_jsonb(m) ORDER BY m.month), '[]'::jsonb)
      FROM per_month m
    )
  );
$$;

GRANT EXECUTE ON FUNCTION swingtrader.get_topic_visuals(text)
  TO anon, authenticated, service_role;
