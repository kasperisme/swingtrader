-- ---------------------------------------------------------------------------
-- Relationship side-panel RPC speedup (node news + sentiment)
--
-- Symptom: the /protected/relations side panel was still slow after the
-- neighborhood matview fix. On node-select it fires three RPCs in parallel;
-- measured for GM: get_relationship_node_news ~8.1s, get_relationship_node_sentiment
-- ~4.4s, get_relationship_node_sentiment_windows ~1.5s (aliases ~0.1s).
--
-- Two root causes, both fixed here:
--   1. The sentiment RPCs still read ticker_sentiment_heads_v — the un-materialized
--      view that re-explodes EVERY sentiment head per call. A materialized
--      `ticker_sentiment_heads` table (indexed on (ticker, article_ts)) already
--      exists (20260615120000) but these RPCs were never repointed. We repoint
--      them; node_sentiment LEFT JOINs news_articles to recover the article
--      metadata columns the table doesn't carry.
--   2. All three filter the underlying views with `ticker IN (SELECT ticker FROM
--      aliases)`. That subquery semi-join defeats predicate/index pushdown into
--      the exploded views, forcing a full materialization (a direct `ticker =
--      'GM'` on the same sources is 0.1–0.3s). We pre-aggregate the alias set into
--      a constant array and filter with `= ANY(alias_arr)`, which pushes down to
--      the indexes.
--
-- Pure read-path change — no schema/data changes, only CREATE OR REPLACE of three
-- STABLE SQL functions. Grants are preserved by REPLACE (re-granted for safety).
-- ---------------------------------------------------------------------------

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
alias_arr AS (SELECT array_agg(ticker) AS arr FROM aliases),
trace_rows AS (
  SELECT
    p.canonical_ticker,
    t.article_id,
    t.article_title AS title,
    t.article_url AS url,
    'traceability'::TEXT AS source,
    NULL::TEXT AS publisher,
    t.published_at,
    CASE WHEN t.from_ticker = p.canonical_ticker THEN p.canonical_ticker ELSE t.to_ticker END AS matched_ticker,
    0 AS precedence
  FROM swingtrader.ticker_relationship_edge_traceability_v t
  CROSS JOIN params p
  WHERE (
      t.from_ticker = ANY (COALESCE((SELECT arr FROM alias_arr), ARRAY[]::text[]))
      OR t.to_ticker = ANY (COALESCE((SELECT arr FROM alias_arr), ARRAY[]::text[]))
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
  JOIN swingtrader.news_articles na ON na.id = nat.article_id
  CROSS JOIN params p
  WHERE nat.ticker = ANY (COALESCE((SELECT arr FROM alias_arr), ARRAY[]::text[]))
    AND (p.cutoff IS NULL OR COALESCE(na.published_at, na.created_at) >= p.cutoff)
),
unioned AS (
  SELECT * FROM trace_rows
  UNION ALL
  SELECT * FROM mention_rows
),
deduped AS (
  SELECT DISTINCT ON (u.article_id)
    u.canonical_ticker, u.article_id, u.title, u.url, u.source, u.publisher, u.published_at, u.matched_ticker
  FROM unioned u
  ORDER BY u.article_id, u.precedence ASC, u.published_at DESC NULLS LAST
),
ranked AS (
  SELECT d.*, ROW_NUMBER() OVER (ORDER BY d.published_at DESC NULLS LAST, d.article_id DESC) AS rn
  FROM deduped d
)
SELECT r.canonical_ticker, r.article_id, r.title, r.url, r.source, r.publisher, r.published_at, r.matched_ticker
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
),
alias_arr AS (SELECT array_agg(ticker) AS arr FROM aliases),
sentiment_ranked AS (
  SELECT
    p.canonical_ticker,
    s.head_id,
    s.article_id,
    s.ticker,
    s.sentiment_score,
    s.reasoning_text,
    s.confidence,
    s.article_ts,
    COALESCE(na.published_at, na.created_at) AS published_at,
    na.source AS article_source,
    na.publisher AS article_publisher,
    na.title AS article_title,
    na.url AS article_url,
    ROW_NUMBER() OVER (ORDER BY s.article_ts DESC NULLS LAST, s.head_id DESC) AS rn
  FROM swingtrader.ticker_sentiment_heads s
  CROSS JOIN params p
  LEFT JOIN swingtrader.news_articles na ON na.id = s.article_id
  WHERE s.ticker = ANY (COALESCE((SELECT arr FROM alias_arr), ARRAY[]::text[]))
)
SELECT
  sr.canonical_ticker, sr.head_id, sr.article_id, sr.ticker, sr.sentiment_score,
  sr.reasoning_text, sr.confidence, sr.article_ts, sr.published_at,
  sr.article_source, sr.article_publisher, sr.article_title, sr.article_url
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
alias_arr AS (SELECT array_agg(ticker) AS arr FROM aliases),
window_defs AS (
  SELECT 10 AS days UNION ALL SELECT 21 UNION ALL SELECT 50 UNION ALL SELECT 200
),
base AS (
  SELECT
    s.sentiment_score,
    GREATEST(0.0, LEAST(1.0, COALESCE(s.confidence, 1.0))) AS confidence,
    s.article_ts
  FROM swingtrader.ticker_sentiment_heads s
  WHERE s.ticker = ANY (COALESCE((SELECT arr FROM alias_arr), ARRAY[]::text[]))
    AND s.article_ts >= NOW() - INTERVAL '200 days'
)
SELECT
  w.days,
  AVG(b.sentiment_score) FILTER (WHERE b.article_ts >= NOW() - ((w.days || ' days')::INTERVAL)) AS avg_sentiment,
  CASE
    WHEN SUM(b.confidence) FILTER (WHERE b.article_ts >= NOW() - ((w.days || ' days')::INTERVAL)) > 0
    THEN SUM(b.sentiment_score * b.confidence) FILTER (WHERE b.article_ts >= NOW() - ((w.days || ' days')::INTERVAL))
       / SUM(b.confidence) FILTER (WHERE b.article_ts >= NOW() - ((w.days || ' days')::INTERVAL))
    ELSE NULL
  END AS weighted_sentiment,
  COUNT(*) FILTER (WHERE b.article_ts >= NOW() - ((w.days || ' days')::INTERVAL))::INTEGER AS mention_count
FROM window_defs w
LEFT JOIN base b ON TRUE
GROUP BY w.days
ORDER BY w.days;
$$;

GRANT EXECUTE ON FUNCTION swingtrader.get_relationship_node_news(TEXT, INTEGER, INTEGER, INTEGER) TO anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION swingtrader.get_relationship_node_sentiment(TEXT, INTEGER, INTEGER) TO anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION swingtrader.get_relationship_node_sentiment_windows(TEXT) TO anon, authenticated, service_role;
