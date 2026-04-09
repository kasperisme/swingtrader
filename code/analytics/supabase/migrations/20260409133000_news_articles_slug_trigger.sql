-- Generate and maintain news_articles.slug inside the database.
-- This keeps slug logic centralized and independent of app code.

CREATE OR REPLACE FUNCTION swingtrader.set_news_article_slug()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
  base_slug text;
  candidate text;
  suffix int := 2;
BEGIN
  -- Respect explicit slug only when provided.
  IF NEW.slug IS NOT NULL AND btrim(NEW.slug) <> '' THEN
    RETURN NEW;
  END IF;

  base_slug := regexp_replace(lower(COALESCE(NEW.title, '')), '[^a-z0-9]+', '-', 'g');
  base_slug := btrim(base_slug, '-');
  IF base_slug = '' THEN
    base_slug := 'article-' || left(COALESCE(NEW.article_hash, md5(random()::text)), 10);
  END IF;

  candidate := base_slug;
  WHILE EXISTS (
    SELECT 1
    FROM swingtrader.news_articles na
    WHERE na.slug = candidate
      AND (NEW.id IS NULL OR na.id <> NEW.id)
  ) LOOP
    candidate := base_slug || '-' || suffix::text;
    suffix := suffix + 1;
  END LOOP;

  NEW.slug := candidate;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_set_news_article_slug ON swingtrader.news_articles;

CREATE TRIGGER trg_set_news_article_slug
BEFORE INSERT OR UPDATE OF title, article_hash, slug
ON swingtrader.news_articles
FOR EACH ROW
EXECUTE FUNCTION swingtrader.set_news_article_slug();
