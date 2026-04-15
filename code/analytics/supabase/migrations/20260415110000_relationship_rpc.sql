-- ---------------------------------------------------------------------------
-- Relationship RPCs
--
-- Why:
-- - Move neighborhood traversal and node-specific aggregation into SQL.
-- - Reduce app-side dedup/merge/BFS logic in relationships actions.
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
  FROM swingtrader.ticker_relationship_network_resolved_v e
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
  SELECT
    fe.from_ticker AS src,
    fe.to_ticker AS dst
  FROM filtered_edges fe
  UNION ALL
  SELECT
    fe.to_ticker AS src,
    fe.from_ticker AS dst
  FROM filtered_edges fe
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
  SELECT
    w.node_ticker,
    MIN(w.depth) AS depth
  FROM walk w
  GROUP BY w.node_ticker
),
kept_nodes AS (
  SELECT
    r.node_ticker,
    r.depth
  FROM reachable r
  ORDER BY r.depth ASC, r.node_ticker ASC
  LIMIT (SELECT limit_nodes FROM params)
),
kept_edges AS (
  SELECT
    fe.from_ticker,
    fe.to_ticker,
    fe.rel_type,
    fe.strength_avg,
    fe.strength_max,
    fe.mention_count,
    fe.article_count,
    fe.first_seen_at,
    fe.last_seen_at
  FROM filtered_edges fe
  JOIN kept_nodes a
    ON a.node_ticker = fe.from_ticker
  JOIN kept_nodes b
    ON b.node_ticker = fe.to_ticker
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
    'node'::TEXT AS row_type,
    p.seed_ticker,
    kn.node_ticker,
    NULL::TEXT AS from_ticker,
    NULL::TEXT AS to_ticker,
    NULL::TEXT AS rel_type,
    NULL::DOUBLE PRECISION AS strength_avg,
    NULL::DOUBLE PRECISION AS strength_max,
    NULL::INTEGER AS mention_count,
    NULL::INTEGER AS article_count,
    NULL::TIMESTAMPTZ AS first_seen_at,
    NULL::TIMESTAMPTZ AS last_seen_at,
    (c.full_node_count > c.limit_nodes OR c.full_edge_count > c.limit_edges) AS truncated
  FROM kept_nodes kn
  CROSS JOIN params p
  CROSS JOIN counts c
),
edge_rows AS (
  SELECT
    'edge'::TEXT AS row_type,
    p.seed_ticker,
    NULL::TEXT AS node_ticker,
    ke.from_ticker,
    ke.to_ticker,
    ke.rel_type,
    ke.strength_avg,
    ke.strength_max,
    ke.mention_count,
    ke.article_count,
    ke.first_seen_at,
    ke.last_seen_at,
    (c.full_node_count > c.limit_nodes OR c.full_edge_count > c.limit_edges) AS truncated
  FROM kept_edges ke
  CROSS JOIN params p
  CROSS JOIN counts c
)
SELECT * FROM node_rows
UNION ALL
SELECT * FROM edge_rows;
$$;

