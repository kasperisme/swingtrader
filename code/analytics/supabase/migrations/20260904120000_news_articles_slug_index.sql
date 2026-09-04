-- ---------------------------------------------------------------------------
-- news_articles: index the slug
--
-- Problem:
-- - /articles/<slug> looks an article up by slug, and `slug` had no index. On
--   226k rows that is a sequential scan: measured at 56 SECONDS for a single
--   article, removing 226,388 rows by filter. PostgREST hit its statement
--   timeout and returned 500, so article pages failed outright.
--
-- - The page does it TWICE — once in `generateMetadata` and once in the body
--   (app/articles/[slug]/page.tsx) — so every article view was two full scans.
--
-- Why an index and not an RPC:
-- - There is no by-slug RPC to route this through. Every article function in
--   this schema is search/discovery (`search_news_fulltext`,
--   `search_news_by_tags`, `search_news_embeddings`, `get_ticker_impact_news`,
--   `get_relationship_node_news`); none takes a slug. A single-row lookup is
--   what an index is for, and wrapping it in a function would not have helped.
--
-- NOT unique, deliberately: one duplicate slug exists (ids 197496 / 197497,
-- the same MarketBeat URL ingested twice). A UNIQUE index cannot build until
-- that is resolved, and the performance fix should not wait on a data decision.
--
-- ── Read this before running it ────────────────────────────────────────────
--
-- NO `IF NOT EXISTS`, deliberately. A failed CONCURRENTLY build leaves an
-- INVALID index behind — same name, right size, and completely unused by the
-- planner. `IF NOT EXISTS` then silently skips the rebuild and reports success,
-- which is exactly how this fix appeared to land twice without doing anything.
-- Without the clause you get a loud "already exists" instead, which is the
-- error you want.
--
-- Verify afterwards — the name existing is not evidence:
--   SELECT i.relname, x.indisvalid
--   FROM pg_index x JOIN pg_class i ON i.oid = x.indexrelid
--   WHERE i.relname = 'idx_news_articles_slug';   -- indisvalid MUST be true
--
-- Plain CREATE INDEX, not CONCURRENTLY: CONCURRENTLY avoids the exclusive lock
-- but must outlast every transaction running when it starts, and this database
-- carries hour-long `search_news_embeddings` calls that make it wait forever.
-- The plain build takes ~30s on 226k rows and blocks readers only for that long
-- — but it cannot start until the long transactions are cleared, hence step 1.
-- ---------------------------------------------------------------------------

-- 1) Clear the hour-long vector searches that hold AccessShareLock and prevent
--    any DDL from acquiring a lock. They are read-only; terminating is safe.
SELECT pg_terminate_backend(pid)
FROM pg_stat_activity
WHERE state = 'active'
  AND query LIKE '%pgrst_call%'
  AND pid <> pg_backend_pid()
  AND now() - query_start > interval '60 seconds';

-- 2) Remove the invalid stubs left by previous timed-out builds.
DROP INDEX IF EXISTS swingtrader.idx_news_articles_slug;
DROP INDEX IF EXISTS swingtrader.idx_news_articles_slug_v2;
DROP INDEX IF EXISTS swingtrader.idx_news_articles_slug_v3;

-- 3) Build it.
CREATE INDEX idx_news_articles_slug
  ON swingtrader.news_articles (slug);
