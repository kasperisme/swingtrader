-- ---------------------------------------------------------------------------
-- news_articles.has_analysis — hide articles the scorer found nothing in
--
-- Why: 15.5% of the corpus (35,554 of 229,633 on 2026-09-11) was scored and came
-- back with no claim and no ticker verdict. They are paywalled teasers — Seeking
-- Alpha transcripts, WSJ / Barron's pieces — whose feed body is ~100 chars
-- (scored articles: ~4,700). The page for one is a headline and some tags, yet
-- The Tape, related articles, topic hubs, tag search, semantic search and the
-- agents' RAG all served them, and Bing reported 88 of them for thin meta
-- descriptions. sitemap_article_urls already leaves them out; this makes every
-- other read path agree.
--
-- Semantics (three-valued on purpose):
--   true   at least one claim (STORY_KEY_POINTS reasoning) or ticker verdict
--          (TICKER_SENTIMENT scores)
--   false  scored — heads exist — and neither is present
--   null   not scored yet (or scoring failed before any head was written)
-- Read paths filter `has_analysis IS NOT FALSE`: only the known-empty set is
-- hidden, so an article is never dropped for being late to the scorer, and this
-- migration is correct before its backfill has run.
--
-- Maintenance: statement-level triggers on news_impact_heads recompute the flag
-- for exactly the articles a statement touched. Unlike the relationship-graph
-- triggers that were deferred off the write path (20260526120000) — those ran a
-- full-table refresh per statement — this is one indexed UPDATE of the ~1
-- article an ingest statement writes. The ingester deletes heads before a
-- re-score, so the flag passes through null and lands on the new verdict.
--
-- Backfill is NOT in this migration: a 227k-row UPDATE in the same transaction
-- as the ALTER would hold news_articles' ACCESS EXCLUSIVE lock for its whole
-- run and stall every article read on the site. Run afterwards, in batches:
--   select swingtrader.sync_article_has_analysis(array(
--     select id from swingtrader.news_articles where id between $lo and $hi));
-- ---------------------------------------------------------------------------

SET lock_timeout = '5s';

ALTER TABLE swingtrader.news_articles
  ADD COLUMN IF NOT EXISTS has_analysis boolean;

COMMENT ON COLUMN swingtrader.news_articles.has_analysis IS
  'true = has a claim or ticker verdict; false = scored, found neither; null = '
  'not scored. Maintained by triggers on news_impact_heads. Read paths filter '
  'has_analysis IS NOT FALSE.';

RESET lock_timeout;

-- The one definition of "this head carries analysis" — the backfill and the
-- triggers both go through it, and it mirrors the article page's own reads
-- (firstClaimSummary / primaryTickerSentiment in app/articles/[slug]/page.tsx).
CREATE OR REPLACE FUNCTION swingtrader.head_carries_analysis(
  p_cluster text, p_scores jsonb, p_reasoning jsonb
)
RETURNS boolean
LANGUAGE sql
IMMUTABLE
AS $$
  SELECT CASE p_cluster
    WHEN 'STORY_KEY_POINTS' THEN
      jsonb_typeof(p_reasoning) = 'object'
      AND EXISTS (SELECT 1 FROM jsonb_each_text(p_reasoning) e WHERE btrim(e.value) <> '')
    WHEN 'TICKER_SENTIMENT' THEN
      jsonb_typeof(p_scores) = 'object' AND p_scores <> '{}'::jsonb
    ELSE false
  END;
$$;

-- Recompute the flag for a set of articles. bool_or over zero heads is null,
-- which is exactly "not scored".
CREATE OR REPLACE FUNCTION swingtrader.sync_article_has_analysis(p_article_ids bigint[])
RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'swingtrader', 'pg_temp'
AS $$
DECLARE
  v_count integer;
BEGIN
  UPDATE swingtrader.news_articles a
  SET has_analysis = s.v
  FROM (
    SELECT ids.id,
           (SELECT bool_or(swingtrader.head_carries_analysis(h.cluster, h.scores_json, h.reasoning_json))
              FROM swingtrader.news_impact_heads h
             WHERE h.article_id = ids.id) AS v
    FROM (SELECT DISTINCT unnest(p_article_ids) AS id) ids
  ) s
  WHERE a.id = s.id
    AND a.has_analysis IS DISTINCT FROM s.v;
  GET DIAGNOSTICS v_count = ROW_COUNT;
  RETURN v_count;
END;
$$;

REVOKE ALL ON FUNCTION swingtrader.sync_article_has_analysis(bigint[]) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION swingtrader.sync_article_has_analysis(bigint[]) TO service_role;

