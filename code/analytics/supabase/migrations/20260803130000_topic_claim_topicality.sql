-- ---------------------------------------------------------------------------
-- Claim-level topicality gate.
--
-- The article-level AND gate (theme tag AND lens ticker) admits the right
-- ARTICLES, but an admitted article can still contain claims about something
-- else entirely. Observed immediately on the first build of
-- iran-conflict-oil-market:
--
--   [+0.60] 2026-08-03  "Berkshire Hathaway significantly increased its stake in
--                        Alphabet through open market purchases and a $10B …"
--
-- The article qualified (it discusses Berkshire trimming Chevron, and carries an
-- oil tag) but this particular claim is about Alphabet. On a permanent page built
-- to rank, off-topic claims are worse than useless — they dilute the exact topical
-- authority the hub exists to build.
--
-- So a claim must ALSO mention the topic: a theme word, a lens ticker (word-bounded,
-- so "GD"/"BA" can't match inside another word), or a lens company's name. The
-- Berkshire/Chevron claim survives (it names Chevron); the Alphabet one does not.
-- ---------------------------------------------------------------------------

ALTER TABLE swingtrader.topics
  ADD COLUMN IF NOT EXISTS extra_keywords TEXT[] NOT NULL DEFAULT '{}';

COMMENT ON COLUMN swingtrader.topics.extra_keywords IS
  'Additional claim-level topicality terms beyond theme_tags + lens tickers/company names '
  '(e.g. crude, brent, opec, tanker). Substring-matched, case-insensitive.';

-- Company names for the lens, corporate suffixes stripped so the match is the
-- distinctive part: "The Boeing Company" → "Boeing", "Exxon Mobil Corporation" →
-- "Exxon Mobil". Keeping both words matters — the bare first token of "General
-- Dynamics Corporation" is "General", which would match almost anything.
CREATE OR REPLACE FUNCTION swingtrader.topic_keywords(p_slug TEXT)
RETURNS TEXT[]
LANGUAGE sql
STABLE
SET search_path = swingtrader, pg_temp
AS $$
  SELECT ARRAY(
    SELECT DISTINCT LOWER(BTRIM(k)) FROM (
      -- theme tags, underscores → spaces  (strait_of_hormuz → "strait of hormuz")
      SELECT REPLACE(UNNEST(t.theme_tags), '_', ' ') AS k FROM swingtrader.topics t WHERE t.slug = p_slug
      UNION ALL
      SELECT UNNEST(t.extra_keywords) FROM swingtrader.topics t WHERE t.slug = p_slug
      UNION ALL
      SELECT BTRIM(regexp_replace(
               sim.canonical_company_name,
               '\s+(Corporation|Corp\.?|Company|Incorporated|Inc\.?|N\.V\.|plc|PLC|Ltd\.?|Holdings|Group)\s*$',
               '', 'gi'))
      FROM swingtrader.topics t
      JOIN swingtrader.security_identity_map sim
        ON sim.canonical_ticker = ANY(t.lens_tickers)
      WHERE t.slug = p_slug AND sim.canonical_company_name IS NOT NULL
    ) s
    WHERE LENGTH(BTRIM(k)) >= 3
      AND LOWER(BTRIM(k)) NOT IN ('the','general','company','group','holdings')
  );
$$;

CREATE OR REPLACE FUNCTION swingtrader.refresh_topic_claims(p_slug TEXT DEFAULT NULL)
RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = swingtrader, pg_temp
AS $$
DECLARE
  v_count INTEGER := 0;
BEGIN
  IF p_slug IS NULL THEN
    DELETE FROM swingtrader.topic_claim_stats WHERE TRUE;   -- safeupdate needs a WHERE
  ELSE
    DELETE FROM swingtrader.topic_claim_stats WHERE topic_slug = p_slug;
  END IF;

  WITH scoped AS (
    SELECT t.slug, t.min_impact, t.lens_tickers,
           swingtrader.topic_keywords(t.slug) AS kw,
           a.id AS article_id, a.title, a.slug AS article_slug,
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
           s.article_slug, s.article_ts, s.tickers, s.min_impact, s.kw, s.lens_tickers,
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
    FROM exploded e
    WHERE impact IS NOT NULL
      AND ABS(impact) >= min_impact
      AND LENGTH(claim) >= 25
      AND (
        -- theme word / company name: plain case-insensitive substring
        EXISTS (SELECT 1 FROM unnest(e.kw) k WHERE e.claim ILIKE '%' || k || '%')
        -- ticker symbol: word-bounded so GD/BA/USO can't match mid-word
        OR EXISTS (SELECT 1 FROM unnest(e.lens_tickers) tk
                   WHERE e.claim ~ ('\m' || tk || '\M'))
      )
    ON CONFLICT (topic_slug, article_id, claim_key) DO UPDATE SET
      claim = EXCLUDED.claim, impact = EXCLUDED.impact,
      article_ts = EXCLUDED.article_ts, updated_at = NOW()
    RETURNING 1
  )
  SELECT COUNT(*) INTO v_count FROM inserted;
  RETURN v_count;
END;
$$;

REVOKE ALL ON FUNCTION swingtrader.refresh_topic_claims(TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION swingtrader.refresh_topic_claims(TEXT) TO service_role;
GRANT EXECUTE ON FUNCTION swingtrader.topic_keywords(TEXT) TO service_role, anon, authenticated;

UPDATE swingtrader.topics SET extra_keywords =
  ARRAY['crude','brent','wti','opec','tanker','barrel','refinery','refining','diesel','gasoline','petroleum','energy']
WHERE slug = 'iran-conflict-oil-market';

UPDATE swingtrader.topics SET extra_keywords =
  ARRAY['defense','defence','missile','munition','fighter jet','military','pentagon','weapons','aerospace','interceptor']
WHERE slug = 'iran-conflict-defence-stocks';
