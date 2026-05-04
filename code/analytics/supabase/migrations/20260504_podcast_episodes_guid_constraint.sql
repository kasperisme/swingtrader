-- Fix: PostgREST's `upsert(..., on_conflict="guid")` requires a real UNIQUE
-- constraint or a non-partial unique index — a partial unique index (with a
-- WHERE clause) does not satisfy the ON CONFLICT specification.
--
-- The previous migration created a partial unique index. Drop it and replace
-- with a proper UNIQUE constraint. NULL guids remain allowed (Postgres treats
-- NULLs as distinct by default), so historical rows aren't affected.

DROP INDEX IF EXISTS swingtrader.podcast_episodes_guid_uniq;

ALTER TABLE swingtrader.podcast_episodes
    DROP CONSTRAINT IF EXISTS podcast_episodes_guid_unique,
    ADD CONSTRAINT podcast_episodes_guid_unique UNIQUE (guid);
