-- ---------------------------------------------------------------------------
-- Public Screenings: CSV download counter.
--
-- Adds a download_count column that is incremented atomically every time the
-- /screenings/[slug]/export route serves a CSV. Used to power "Most
-- downloaded" sorting on the public gallery and a per-row count badge.
--
-- Writes happen exclusively via service_role from the Next.js route; we ship
-- a SECURITY DEFINER function so a future shift to anon/auth callers can keep
-- the same surface without needing direct UPDATE grants on the table.
-- ---------------------------------------------------------------------------

ALTER TABLE swingtrader.public_screenings
    ADD COLUMN IF NOT EXISTS download_count BIGINT NOT NULL DEFAULT 0;

CREATE INDEX IF NOT EXISTS idx_public_screenings_download_count
    ON swingtrader.public_screenings (download_count DESC)
    WHERE is_published = TRUE;

CREATE OR REPLACE FUNCTION swingtrader.increment_public_screening_download(
    p_id UUID
)
RETURNS BIGINT
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = swingtrader, public
AS $$
DECLARE
    v_new_count BIGINT;
BEGIN
    UPDATE swingtrader.public_screenings
       SET download_count = download_count + 1
     WHERE id = p_id
       AND is_published = TRUE
    RETURNING download_count INTO v_new_count;

    RETURN v_new_count;
END;
$$;

REVOKE ALL ON FUNCTION swingtrader.increment_public_screening_download(UUID) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION swingtrader.increment_public_screening_download(UUID) TO service_role;
