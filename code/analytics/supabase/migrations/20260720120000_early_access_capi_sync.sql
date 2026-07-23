-- ---------------------------------------------------------------------------
-- Track which early_access_signups have been forwarded to Meta via the
-- Conversions API (the "Qualified Leads" / CRM lead integration).
--
-- NULL  = not yet uploaded to Meta's dataset (pending).
-- set   = the UTC time the lead's `Lead` event was accepted by Meta.
--
-- The sync (services.meta_ads.capi) selects WHERE meta_capi_sent_at IS NULL,
-- so a re-run only sends new leads; each event also carries event_id = the
-- signup id, so Meta dedups even if a row is sent twice.
-- ---------------------------------------------------------------------------

ALTER TABLE swingtrader.early_access_signups
    ADD COLUMN IF NOT EXISTS meta_capi_sent_at TIMESTAMPTZ;

-- Partial index for the sync's hot query: "unsent signups, oldest first".
CREATE INDEX IF NOT EXISTS idx_early_access_signups_capi_unsent
    ON swingtrader.early_access_signups (created_at)
    WHERE meta_capi_sent_at IS NULL;

COMMENT ON COLUMN swingtrader.early_access_signups.meta_capi_sent_at IS
    'When this lead was uploaded to Meta''s Conversions API (CRM leads dataset). NULL = pending. Set by services.meta_ads.capi.';
