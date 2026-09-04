-- ---------------------------------------------------------------------------
-- search_news_embeddings: filter by time BEFORE the vector search
--
-- The bug:
-- - `raw_candidates` took the 40 nearest vectors across the ENTIRE corpus
--   (1.85M rows), and `lookback_hours` was applied afterwards, in the outer
--   WHERE. So every call — even a 24-hour search — scanned all 1.85M vectors
--   and then discarded almost everything it found.
--
-- - It is a correctness bug as much as a performance one. A 24h search returned
--   whichever of the GLOBAL top-40 happened to be recent, which is usually one
--   or two rows and sometimes none — not "the 20 most similar recent articles".
--
-- - The performance half was severe enough to take the API down. Each call did
--   ~76MB of random reads against a 17GB ivfflat index on an instance with
--   640MB of shared_buffers, so nothing stayed cached. Calls ran for 45-60
--   MINUTES, piled up (18 concurrent observed), held AccessShareLock on
--   news_articles, and starved every other query — including article-page
--   lookups, which returned 500s, and any DDL, which could never get a lock.
--
-- The fix: push the time filter into the candidate CTE.
--
--   lookback   vectors     exact scan
--   24 hours     2,570        ~11 MB
--   7 days      14,061        ~58 MB
--   90 days    343,100      ~1,405 MB
--
-- For the common short windows the planner can use
-- idx_news_article_embeddings_published to select a few thousand rows and rank
-- them EXACTLY — cheaper than an approximate search over 1.85M, and with
-- perfect recall rather than ivfflat's sampling. For long windows it can still
-- fall back to the ivfflat index.
--
-- Over-fetch (match_count * 4, floor 40) so the stream and ticker filters below
-- still have candidates to work with after they cut the set down.
--
-- MATERIALIZED is kept: the point of the barrier was to stop the OUTER filters
-- being pushed into the vector scan. The time filter is now deliberately inside
-- it, which is the opposite situation and exactly what we want.
--
-- Not changed here: the ivfflat index is still lists=100 over 1.85M vectors
-- (~18.5k vectors per probe), which is under-partitioned — sqrt(n) ≈ 1361 would
-- be the textbook value. That rebuild is a 17GB operation and this change makes
-- it much less urgent, so it is deliberately left as a separate decision.
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION swingtrader.search_news_embeddings(
  query_embedding double precision[],
  match_count integer DEFAULT 20,
  lookback_hours integer DEFAULT 24,
  stream_filter text DEFAULT NULL::text,
  ticker_filter text[] DEFAULT NULL::text[]
)
RETURNS TABLE(
  article_id bigint, title text, url text, source text, slug text,
  image_url text, article_stream text, published_at timestamp with time zone,
  snippet text, similarity double precision
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path TO 'swingtrader', 'public', 'extensions'
SET statement_timeout TO '60s'
AS $function$
  WITH
    q AS (
      SELECT (query_embedding)::vector(1024) AS emb
    ),
    -- The time filter lives HERE, not in the outer WHERE. That is the whole
    -- fix: it bounds the set the vector search has to consider.
    raw_candidates AS MATERIALIZED (
      SELECT
        e.article_id,
        e.chunk_text,
        e.published_at,
        1 - (e.embedding <=> q.emb) AS similarity
      FROM q, swingtrader.news_article_embeddings e
      WHERE e.published_at >= NOW() - make_interval(hours => GREATEST(1, lookback_hours))
      ORDER BY e.embedding <=> q.emb
      LIMIT GREATEST(40, GREATEST(1, match_count) * 4)
    ),
    tf AS (
      SELECT array_agg(DISTINCT upper(t)) AS tickers
      FROM unnest(COALESCE(ticker_filter, ARRAY[]::text[])) AS t
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
  -- The published_at predicate that used to be here is gone: it is applied
  -- above, before the vector search, and repeating it would only mislead.
  WHERE (stream_filter IS NULL OR na.article_stream = stream_filter)
    AND (
      ticker_filter IS NULL
      OR cardinality(COALESCE(ticker_filter, ARRAY[]::text[])) = 0
      OR c.article_id IN (SELECT cipt.aid FROM candidate_ids_passing_ticker cipt)
    )
  ORDER BY c.similarity DESC
  LIMIT GREATEST(1, match_count)
$function$;