CREATE OR REPLACE FUNCTION swingtrader.get_relationship_node_news(
  p_ticker TEXT,
  p_page INTEGER DEFAULT 1,
  p_page_size INTEGER DEFAULT 10,
  p_days_lookback INTEGER DEFAULT NULL
)
RETURNS TABLE (
  canonical_ticker TEXT,
  article_id BIGINT,
  title TEXT,
  url TEXT,
  source TEXT,
  publisher TEXT,
  published_at TIMESTAMPTZ,
  matched_ticker TEXT
)
LANGUAGE sql
STABLE
AS $$
WITH params AS (
  SELECT
    swingtrader.resolve_canonical_ticker(p_ticker, 'ticker') AS canonical_ticker,
    GREATEST(1, COALESCE(p_page, 1)) AS page_num,
    LEAST(30, GREATEST(5, COALESCE(p_page_size, 10))) AS page_size,
    CASE
      WHEN p_days_lookback IS NULL OR p_days_lookback <= 0 THEN NULL
      ELSE NOW() - (p_days_lookback || ' days')::INTERVAL
    END AS cutoff
),
aliases AS (
  SELECT p.canonical_ticker AS ticker
  FROM params p
  UNION
  SELECT upper(btrim(sim.alias_value)) AS ticker
  FROM swingtrader.security_identity_map sim
  CROSS JOIN params p
  WHERE sim.canonical_ticker = p.canonical_ticker
    AND sim.alias_kind = 'ticker'
    AND btrim(sim.alias_value) <> ''
),
trace_rows AS (
  SELECT
    p.canonical_ticker,
    t.article_id,
    t.article_title AS title,
    t.article_url AS url,
    'traceability'::TEXT AS source,
    NULL::TEXT AS publisher,
    t.published_at,
    CASE
      WHEN t.from_ticker = p.canonical_ticker THEN p.canonical_ticker
      ELSE t.to_ticker
    END AS matched_ticker,
    0 AS precedence
  FROM swingtrader.ticker_relationship_edge_traceability_v t
  CROSS JOIN params p
  WHERE (
      t.from_ticker IN (SELECT ticker FROM aliases)
      OR t.to_ticker IN (SELECT ticker FROM aliases)
    )
    AND (p.cutoff IS NULL OR t.published_at >= p.cutoff)
),
mention_rows AS (
  SELECT
    p.canonical_ticker,
    na.id AS article_id,
    na.title,
    na.url,
    na.source,
    na.publisher,
    COALESCE(na.published_at, na.created_at) AS published_at,
    nat.ticker AS matched_ticker,
    1 AS precedence
  FROM swingtrader.news_article_tickers nat
  JOIN swingtrader.news_articles na
    ON na.id = nat.article_id
  CROSS JOIN params p
  WHERE nat.ticker IN (SELECT ticker FROM aliases)
    AND (
      p.cutoff IS NULL
      OR COALESCE(na.published_at, na.created_at) >= p.cutoff
    )
),
unioned AS (
  SELECT * FROM trace_rows
  UNION ALL
  SELECT * FROM mention_rows
),
deduped AS (
  SELECT DISTINCT ON (u.article_id)
    u.canonical_ticker,
    u.article_id,
    u.title,
    u.url,
    u.source,
    u.publisher,
    u.published_at,
    u.matched_ticker
  FROM unioned u
  ORDER BY u.article_id, u.precedence ASC, u.published_at DESC NULLS LAST
),
ranked AS (
  SELECT
    d.*,
    ROW_NUMBER() OVER (ORDER BY d.published_at DESC NULLS LAST, d.article_id DESC) AS rn
  FROM deduped d
)
SELECT
  r.canonical_ticker,
  r.article_id,
  r.title,
  r.url,
  r.source,
  r.publisher,
  r.published_at,
  r.matched_ticker
FROM ranked r
CROSS JOIN params p
WHERE r.rn > ((p.page_num - 1) * p.page_size)
  AND r.rn <= (p.page_num * p.page_size)
ORDER BY r.rn;
$$;

CREATE OR REPLACE FUNCTION swingtrader.get_relationship_node_sentiment(
  p_ticker TEXT,
  p_page INTEGER DEFAULT 1,
  p_page_size INTEGER DEFAULT 10
)
RETURNS TABLE (
  canonical_ticker TEXT,
  head_id BIGINT,
  article_id BIGINT,
  ticker TEXT,
  sentiment_score DOUBLE PRECISION,
  reasoning_text TEXT,
  confidence DOUBLE PRECISION,
  article_ts TIMESTAMPTZ,
  published_at TIMESTAMPTZ,
  article_source TEXT,
  article_publisher TEXT,
  article_title TEXT,
  article_url TEXT
)
LANGUAGE sql
STABLE
AS $$
WITH params AS (
  SELECT
    swingtrader.resolve_canonical_ticker(p_ticker, 'ticker') AS canonical_ticker,
    GREATEST(1, COALESCE(p_page, 1)) AS page_num,
    LEAST(50, GREATEST(5, COALESCE(p_page_size, 10))) AS page_size
),
aliases AS (
  SELECT p.canonical_ticker AS ticker
  FROM params p
  UNION
  SELECT upper(btrim(sim.alias_value)) AS ticker
  FROM swingtrader.security_identity_map sim
  CROSS JOIN params p
  WHERE sim.canonical_ticker = p.canonical_ticker
    AND sim.alias_kind = 'ticker'
    AND btrim(sim.alias_value) <> ''
)
WITH sentiment_ranked AS (
  SELECT
    p.canonical_ticker,
    s.head_id,
    s.article_id,
    s.ticker,
    s.sentiment_score,
    s.reasoning_text,
    s.confidence,
    s.article_ts,
    s.published_at,
    s.article_source,
    s.article_publisher,
    s.article_title,
    s.article_url,
    ROW_NUMBER() OVER (ORDER BY s.article_ts DESC NULLS LAST, s.head_id DESC) AS rn
  FROM swingtrader.ticker_sentiment_heads_v s
  CROSS JOIN params p
  WHERE s.ticker IN (SELECT ticker FROM aliases)
)
SELECT
  sr.canonical_ticker,
  sr.head_id,
  sr.article_id,
  sr.ticker,
  sr.sentiment_score,
  sr.reasoning_text,
  sr.confidence,
  sr.article_ts,
  sr.published_at,
  sr.article_source,
  sr.article_publisher,
  sr.article_title,
  sr.article_url