-- Transition tables cannot be shared across INSERT/UPDATE/DELETE on one trigger
-- (0A000), hence three.
CREATE OR REPLACE FUNCTION swingtrader.trg_stmt_nih_has_analysis_ins()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path TO 'swingtrader', 'pg_temp'
AS $$
BEGIN
  PERFORM swingtrader.sync_article_has_analysis(ARRAY(SELECT DISTINCT article_id FROM new_rows));
  RETURN NULL;
END;
$$;

CREATE OR REPLACE FUNCTION swingtrader.trg_stmt_nih_has_analysis_upd()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path TO 'swingtrader', 'pg_temp'
AS $$
BEGIN
  PERFORM swingtrader.sync_article_has_analysis(ARRAY(
    SELECT article_id FROM new_rows UNION SELECT article_id FROM old_rows));
  RETURN NULL;
END;
$$;

CREATE OR REPLACE FUNCTION swingtrader.trg_stmt_nih_has_analysis_del()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path TO 'swingtrader', 'pg_temp'
AS $$
BEGIN
  PERFORM swingtrader.sync_article_has_analysis(ARRAY(SELECT DISTINCT article_id FROM old_rows));
  RETURN NULL;
END;
$$;

REVOKE ALL ON FUNCTION swingtrader.trg_stmt_nih_has_analysis_ins() FROM PUBLIC;
REVOKE ALL ON FUNCTION swingtrader.trg_stmt_nih_has_analysis_upd() FROM PUBLIC;
REVOKE ALL ON FUNCTION swingtrader.trg_stmt_nih_has_analysis_del() FROM PUBLIC;

DROP TRIGGER IF EXISTS trg_nih_has_analysis_ins ON swingtrader.news_impact_heads;
CREATE TRIGGER trg_nih_has_analysis_ins
  AFTER INSERT ON swingtrader.news_impact_heads
  REFERENCING NEW TABLE AS new_rows
  FOR EACH STATEMENT EXECUTE FUNCTION swingtrader.trg_stmt_nih_has_analysis_ins();

DROP TRIGGER IF EXISTS trg_nih_has_analysis_upd ON swingtrader.news_impact_heads;
CREATE TRIGGER trg_nih_has_analysis_upd
  AFTER UPDATE ON swingtrader.news_impact_heads
  REFERENCING OLD TABLE AS old_rows NEW TABLE AS new_rows
  FOR EACH STATEMENT EXECUTE FUNCTION swingtrader.trg_stmt_nih_has_analysis_upd();

DROP TRIGGER IF EXISTS trg_nih_has_analysis_del ON swingtrader.news_impact_heads;
CREATE TRIGGER trg_nih_has_analysis_del
  AFTER DELETE ON swingtrader.news_impact_heads
  REFERENCING OLD TABLE AS old_rows
  FOR EACH STATEMENT EXECUTE FUNCTION swingtrader.trg_stmt_nih_has_analysis_del();

-- ---------------------------------------------------------------------------
-- Read paths. Each body below is the live definition (pg_get_functiondef /
-- pg_get_viewdef, 2026-09-11) with one added predicate: has_analysis IS NOT FALSE.
--
-- Deliberately unchanged, because they cannot return an empty article:
--   get_ticker_impact_news, get_relationship_node_sentiment,
--   ticker_sentiment_heads_v, news_trends_ticker_daily_v — driven by
--   ticker_sentiment_heads; refresh_topic_claims — driven by claims;
--   refresh_sitemap_article_urls — requires a covered ticker's sentiment head.
--   search_news_article_embeddings_gte — reads news_article_embeddings_gte, a
--   table that no longer exists; the function already fails on every call.
-- news_trends_article_base_v (40 dependent views) keeps its columns exactly, so
-- CREATE OR REPLACE leaves the dependents intact.
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION swingtrader.search_news_by_tags(tag_filter text[], match_count integer DEFAULT 20, lookback_hours integer DEFAULT 2160, stream_filter text DEFAULT NULL::text)
 RETURNS TABLE(article_id bigint, title text, url text, source text, slug text, image_url text, article_stream text, published_at timestamp with time zone, snippet text, similarity double precision)
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO 'swingtrader', 'public'
AS $function$
    SELECT
        a.id AS article_id,
        a.title,
        a.url,
        a.source,
        a.slug,
        a.image_url,
        a.article_stream,
        a.published_at,
        left(a.body, 280) AS snippet,
        1.0::double precision AS similarity
    FROM swingtrader.news_articles a
    WHERE cardinality(COALESCE(tag_filter, ARRAY[]::text[])) > 0
      AND a.search_tags && tag_filter
      AND a.has_analysis IS NOT FALSE
      AND (
          lookback_hours IS NULL
          OR lookback_hours <= 0
          OR a.published_at IS NULL
          OR a.published_at >= NOW() - (lookback_hours || ' hours')::interval
      )
      AND (
          stream_filter IS NULL
          OR btrim(stream_filter) = ''
          OR a.article_stream = stream_filter
      )
    ORDER BY a.published_at DESC NULLS LAST, a.id DESC
    LIMIT GREATEST(1, LEAST(match_count, 100));
