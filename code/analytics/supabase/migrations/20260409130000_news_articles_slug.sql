-- Add slug support for human-friendly article URLs
ALTER TABLE swingtrader.news_articles
ADD COLUMN IF NOT EXISTS slug TEXT;

-- Backfill existing rows: title-based slug where possible, else article-{id}
WITH bases AS (
  SELECT
    id,
    CASE
      WHEN title IS NOT NULL AND btrim(title) <> '' THEN
        NULLIF(
          regexp_replace(lower(title), '[^a-z0-9]+', '-', 'g'),
          ''
        )
      ELSE NULL
    END AS raw_slug
  FROM swingtrader.news_articles
),
normalized AS (
  SELECT
    id,
    COALESCE(btrim(raw_slug, '-'), 'article-' || id::text) AS base_slug
  FROM bases
),
deduped AS (
  SELECT
    id,
    base_slug,
    row_number() OVER (PARTITION BY base_slug ORDER BY id) AS rn
  FROM normalized
)
UPDATE swingtrader.news_articles AS na
SET slug = CASE
  WHEN d.rn = 1 THEN d.base_slug
  ELSE d.base_slug || '-' || d.rn::text
END
FROM deduped AS d
WHERE na.id = d.id
  AND (na.slug IS NULL OR btrim(na.slug) = '');

CREATE UNIQUE INDEX IF NOT EXISTS idx_news_articles_slug_unique
ON swingtrader.news_articles (slug)
WHERE slug IS NOT NULL AND btrim(slug) <> '';
