-- Extend swingtrader.podcast_episodes so the UI can render an RSS feed
-- directly from the table. RSS-relevant fields the UI needs:
--   description       — show notes / episode description
--   audio_url         — public storage URL for the MP3
--   cover_url         — public storage URL for the cover PNG
--   file_size_bytes   — required by RSS <enclosure length=…>
--   guid              — RSS <guid> stable identifier
--   published_at      — RSS <pubDate> (UTC timestamp distinct from date)

ALTER TABLE swingtrader.podcast_episodes
    ADD COLUMN IF NOT EXISTS description     TEXT,
    ADD COLUMN IF NOT EXISTS audio_url       TEXT,
    ADD COLUMN IF NOT EXISTS cover_url       TEXT,
    ADD COLUMN IF NOT EXISTS file_size_bytes BIGINT,
    ADD COLUMN IF NOT EXISTS guid            TEXT,
    ADD COLUMN IF NOT EXISTS published_at    TIMESTAMPTZ;

-- One row per published episode; the publisher upserts on guid to make reruns
-- idempotent. PostgREST's ON CONFLICT requires a real UNIQUE constraint
-- (a partial unique index with WHERE doesn't satisfy ON CONFLICT(guid)).
-- Postgres treats NULL guids as distinct, so historical rows with NULL stay valid.
ALTER TABLE swingtrader.podcast_episodes
    DROP CONSTRAINT IF EXISTS podcast_episodes_guid_unique,
    ADD CONSTRAINT podcast_episodes_guid_unique UNIQUE (guid);

-- Index used by the UI feed query (latest published episodes).
CREATE INDEX IF NOT EXISTS podcast_episodes_published_idx
    ON swingtrader.podcast_episodes (published_at DESC NULLS LAST)
    WHERE status = 'published';