FROM sentiment_ranked sr
CROSS JOIN params p
WHERE sr.rn > ((p.page_num - 1) * p.page_size)
  AND sr.rn <= (p.page_num * p.page_size)
ORDER BY sr.rn;
$$;

CREATE OR REPLACE FUNCTION swingtrader.get_relationship_node_sentiment_windows(
  p_ticker TEXT
)
RETURNS TABLE (
  days INTEGER,
  avg_sentiment DOUBLE PRECISION,
  weighted_sentiment DOUBLE PRECISION,
  mention_count INTEGER
)
LANGUAGE sql
STABLE
AS $$
WITH params AS (
  SELECT swingtrader.resolve_canonical_ticker(p_ticker, 'ticker') AS canonical_ticker
),
aliases AS (
  SELECT p.canonical_ticker AS ticker
  FROM params p
  UNION
  SELECT upper(btrim(sim.alias_value)) AS ticker
  FROM swingtrader.security_identity_map sim
  CROSS JOIN params p
  WHERE sim.canonical_ticker = p.canonical_ticker
    AND sim.alias_kind = 'ticker'
    AND btrim(sim.alias_value) <> ''
),
window_defs AS (
  SELECT 10 AS days
  UNION ALL
  SELECT 21 AS days
  UNION ALL
  SELECT 50 AS days
  UNION ALL
  SELECT 200 AS days
),
base AS (
  SELECT
    s.sentiment_score,
    GREATEST(0.0, LEAST(1.0, COALESCE(s.confidence, 1.0))) AS confidence,
    s.article_ts
  FROM swingtrader.ticker_sentiment_heads_v s
  WHERE s.ticker IN (SELECT ticker FROM aliases)
    AND s.article_ts >= NOW() - INTERVAL '200 days'
)
SELECT
  w.days,
  AVG(b.sentiment_score) FILTER (
    WHERE b.article_ts >= NOW() - ((w.days || ' days')::INTERVAL)
  ) AS avg_sentiment,
  CASE
    WHEN SUM(b.confidence) FILTER (
      WHERE b.article_ts >= NOW() - ((w.days || ' days')::INTERVAL)
    ) > 0
    THEN
      SUM(b.sentiment_score * b.confidence) FILTER (
        WHERE b.article_ts >= NOW() - ((w.days || ' days')::INTERVAL)
      )
      / SUM(b.confidence) FILTER (
        WHERE b.article_ts >= NOW() - ((w.days || ' days')::INTERVAL)
      )
    ELSE NULL
  END AS weighted_sentiment,
  COUNT(*) FILTER (
    WHERE b.article_ts >= NOW() - ((w.days || ' days')::INTERVAL)
  )::INTEGER AS mention_count
FROM window_defs w
LEFT JOIN base b
  ON TRUE
GROUP BY w.days
ORDER BY w.days ASC;
$$;

GRANT EXECUTE ON FUNCTION swingtrader.get_relationship_neighborhood(TEXT, INTEGER, DOUBLE PRECISION, INTEGER, TEXT[], INTEGER, INTEGER, INTEGER) TO anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION swingtrader.get_relationship_node_news(TEXT, INTEGER, INTEGER, INTEGER) TO anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION swingtrader.get_relationship_node_sentiment(TEXT, INTEGER, INTEGER) TO anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION swingtrader.get_relationship_node_sentiment_windows(TEXT) TO anon, authenticated, service_role;
