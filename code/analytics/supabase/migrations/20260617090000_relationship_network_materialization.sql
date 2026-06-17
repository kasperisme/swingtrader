-- ---------------------------------------------------------------------------
-- Relationship network materialization
--
-- Problem (statement timeout on /protected/relations):
--   ticker_relationship_network_resolved_v calls resolve_canonical_ticker()
--   TWICE per edge across all ~22k rows of ticker_relationship_edges (each call
--   is a security_identity_map lookup), then GROUP BYs — on EVERY query. So
--   get_relationship_neighborhood() paid a fixed ~6s cost regardless of seed or
--   hop count (measured: 1-hop and 2-hop both ~6.3s; the resolved view costs
--   ~4.5s just to COUNT). Every node click on the relations side panel re-runs
--   it, tripping the Postgres statement_timeout.
--
-- Fix:
--   Materialize the canonicalized + collapsed graph once, index it, and point
--   the neighborhood RPC at the matview. The per-call cost drops from ~6s to a
--   few ms (an indexed read of a ~22k-row snapshot). Batch jobs that aren't
--   latency-sensitive (pair calibration, candidates) can keep using the view.
--
-- Refresh cadence:
--   The graph is rebuilt in batches by the news-scoring pipeline, so the matview
--   only needs a periodic refresh — call swingtrader.refresh_relationship_network_mv()
--   after each relationship-graph build (or on a cron, e.g. every 15–30 min).
--   It is slightly stale between refreshes, which is fine for this graph.
-- ---------------------------------------------------------------------------

CREATE MATERIALIZED VIEW IF NOT EXISTS swingtrader.ticker_relationship_network_resolved_mv AS
  SELECT
    from_ticker,
    to_ticker,
    rel_type,
    strength_avg,
    strength_max,
    mention_count,
    article_count,
    first_seen_at,
    last_seen_at
  FROM swingtrader.ticker_relationship_network_resolved_v
WITH DATA;

-- (from_ticker, to_ticker, rel_type) is unique by construction — the resolved
-- view GROUP BYs exactly those three columns — so a UNIQUE index is valid and
-- lets us REFRESH ... CONCURRENTLY (no read lock during refresh).
CREATE UNIQUE INDEX IF NOT EXISTS ux_trn_resolved_mv_edge
  ON swingtrader.ticker_relationship_network_resolved_mv (from_ticker, to_ticker, rel_type);
CREATE INDEX IF NOT EXISTS idx_trn_resolved_mv_from
  ON swingtrader.ticker_relationship_network_resolved_mv (from_ticker);
CREATE INDEX IF NOT EXISTS idx_trn_resolved_mv_to
  ON swingtrader.ticker_relationship_network_resolved_mv (to_ticker);
CREATE INDEX IF NOT EXISTS idx_trn_resolved_mv_strength
  ON swingtrader.ticker_relationship_network_resolved_mv (strength_avg DESC);

CREATE OR REPLACE FUNCTION swingtrader.refresh_relationship_network_mv()
RETURNS void
LANGUAGE plpgsql
AS $$
BEGIN
  REFRESH MATERIALIZED VIEW CONCURRENTLY swingtrader.ticker_relationship_network_resolved_mv;
EXCEPTION WHEN OTHERS THEN
  -- First refresh after create (the MV is already populated WITH DATA, but a
  -- concurrent refresh needs a prior non-concurrent populate in some setups) —
  -- fall back to a plain refresh.
  REFRESH MATERIALIZED VIEW swingtrader.ticker_relationship_network_resolved_mv;
END;
$$;

GRANT SELECT ON swingtrader.ticker_relationship_network_resolved_mv TO anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION swingtrader.refresh_relationship_network_mv() TO service_role;

