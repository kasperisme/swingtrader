-- ---------------------------------------------------------------------------
-- Artifacts attached to a research write-up.
--
-- The notes reference the files they were computed from — a pre-registration
-- record, a results JSON, a data panel. Printed as bare local paths those
-- references are worse than useless: they look like evidence while pointing at
-- a directory on one laptop.
--
-- So each referenced file becomes a row. Either it is genuinely downloadable
-- (`available = true`, with a public URL), or it is not, and `reason` has to
-- say why. The second case is not a gap to hide — "this panel is derived from
-- licensed vendor data and cannot be redistributed" is information a
-- replicator needs before they start.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS swingtrader.research_artifacts (
    id           bigserial PRIMARY KEY,
    note_slug    text NOT NULL REFERENCES swingtrader.research_notes(slug)
                     ON DELETE CASCADE,
    name         text NOT NULL,
    description  text NOT NULL,
    -- false = deliberately not published; `reason` must explain.
    available    boolean NOT NULL DEFAULT false,
    reason       text,
    public_url   text,
    storage_path text,
    bytes        bigint,
    sha256       text,
    sort_order   int NOT NULL DEFAULT 0,
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now(),
    UNIQUE (note_slug, name),
    -- An unavailable artifact without a stated reason is just a dead link
    -- with extra steps.
    CONSTRAINT research_artifacts_reason_ck
        CHECK (available OR reason IS NOT NULL),
    CONSTRAINT research_artifacts_url_ck
        CHECK (NOT available OR public_url IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS ix_research_artifacts_note
    ON swingtrader.research_artifacts (note_slug, sort_order);

ALTER TABLE swingtrader.research_artifacts ENABLE ROW LEVEL SECURITY;

-- Visible exactly when its write-up is. No separate publish flag: an artifact
-- belongs to its note and should never outlive or precede it.
DROP POLICY IF EXISTS research_artifacts_public_read ON swingtrader.research_artifacts;
CREATE POLICY research_artifacts_public_read ON swingtrader.research_artifacts
    FOR SELECT USING (
        EXISTS (SELECT 1 FROM swingtrader.research_notes n
                WHERE n.slug = research_artifacts.note_slug AND n.published));

CREATE OR REPLACE VIEW swingtrader.research_artifacts_public_v AS
SELECT a.note_slug, a.name, a.description, a.available, a.reason,
       a.public_url, a.bytes, a.sha256, a.sort_order
FROM swingtrader.research_artifacts a
JOIN swingtrader.research_notes n ON n.slug = a.note_slug
WHERE n.published
ORDER BY a.note_slug, a.sort_order, a.name;
