-- Public-read storage bucket for podcast audio + cover art.
--
-- Apple Podcasts / Spotify polling fetches public URLs without auth, so the
-- bucket is public-read. Writes are restricted to the service role used by
-- the analytics pipeline.

INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
VALUES (
    'podcast',
    'podcast',
    TRUE,                                    -- public read
    524288000,                               -- 500 MB hard cap per object
    ARRAY['audio/mpeg', 'image/png', 'image/jpeg']::text[]
)
ON CONFLICT (id) DO UPDATE SET
    public = EXCLUDED.public,
    file_size_limit = EXCLUDED.file_size_limit,
    allowed_mime_types = EXCLUDED.allowed_mime_types;

-- Public read policy (object listing/download for anyone).
DROP POLICY IF EXISTS "Public read podcast bucket" ON storage.objects;
CREATE POLICY "Public read podcast bucket"
    ON storage.objects FOR SELECT
    USING (bucket_id = 'podcast');

-- Service-role write only — the analytics pipeline uses SUPABASE_KEY (service
-- role) so this matches in practice; anon clients cannot upload or delete.
DROP POLICY IF EXISTS "Service role writes podcast bucket" ON storage.objects;
CREATE POLICY "Service role writes podcast bucket"
    ON storage.objects FOR ALL
    USING (bucket_id = 'podcast' AND (auth.jwt()->>'role') = 'service_role')
    WITH CHECK (bucket_id = 'podcast' AND (auth.jwt()->>'role') = 'service_role');
