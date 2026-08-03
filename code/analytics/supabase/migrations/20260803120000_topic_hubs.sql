-- ---------------------------------------------------------------------------
-- Topic hubs — permanent, auto-updating deep-dive pages over the scraped corpus.
--
-- The idea: /articles publishes ~5k single-news-item URLs that rank for nothing
-- (Search Console: 20 impressions, 0 clicks, avg position 24 over a week). Thin
-- spokes don't earn topical authority; a small number of deep hubs can. A topic
-- consolidates many articles into one evergreen page carrying the whole arc of a
-- story — e.g. 15 months of the Iran conflict against the oil complex.
--
-- A topic is a SAVED QUERY, not generated content:
--   theme_tags  (what the story is)  AND  lens_tickers (who it hits)
-- Membership is therefore automatic — a newly-scored article joins the moment it
-- matches, with no sync job. That's what makes the page live rather than a
-- snapshot pretending to be live.
--
-- AND, never OR: requiring both gates is what keeps a securities-class-action
-- story about WIX out of an AI topic (the trend radar's ranking did exactly that
-- when only one gate applied).
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS swingtrader.topics (
  slug              TEXT PRIMARY KEY,
  title             TEXT        NOT NULL,
  subtitle          TEXT,
  -- The saved query.
  theme_tags        TEXT[]      NOT NULL,
  lens_tickers      TEXT[]      NOT NULL,
  -- Noise floor: a claim must carry at least this |impact| to reach the page.
  min_impact        REAL        NOT NULL DEFAULT 0.4,
  -- Visual identity (see nis-ad-image's SCENE_PRESETS / archetype library).
  visual_archetype  TEXT        NOT NULL DEFAULT 'price_timeline',
  scene             TEXT,
  accent            TEXT        NOT NULL DEFAULT 'amber',
  hero_tickers      TEXT[],
  -- Editorial layer (Sanity doc id) — the thesis a query can't derive.
  thesis_ref        TEXT,
  seo_description   TEXT,
  is_published      BOOLEAN     NOT NULL DEFAULT FALSE,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Membership is an array-overlap on tags + a ticker join. GIN on search_tags is
-- what keeps the live feed at ~30ms over 185k articles.
CREATE INDEX IF NOT EXISTS idx_news_articles_search_tags_gin
  ON swingtrader.news_articles USING GIN (search_tags);

CREATE INDEX IF NOT EXISTS idx_news_article_tickers_ticker
  ON swingtrader.news_article_tickers (ticker, article_id);

-- ---------------------------------------------------------------------------
-- topic_article_v — the membership query, as a view.
--
-- Deliberately NOT materialized: it resolves in ~30ms and materializing it would
-- reintroduce the staleness the whole design exists to avoid. The heavy rollups
-- (15-month arcs) are materialized separately below.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW swingtrader.topic_article_v AS
SELECT
  t.slug            AS topic_slug,
  a.id              AS article_id,
  a.title,
  a.slug            AS article_slug,
  a.published_at,
  a.search_tags,
  ARRAY(SELECT DISTINCT nat.ticker
        FROM swingtrader.news_article_tickers nat
        WHERE nat.article_id = a.id
          AND nat.ticker = ANY(t.lens_tickers)) AS matched_tickers
FROM swingtrader.topics t
JOIN swingtrader.news_articles a
  ON a.search_tags && t.theme_tags
WHERE t.is_published
  AND EXISTS (SELECT 1 FROM swingtrader.news_article_tickers nat
              WHERE nat.article_id = a.id
                AND nat.ticker = ANY(t.lens_tickers));

-- ---------------------------------------------------------------------------
-- topic_claim_stats — the materialized half.
--
-- Ranked STORY_KEY_POINTS across a topic's whole arc. This CANNOT be live: it
-- scans every matching article's heads, and the REST role (`authenticator`) caps
-- statements at 8s. Refreshed after each ingest, exactly like
-- ticker_sentiment_heads / ticker_relationship_edges.
--
-- Every claim keeps `article_ts`. A permanent page that aggregates claims will
-- otherwise enshrine stale numbers as evergreen fact — observed repeatedly:
-- NVIDIA "$119B supply commitments / $91B guide" (pre-quarter, reports Aug 26)
-- and Micron "+346% to $41.46B" (a prior quarter) both resurfaced as current.
-- The date is what lets the page demote them out of the headline block.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS swingtrader.topic_claim_stats (
  topic_slug    TEXT        NOT NULL,
  article_id    BIGINT      NOT NULL,
  claim_key     TEXT        NOT NULL,
  claim         TEXT        NOT NULL,
  impact        REAL        NOT NULL,
  article_ts    TIMESTAMPTZ NOT NULL,
  article_title TEXT,
  article_slug  TEXT,
  tickers       TEXT[],
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT topic_claim_stats_pk PRIMARY KEY (topic_slug, article_id, claim_key)
);

CREATE INDEX IF NOT EXISTS idx_topic_claim_stats_rank
  ON swingtrader.topic_claim_stats (topic_slug, article_ts DESC);
CREATE INDEX IF NOT EXISTS idx_topic_claim_stats_impact
  ON swingtrader.topic_claim_stats (topic_slug, impact DESC);

CREATE OR REPLACE FUNCTION swingtrader.refresh_topic_claims(p_slug TEXT DEFAULT NULL)
RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = swingtrader, pg_temp
AS $$
DECLARE
  v_count INTEGER := 0;
BEGIN
  -- WHERE TRUE is load-bearing: `safeupdate` is preloaded into REST sessions and
  -- rejects an unqualified DELETE with 21000.
  IF p_slug IS NULL THEN
    DELETE FROM swingtrader.topic_claim_stats WHERE TRUE;
  ELSE
    DELETE FROM swingtrader.topic_claim_stats WHERE topic_slug = p_slug;
  END IF;

  WITH scoped AS (
    SELECT t.slug, t.min_impact, a.id AS article_id, a.title, a.slug AS article_slug,
           COALESCE(a.published_at, a.created_at) AS article_ts,
           ARRAY(SELECT DISTINCT nat.ticker
                 FROM swingtrader.news_article_tickers nat
                 WHERE nat.article_id = a.id
                   AND nat.ticker = ANY(t.lens_tickers)) AS tickers
    FROM swingtrader.topics t
    JOIN swingtrader.news_articles a
      ON a.search_tags && t.theme_tags
    WHERE (p_slug IS NULL OR t.slug = p_slug)
      AND EXISTS (SELECT 1 FROM swingtrader.news_article_tickers nat
                  WHERE nat.article_id = a.id
                    AND nat.ticker = ANY(t.lens_tickers))
  ),
  exploded AS (
    SELECT s.slug AS topic_slug, s.article_id, s.title AS article_title,
           s.article_slug, s.article_ts, s.tickers, s.min_impact,
           kv.key AS claim_key,
           BTRIM(SPLIT_PART(COALESCE(h.reasoning_json::jsonb ->> kv.key, ''), ' — ', 1)) AS claim,
           CASE WHEN kv.value ~ '^-?[0-9]+(\.[0-9]+)?$'
                THEN kv.value::REAL ELSE NULL END AS impact
    FROM scoped s
    JOIN swingtrader.news_impact_heads h
      ON h.article_id = s.article_id AND h.cluster = 'STORY_KEY_POINTS'
    CROSS JOIN LATERAL jsonb_each_text(
      CASE WHEN jsonb_typeof(h.scores_json::jsonb) = 'object'
           THEN h.scores_json::jsonb ELSE '{}'::jsonb END
    ) AS kv(key, value)
  ),
  inserted AS (
    INSERT INTO swingtrader.topic_claim_stats
      (topic_slug, article_id, claim_key, claim, impact, article_ts,
       article_title, article_slug, tickers)
    SELECT topic_slug, article_id, claim_key, claim, impact, article_ts,
           article_title, article_slug, tickers
    FROM exploded
    WHERE impact IS NOT NULL
      AND ABS(impact) >= min_impact
      AND LENGTH(claim) >= 25          -- drops stubs like "The company is facing borrowing constraints."
    ON CONFLICT (topic_slug, article_id, claim_key) DO UPDATE SET
      claim = EXCLUDED.claim, impact = EXCLUDED.impact,
      article_ts = EXCLUDED.article_ts, updated_at = NOW()
    RETURNING 1
  )
  SELECT COUNT(*) INTO v_count FROM inserted;
  RETURN v_count;
END;
$$;

CREATE OR REPLACE FUNCTION swingtrader.exec_topic_claims_refresh()
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = swingtrader, pg_temp
AS $$
BEGIN
  PERFORM swingtrader.refresh_topic_claims(NULL);
END;
$$;

-- Batch budget, same rationale as the other post-ingest refresh RPCs: the REST
-- role carries statement_timeout=8s, which a full-arc rebuild cannot meet. A
-- function-level SET overrides it for this function only.
ALTER FUNCTION swingtrader.exec_topic_claims_refresh() SET statement_timeout = '300s';
ALTER FUNCTION swingtrader.exec_topic_claims_refresh() SET lock_timeout = '30s';

REVOKE ALL ON FUNCTION swingtrader.refresh_topic_claims(TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION swingtrader.exec_topic_claims_refresh() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION swingtrader.refresh_topic_claims(TEXT) TO service_role;
GRANT EXECUTE ON FUNCTION swingtrader.exec_topic_claims_refresh() TO service_role;

-- RLS mirrors the sibling materializations: service_role bypasses, anon+auth read.
ALTER TABLE swingtrader.topics ENABLE ROW LEVEL SECURITY;
ALTER TABLE swingtrader.topic_claim_stats ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Public read published topics" ON swingtrader.topics;
CREATE POLICY "Public read published topics" ON swingtrader.topics
  FOR SELECT TO anon, authenticated USING (is_published);

DROP POLICY IF EXISTS "Public read topic claims" ON swingtrader.topic_claim_stats;
CREATE POLICY "Public read topic claims" ON swingtrader.topic_claim_stats
  FOR SELECT TO anon, authenticated USING (true);

GRANT SELECT ON swingtrader.topics             TO anon, authenticated, service_role;
GRANT SELECT ON swingtrader.topic_claim_stats  TO anon, authenticated, service_role;
GRANT SELECT ON swingtrader.topic_article_v    TO anon, authenticated, service_role;

-- ── seed: the two Iran lenses ────────────────────────────────────────────────
INSERT INTO swingtrader.topics
  (slug, title, subtitle, theme_tags, lens_tickers, visual_archetype, scene, accent,
   hero_tickers, seo_description, is_published)
VALUES
  ('iran-conflict-oil-market',
   'Iran Conflict: Effect on the Oil Market',
   'Every escalation, and what crude and the majors actually did',
   ARRAY['iran','geopolitics','strait_of_hormuz','middle_east','oil'],
   ARRAY['CVX','XOM','COP','OXY','SLB','USO','HAL','MPC'],
   'price_timeline', 'tanker', 'amber',
   ARRAY['USO','XOM','CVX'],
   'A live tracker of the Iran conflict''s effect on oil: crude prices, the majors, and the scored market impact of every escalation, updated as news lands.',
   TRUE),
  ('iran-conflict-defence-stocks',
   'Iran Conflict: Effect on Defence Stocks',
   'How the defence complex reprices on escalation',
   ARRAY['iran','geopolitics','strait_of_hormuz','middle_east','defense','defence'],
   ARRAY['LMT','RTX','GD','NOC','BA','HII','LDOS','TDG'],
   'price_timeline', 'tanker', 'steel',
   ARRAY['LMT','RTX','NOC'],
   'A live tracker of the Iran conflict''s effect on defence stocks: Lockheed, RTX, Northrop and peers, with the scored market impact of every escalation.',
   TRUE)
ON CONFLICT (slug) DO NOTHING;