$function$;

CREATE OR REPLACE FUNCTION swingtrader.search_news_fulltext(query_text text, match_count integer DEFAULT 20, lookback_hours integer DEFAULT 2160, stream_filter text DEFAULT NULL::text)
 RETURNS TABLE(article_id bigint, title text, url text, source text, slug text, image_url text, article_stream text, published_at timestamp with time zone, snippet text, similarity double precision)
 LANGUAGE plpgsql
 STABLE SECURITY DEFINER
 SET search_path TO 'swingtrader', 'public'
AS $function$
DECLARE
    or_query text; ts_q tsquery;
    candidate_cap constant integer := 2000;
BEGIN
    SELECT string_agg(lexeme, ' | ') INTO or_query
      FROM unnest(to_tsvector('english', coalesce(query_text, '')));
    IF or_query IS NULL OR btrim(or_query) = '' THEN RETURN; END IF;
    ts_q := to_tsquery('english', or_query);
    RETURN QUERY
    WITH cand AS (
        SELECT a.id FROM swingtrader.news_articles a
        WHERE a.fts @@ ts_q
          AND a.has_analysis IS NOT FALSE
          AND (lookback_hours IS NULL OR lookback_hours <= 0 OR a.published_at IS NULL
               OR a.published_at >= NOW() - (lookback_hours || ' hours')::interval)
          AND (stream_filter IS NULL OR btrim(stream_filter) = '' OR a.article_stream = stream_filter)
        ORDER BY a.published_at DESC NULLS LAST, a.id DESC
        LIMIT candidate_cap
    )
    SELECT a.id, a.title::text, a.url::text, a.source::text, a.slug::text,
        a.image_url, a.article_stream, a.published_at,
        left(a.body, 280) AS snippet,
        ts_rank_cd(a.fts, ts_q)::double precision
    FROM cand JOIN swingtrader.news_articles a ON a.id = cand.id
    ORDER BY ts_rank_cd(a.fts, ts_q) DESC, a.published_at DESC NULLS LAST, a.id DESC
    LIMIT GREATEST(1, LEAST(match_count, 100));
END;
$function$;

CREATE OR REPLACE FUNCTION swingtrader.search_news_embeddings(query_embedding double precision[], match_count integer DEFAULT 20, lookback_hours integer DEFAULT 24, stream_filter text DEFAULT NULL::text, ticker_filter text[] DEFAULT NULL::text[], as_of timestamp with time zone DEFAULT NULL::timestamp with time zone)
 RETURNS TABLE(article_id bigint, title text, url text, source text, slug text, image_url text, article_stream text, published_at timestamp with time zone, snippet text, similarity double precision)
 LANGUAGE plpgsql
 STABLE SECURITY DEFINER
 SET search_path TO 'swingtrader', 'public', 'extensions'
 SET statement_timeout TO '60s'
AS $function$
DECLARE
  win_end   timestamptz := COALESCE(as_of, NOW());
  win_start timestamptz := COALESCE(as_of, NOW())
                           - make_interval(hours => GREATEST(1, lookback_hours));
  -- Over-fetch so the stream and ticker filters below still have candidates
  -- after they cut the set down.
  cap       integer := GREATEST(40, GREATEST(1, match_count) * 4);