-- ---------------------------------------------------------------------------
-- Repoint the neighborhood RPC at the matview. ONLY the source relation changes
-- (filtered_edges now reads the materialized snapshot instead of recomputing the
-- canonicalization per call); all filtering/traversal/limits are unchanged.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION swingtrader.get_relationship_neighborhood(
  p_seed TEXT,
  p_hops INTEGER DEFAULT 2,
  p_min_strength DOUBLE PRECISION DEFAULT 0.25,
  p_min_mentions INTEGER DEFAULT 1,
  p_rel_types TEXT[] DEFAULT NULL,
  p_limit_nodes INTEGER DEFAULT 140,
  p_limit_edges INTEGER DEFAULT 360,
  p_days_lookback INTEGER DEFAULT NULL
)
RETURNS TABLE (
  row_type TEXT,
  seed_ticker TEXT,
  node_ticker TEXT,
  from_ticker TEXT,
  to_ticker TEXT,
  rel_type TEXT,
  strength_avg DOUBLE PRECISION,
  strength_max DOUBLE PRECISION,
  mention_count INTEGER,
  article_count INTEGER,
  first_seen_at TIMESTAMPTZ,
  last_seen_at TIMESTAMPTZ,
  truncated BOOLEAN
)
LANGUAGE sql
STABLE
AS $$
WITH RECURSIVE params AS (
  SELECT
    swingtrader.resolve_canonical_ticker(p_seed, 'ticker') AS seed_ticker,
    GREATEST(1, LEAST(2, COALESCE(p_hops, 2))) AS hops,
    GREATEST(0.0, LEAST(1.0, COALESCE(p_min_strength, 0.25))) AS min_strength,
    GREATEST(1, COALESCE(p_min_mentions, 1)) AS min_mentions,
    COALESCE(p_rel_types, ARRAY[]::TEXT[]) AS rel_types,
    GREATEST(20, COALESCE(p_limit_nodes, 140)) AS limit_nodes,
    GREATEST(50, COALESCE(p_limit_edges, 360)) AS limit_edges,
    CASE
      WHEN p_days_lookback IS NULL OR p_days_lookback <= 0 THEN NULL
      ELSE NOW() - (p_days_lookback || ' days')::INTERVAL
    END AS cutoff
),
filtered_edges AS (
  SELECT
    e.from_ticker,
    e.to_ticker,
    e.rel_type,
    e.strength_avg,
    e.strength_max,
    e.mention_count,
    e.article_count,
    e.first_seen_at,
    e.last_seen_at
  FROM swingtrader.ticker_relationship_network_resolved_mv e
  CROSS JOIN params p
  WHERE e.from_ticker <> ''
    AND e.to_ticker <> ''
    AND e.from_ticker <> e.to_ticker
    AND e.strength_avg >= p.min_strength
    AND e.mention_count >= p.min_mentions
    AND (
      cardinality(p.rel_types) = 0
      OR e.rel_type = ANY (p.rel_types)
    )
    AND (
      p.cutoff IS NULL
      OR e.last_seen_at >= p.cutoff
    )
),
adjacency AS (
  SELECT fe.from_ticker AS src, fe.to_ticker AS dst FROM filtered_edges fe
  UNION ALL
  SELECT fe.to_ticker AS src, fe.from_ticker AS dst FROM filtered_edges fe
),
walk AS (
  SELECT
    p.seed_ticker AS node_ticker,
    0 AS depth,
    ARRAY[p.seed_ticker]::TEXT[] AS path
  FROM params p
  UNION ALL
  SELECT
    a.dst AS node_ticker,
    w.depth + 1 AS depth,
    array_append(w.path, a.dst) AS path
  FROM walk w
  JOIN adjacency a
    ON a.src = w.node_ticker
  CROSS JOIN params p
  WHERE w.depth < p.hops
    AND NOT (a.dst = ANY (w.path))
),
reachable AS (
  SELECT w.node_ticker, MIN(w.depth) AS depth
  FROM walk w
  GROUP BY w.node_ticker
),
kept_nodes AS (
  SELECT r.node_ticker, r.depth
  FROM reachable r
  ORDER BY r.depth ASC, r.node_ticker ASC
  LIMIT (SELECT limit_nodes FROM params)
),
kept_edges AS (
  SELECT
    fe.from_ticker, fe.to_ticker, fe.rel_type, fe.strength_avg, fe.strength_max,
    fe.mention_count, fe.article_count, fe.first_seen_at, fe.last_seen_at
  FROM filtered_edges fe
  JOIN kept_nodes a ON a.node_ticker = fe.from_ticker
  JOIN kept_nodes b ON b.node_ticker = fe.to_ticker
  ORDER BY fe.strength_avg DESC, fe.mention_count DESC, fe.from_ticker ASC, fe.to_ticker ASC
  LIMIT (SELECT limit_edges FROM params)
),
counts AS (
  SELECT
    (SELECT COUNT(*) FROM reachable) AS full_node_count,
    (SELECT COUNT(*) FROM filtered_edges) AS full_edge_count,
    (SELECT limit_nodes FROM params) AS limit_nodes,
    (SELECT limit_edges FROM params) AS limit_edges
),
node_rows AS (
  SELECT
    'node'::TEXT AS row_type, p.seed_ticker, kn.node_ticker,
    NULL::TEXT, NULL::TEXT, NULL::TEXT,
    NULL::DOUBLE PRECISION, NULL::DOUBLE PRECISION, NULL::INTEGER, NULL::INTEGER,
    NULL::TIMESTAMPTZ, NULL::TIMESTAMPTZ,
    (c.full_node_count > c.limit_nodes OR c.full_edge_count > c.limit_edges) AS truncated
  FROM kept_nodes kn CROSS JOIN params p CROSS JOIN counts c
),
edge_rows AS (
  SELECT
    'edge'::TEXT AS row_type, p.seed_ticker, NULL::TEXT,
    ke.from_ticker, ke.to_ticker, ke.rel_type,
    ke.strength_avg, ke.strength_max, ke.mention_count, ke.article_count,
    ke.first_seen_at, ke.last_seen_at,
    (c.full_node_count > c.limit_nodes OR c.full_edge_count > c.limit_edges) AS truncated
  FROM kept_edges ke CROSS JOIN params p CROSS JOIN counts c
)
SELECT * FROM node_rows
UNION ALL
SELECT * FROM edge_rows;
$$;
