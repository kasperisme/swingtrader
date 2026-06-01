-- ---------------------------------------------------------------------------
-- Early access signups: add a structured `metadata` column.
--
-- We want to record attribution for each waitlist signup — notably the A/B CTA
-- variant a visitor was exposed to when they converted (e.g. the article or
-- landing-hero copy test) — without overloading the short `source` string.
--
-- `source` stays a clean channel label ('landing', 'article', 'landing-hero');
-- `metadata` carries discrete keys like { "cta_variant": "loss_aversion" } and
-- is free to grow (referrer, campaign, etc.) without further migrations.
-- ---------------------------------------------------------------------------

ALTER TABLE swingtrader.early_access_signups
    ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}'::jsonb;

COMMENT ON COLUMN swingtrader.early_access_signups.metadata IS
    'Structured signup attribution, e.g. {"cta_variant": "..."}. Written by the service-role API only.';

-- GIN index so we can filter/aggregate signups by metadata keys
-- (e.g. metadata->>''cta_variant'') when analysing CTA test performance.
CREATE INDEX IF NOT EXISTS idx_early_access_signups_metadata
    ON swingtrader.early_access_signups USING GIN (metadata);
