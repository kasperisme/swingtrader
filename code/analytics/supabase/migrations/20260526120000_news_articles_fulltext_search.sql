-- Full-text search over news articles with relevance ranking.
--
-- Tag overlap (search_news_by_tags) only matches the curated `search_tags`
-- array and sorts purely by recency, so a free-text query like
-- "iran oil crisis" can neither match body text nor rank by how well it fits.
-- This adds a weighted, materialized tsvector over title + tags + body and a
-- ranking RPC that ORs the query terms and scores with ts_rank_cd.

-- Weighted document vector: title (A) > tags (B) > body (C). ts_rank_cd weights
-- these {A:1.0, B:0.4, C:0.2} by default, so a title hit outranks a body hit.
--
-- IMMUTABLE wrapper: a STABLE function (array_to_string) can't be used directly
-- in a generated column / index, but the result is genuinely deterministic, so
-- wrapping it lets the column trigger and index reference one shared definition.
CREATE OR REPLACE FUNCTION swingtrader.news_article_fts(
    title text,
    search_tags text[],
    body text
)
RETURNS tsvector
LANGUAGE sql
IMMUTABLE
PARALLEL SAFE
AS $$
    SELECT setweight(to_tsvector('english', coalesce(title, '')), 'A')
        || setweight(to_tsvector('english', coalesce(array_to_string(search_tags, ' '), '')), 'B')
        || setweight(to_tsvector('english', coalesce(body, '')), 'C');
$$;

-- Materialize the vector in a real column (NOT a generated/expression index).
-- Ranking (ts_rank_cd) and the GIN recheck must READ the vector per matched
-- row; with an expression index Postgres can't read it back and rebuilds
-- to_tsvector over the full body for every match — tens of thousands of
-- re-tokenizations for common terms, which times out. A stored column is read
-- directly. The column is nullable with no default, so ADD COLUMN is an instant
-- metadata change (no table rewrite); a trigger keeps it current and existing
-- rows are backfilled below.
ALTER TABLE swingtrader.news_articles ADD COLUMN IF NOT EXISTS fts tsvector;

COMMENT ON COLUMN swingtrader.news_articles.fts IS
    'Weighted full-text vector (title A, search_tags B, body C) for ranked search.';

CREATE OR REPLACE FUNCTION swingtrader.news_articles_fts_maintain()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.fts := swingtrader.news_article_fts(NEW.title, NEW.search_tags, NEW.body);
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_news_articles_fts ON swingtrader.news_articles;
CREATE TRIGGER trg_news_articles_fts
    BEFORE INSERT OR UPDATE OF title, search_tags, body
    ON swingtrader.news_articles
    FOR EACH ROW
    EXECUTE FUNCTION swingtrader.news_articles_fts_maintain();

-- Backfill existing rows. On a large table run this in id-range batches (each
-- its own transaction) to avoid a long lock / statement timeout, e.g.:
--   UPDATE swingtrader.news_articles SET fts = swingtrader.news_article_fts(title, search_tags, body)
--   WHERE id >= :lo AND id < :hi AND fts IS NULL;
UPDATE swingtrader.news_articles
   SET fts = swingtrader.news_article_fts(title, search_tags, body)
 WHERE fts IS NULL;

-- GIN index on the stored column. Use CREATE INDEX CONCURRENTLY (outside a
-- transaction) when applying against a live table to avoid blocking writes.
CREATE INDEX IF NOT EXISTS idx_news_articles_fts_gin
    ON swingtrader.news_articles USING GIN (fts);

-- Ranked full-text search. The query is lexed and stemmed, then the lexemes are
-- OR-combined so "iran oil crisis" matches articles containing iran OR oil OR
-- crisis, ranked by ts_rank_cd (more / rarer / higher-weighted matches score
-- higher). Returns the same shape as search_news_by_tags; `similarity` carries
-- the raw ts_rank_cd score (normalized client-side for display).
CREATE OR REPLACE FUNCTION swingtrader.search_news_fulltext(
    query_text text,
    match_count integer DEFAULT 20,
    lookback_hours integer DEFAULT 2160,
    stream_filter text DEFAULT NULL
)
RETURNS TABLE (
    article_id bigint,
    title text,
    url text,
    source text,
    slug text,
    image_url text,
    article_stream text,
    published_at timestamptz,
    snippet text,
    similarity double precision
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = swingtrader, public
AS $$
DECLARE
    or_query text;
    ts_q tsquery;
BEGIN
    -- Build an OR tsquery from the stemmed, stopword-filtered lexemes. Using
    -- the lexemes (rather than raw input) keeps to_tsquery safe from operator
    -- characters in user input.
    SELECT string_agg(lexeme, ' | ')
      INTO or_query
      FROM unnest(to_tsvector('english', coalesce(query_text, '')));

    IF or_query IS NULL OR btrim(or_query) = '' THEN
        RETURN;  -- nothing searchable (empty / all stopwords)
    END IF;

    ts_q := to_tsquery('english', or_query);

    RETURN QUERY
    SELECT
        a.id AS article_id,
        -- title/url/source/slug are varchar; cast to text to match the declared
        -- return type (plpgsql RETURN QUERY does not auto-widen varchar→text).
        a.title::text,
        a.url::text,
        a.source::text,
        a.slug::text,
        a.image_url,
        a.article_stream,
        a.published_at,
        ts_headline(
            'english', left(a.body, 600), ts_q,
            'StartSel=,StopSel=,MaxFragments=2,MaxWords=30,MinWords=10'
        ) AS snippet,
        ts_rank_cd(a.fts, ts_q)::double precision AS similarity
    FROM swingtrader.news_articles a
    WHERE a.fts @@ ts_q
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
    ORDER BY similarity DESC, a.published_at DESC NULLS LAST, a.id DESC
    LIMIT GREATEST(1, LEAST(match_count, 100));
END;
$$;

GRANT EXECUTE ON FUNCTION swingtrader.search_news_fulltext(text, integer, integer, text)
    TO authenticated, service_role;
