-- Denormalized search tags (from ARTICLE_TAGS head + ticker sentiment).
-- GIN index supports fast overlap queries: WHERE search_tags && ARRAY['fed','rates'].

ALTER TABLE swingtrader.news_articles
    ADD COLUMN IF NOT EXISTS search_tags TEXT[] NOT NULL DEFAULT '{}'::TEXT[];

CREATE INDEX IF NOT EXISTS idx_news_articles_search_tags_gin
    ON swingtrader.news_articles USING GIN (search_tags);

COMMENT ON COLUMN swingtrader.news_articles.search_tags IS
    'Lowercase theme slugs (taxonomy) plus uppercase tickers for indexed tag search.';

-- Fast tag-only search (no embedding). Used when query tokens match known tags.
CREATE OR REPLACE FUNCTION swingtrader.search_news_by_tags(
    tag_filter text[],
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
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = swingtrader, public
AS $$
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
$$;

GRANT EXECUTE ON FUNCTION swingtrader.search_news_by_tags(text[], integer, integer, text)
    TO authenticated, service_role;
