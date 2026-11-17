-- ---------------------------------------------------------------------------
-- Retire the news vector store: news_article_embeddings and everything on it
--
-- Measured 2026-11-09: the database was 38 GB against an 8 GB disk quota, and
-- news_article_embeddings alone was 32 GB (2.09M chunks of vector(1024):
-- 2.2 GB heap, 12 GB TOAST, 18 GB of indexes). Its ivfflat index
-- (idx_news_article_embeddings_vec_cos, 18 GB) had 78 scans in total, the last
-- on 2026-09-04 — the day 20260904140000_search_news_embeddings_filter_first
-- made the search filter by published_at and rank the survivors exactly.
--
-- Every reader has moved to the tag-overlap / Postgres full-text cascade the
-- agent tools already used (search_news_by_tags, search_news_fulltext, and
-- services.rag.search_news in Python): the pre-market brief, the blog
-- generator, Telegram /search and the /articles search fallback. The priced-in
-- pipeline (strategylab NarrativeSpace + eventtest) now vectorises
-- news_articles.body in memory over to_tsvector('english') lexemes. What was
-- given up is meaning-level recall for queries that share no words with the
-- article — accepted for 32 GB.
--
-- Dropped:
--   search_news_embeddings(...)              the vector search RPC
--   search_news_article_embeddings_gte(...)  dead: its table was already gone
--   news_article_embeddings                  chunk text + vector(1024)
--   news_article_embedding_jobs              the writer's job queue
--   news_embedding_{hourly,daily}_cluster_{runs,centroids,articles}
--                                            K-means over the vectors; no reader
--
-- The `vector` extension is left installed: dropping it is not needed to free
-- the space and other tables may adopt it later.
--
-- APPLY ONLY AFTER the code that stops reading/writing these is deployed (UI on
-- Vercel, analytics + strategylab on the Mac Mini) and the four embeddings_*
-- cron jobs there are removed — otherwise those callers start erroring.
--
-- DROP TABLE returns the disk immediately (no VACUUM FULL needed). Supabase does
-- not shrink a provisioned disk on its own; reduce it in the dashboard after.
-- ---------------------------------------------------------------------------

DROP FUNCTION IF EXISTS swingtrader.search_news_embeddings(
  double precision[], integer, integer, text, text[], timestamp with time zone);
DROP FUNCTION IF EXISTS swingtrader.search_news_article_embeddings_gte(
  double precision[], integer, integer, text);

DROP TABLE IF EXISTS swingtrader.news_embedding_hourly_cluster_articles;
DROP TABLE IF EXISTS swingtrader.news_embedding_hourly_cluster_centroids;
DROP TABLE IF EXISTS swingtrader.news_embedding_hourly_cluster_runs;
DROP TABLE IF EXISTS swingtrader.news_embedding_daily_cluster_articles;
DROP TABLE IF EXISTS swingtrader.news_embedding_daily_cluster_centroids;
DROP TABLE IF EXISTS swingtrader.news_embedding_daily_cluster_runs;

DROP TABLE IF EXISTS swingtrader.news_article_embedding_jobs;
DROP TABLE IF EXISTS swingtrader.news_article_embeddings;
