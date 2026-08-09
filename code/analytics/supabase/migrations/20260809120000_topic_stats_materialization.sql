-- ---------------------------------------------------------------------------
-- Materialize the topic headline counts.
--
-- getTopicStats ran an exact count over topic_article_v — the LIVE membership
-- view — for every topic on every render. Measured against the built app:
-- /quote (reads a materialized rollup) serves in ~0.10s while /topics and
-- /topics/[slug] take ~0.35s, and that count is the whole difference. It is also
-- the one query on the page that can time out, which is how a tracker with 791
-- stories could render "0 stories".
--
-- Only the COUNT moves. The feed stays live — it is `limit 24` off an indexed
-- view (~50ms) and being live is the point of it.
--
-- Refreshed inside exec_topic_claims_refresh so it rides the post-ingest step
-- that already exists; no new Python wiring, and the counts stay exactly as
-- fresh as the claim arcs shown next to them.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS swingtrader.topic_stats (
  topic_slug    TEXT PRIMARY KEY,
  article_count BIGINT NOT NULL,
  claim_count   BIGINT NOT NULL,
  first_seen    TIMESTAMPTZ,
  last_seen     TIMESTAMPTZ,
  refreshed_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE OR REPLACE FUNCTION swingtrader.refresh_topic_stats()
RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = swingtrader, pg_temp
AS $$
DECLARE
  v_count INTEGER := 0;
BEGIN
  DELETE FROM swingtrader.topic_stats WHERE TRUE;  -- safeupdate needs a WHERE

  INSERT INTO swingtrader.topic_stats
    (topic_slug, article_count, claim_count, first_seen, last_seen)
  SELECT
    t.slug,
    COALESCE(a.n, 0),
    COALESCE(c.n, 0),
    c.first_seen,
    c.last_seen
  FROM swingtrader.topics t
  LEFT JOIN (
    SELECT topic_slug, count(*) AS n
    FROM swingtrader.topic_article_v
    GROUP BY topic_slug
  ) a ON a.topic_slug = t.slug
  LEFT JOIN (
    SELECT topic_slug,
           count(*) AS n,
           min(article_ts) AS first_seen,
           max(article_ts) AS last_seen
    FROM swingtrader.topic_claim_stats
    GROUP BY topic_slug
  ) c ON c.topic_slug = t.slug;

  GET DIAGNOSTICS v_count = ROW_COUNT;
  RETURN v_count;
END;
$$;

-- Fold into the existing post-ingest entry point. The counts describe the same
-- corpus the arcs are built from, so they must be rebuilt in the same step —
-- refreshing one without the other is how the two disagree.
CREATE OR REPLACE FUNCTION swingtrader.exec_topic_claims_refresh()
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = swingtrader, pg_temp
AS $$
BEGIN
  PERFORM swingtrader.refresh_topic_claims(NULL);
  PERFORM swingtrader.refresh_topic_stats();
END;
$$;

ALTER FUNCTION swingtrader.exec_topic_claims_refresh() SET statement_timeout = '300s';
ALTER FUNCTION swingtrader.exec_topic_claims_refresh() SET lock_timeout = '30s';

ALTER TABLE swingtrader.topic_stats ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Public read topic stats" ON swingtrader.topic_stats;
CREATE POLICY "Public read topic stats" ON swingtrader.topic_stats
  FOR SELECT TO anon, authenticated USING (true);

GRANT SELECT ON swingtrader.topic_stats TO anon, authenticated, service_role;

REVOKE ALL ON FUNCTION swingtrader.refresh_topic_stats() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION swingtrader.refresh_topic_stats() TO service_role;

-- Initial build so the pages have counts before the next ingest.
SELECT swingtrader.refresh_topic_stats();