BEGIN
  RETURN QUERY EXECUTE format($q$
    WITH raw_candidates AS MATERIALIZED (
      SELECT
        e.article_id,
        e.chunk_text,
        e.published_at,
        1 - (e.embedding <=> $1) AS similarity
      FROM swingtrader.news_article_embeddings e
      WHERE e.published_at >= %1$L::timestamptz
        AND e.published_at <= %2$L::timestamptz
      ORDER BY e.embedding <=> $1
      LIMIT %3$s
    ),
    tf AS (
      SELECT array_agg(DISTINCT upper(t)) AS tickers
      FROM unnest(COALESCE($2, ARRAY[]::text[])) AS t
      WHERE t IS NOT NULL AND length(t) > 0
    ),
    candidate_ids_passing_ticker AS (
      SELECT DISTINCT nat.article_id AS aid
      FROM swingtrader.news_article_tickers nat, tf
      WHERE tf.tickers IS NOT NULL
        AND nat.article_id IN (SELECT rc.article_id FROM raw_candidates rc)
        AND nat.ticker = ANY(tf.tickers)
    )
    SELECT
      na.id AS article_id,
      na.title::text,
      na.url::text,
      na.source::text,
      na.slug::text,
      na.image_url::text,
      na.article_stream::text,
      COALESCE(na.published_at, na.created_at) AS published_at,
      c.chunk_text AS snippet,
      c.similarity
    FROM raw_candidates c
    JOIN swingtrader.news_articles na ON na.id = c.article_id
    WHERE na.has_analysis IS NOT FALSE
      AND ($3::text IS NULL OR na.article_stream = $3::text)
      AND (
        $2 IS NULL
        OR cardinality(COALESCE($2, ARRAY[]::text[])) = 0
        OR c.article_id IN (SELECT cipt.aid FROM candidate_ids_passing_ticker cipt)
      )
    ORDER BY c.similarity DESC
    LIMIT %4$s
  $q$, win_start, win_end, cap, GREATEST(1, match_count))
  USING query_embedding::vector(1024), ticker_filter, stream_filter;
END;
$function$;

CREATE OR REPLACE FUNCTION swingtrader.get_relationship_node_news(p_ticker text, p_page integer DEFAULT 1, p_page_size integer DEFAULT 10, p_days_lookback integer DEFAULT NULL::integer)
 RETURNS TABLE(canonical_ticker text, article_id bigint, title text, url text, source text, publisher text, published_at timestamp with time zone, matched_ticker text)
 LANGUAGE sql
 STABLE
AS $function$
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
    AND na.has_analysis IS NOT FALSE
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
$function$;

CREATE OR REPLACE VIEW swingtrader.topic_article_v AS
 SELECT t.slug AS topic_slug,
    a.id AS article_id,
    a.title,
    a.slug AS article_slug,
    a.published_at,
    a.search_tags,
    ARRAY( SELECT DISTINCT nat.ticker
           FROM swingtrader.news_article_tickers nat
          WHERE nat.article_id = a.id AND (nat.ticker::text = ANY (t.lens_tickers))) AS matched_tickers
   FROM swingtrader.topics t
     JOIN swingtrader.news_articles a ON a.search_tags && t.theme_tags
  WHERE t.is_published AND a.has_analysis IS NOT FALSE AND (EXISTS ( SELECT 1
           FROM swingtrader.news_article_tickers nat
          WHERE nat.article_id = a.id AND (nat.ticker::text = ANY (t.lens_tickers))));

CREATE OR REPLACE VIEW swingtrader.news_trends_tag_daily_v AS
 SELECT date_trunc('day'::text, COALESCE(a.published_at, a.created_at))::date AS bucket_day,
    tag.tag,
    count(*) AS article_count
   FROM swingtrader.news_articles a
     CROSS JOIN LATERAL unnest(a.search_tags) tag(tag)
  WHERE COALESCE(a.published_at, a.created_at) >= (now() - '120 days'::interval) AND a.processing_status IS DISTINCT FROM 'failed'::text AND a.has_analysis IS NOT FALSE AND tag.tag = lower(tag.tag) AND length(tag.tag) >= 2
  GROUP BY (date_trunc('day'::text, COALESCE(a.published_at, a.created_at))::date), tag.tag;

CREATE OR REPLACE VIEW swingtrader.news_trends_article_base_v AS
 WITH head_confidence AS (
         SELECT news_impact_heads.article_id,
            avg(news_impact_heads.confidence) AS confidence_mean
           FROM swingtrader.news_impact_heads
          GROUP BY news_impact_heads.article_id
        )
 SELECT niv.article_id,
    COALESCE(na.published_at, niv.created_at) AS published_at,
    date_trunc('day'::text, COALESCE(na.published_at, niv.created_at)) AS bucket_day,
    date_trunc('hour'::text, COALESCE(na.published_at, niv.created_at)) AS bucket_hour,
    niv.impact_json AS impact_jsonb,
    hc.confidence_mean,
    na.id,
    na.title,
    na.url,
    na.source,
    na.slug,
    na.image_url,
    na.created_at AS article_created_at
   FROM swingtrader.news_impact_vectors niv
     LEFT JOIN swingtrader.news_articles na ON na.id = niv.article_id
     LEFT JOIN head_confidence hc ON hc.article_id = niv.article_id
  WHERE na.has_analysis IS NOT FALSE;
