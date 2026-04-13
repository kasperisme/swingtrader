-- ---------------------------------------------------------------------------
-- early_access_signups
--
-- Marketing waitlist from the public landing page. Inserts only via
-- server-side service role (Next.js API); RLS blocks direct client access.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS swingtrader.early_access_signups (
    id         BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    email      VARCHAR(320) NOT NULL,
    source     VARCHAR(64)  NOT NULL DEFAULT 'landing',
    CONSTRAINT early_access_signups_email_key UNIQUE (email)
);

CREATE INDEX IF NOT EXISTS idx_early_access_signups_created_at
    ON swingtrader.early_access_signups (created_at DESC);

ALTER TABLE swingtrader.early_access_signups ENABLE ROW LEVEL SECURITY;

GRANT ALL ON TABLE swingtrader.early_access_signups TO service_role;
