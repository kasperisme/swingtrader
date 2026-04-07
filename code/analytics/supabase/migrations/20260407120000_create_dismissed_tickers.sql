-- ---------------------------------------------------------------------------
-- scan_row_notes: analyst workflow annotations linked to specific scan rows.
--
-- Replaces ticker-level "dismissed_tickers" with row-level state so users can:
--   - dismiss or restore candidates
--   - highlight candidates for follow-up
--   - add comments for pipeline handoff
--   - track screening workflow stage/priority
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS swingtrader.scan_row_notes (
    id             BIGSERIAL PRIMARY KEY,
    scan_row_id    BIGINT      NOT NULL REFERENCES swingtrader.scan_rows (id) ON DELETE CASCADE,
    run_id         BIGINT      NOT NULL REFERENCES swingtrader.scan_runs (id) ON DELETE CASCADE,
    ticker         VARCHAR     NOT NULL,
    status         VARCHAR     NOT NULL DEFAULT 'active'
                              CHECK (status IN ('active', 'dismissed', 'watchlist', 'pipeline')),
    highlighted    BOOLEAN     NOT NULL DEFAULT FALSE,
    comment        TEXT,
    stage          VARCHAR     CHECK (stage IN ('new', 'researching', 'watching', 'ready', 'rejected')),
    priority       SMALLINT,
    tags           TEXT[]      NOT NULL DEFAULT '{}'::TEXT[],
    metadata_json  JSONB       NOT NULL DEFAULT '{}'::JSONB,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (scan_row_id)
);

CREATE INDEX IF NOT EXISTS idx_scan_row_notes_run_id      ON swingtrader.scan_row_notes (run_id);
CREATE INDEX IF NOT EXISTS idx_scan_row_notes_ticker      ON swingtrader.scan_row_notes (ticker);
CREATE INDEX IF NOT EXISTS idx_scan_row_notes_status      ON swingtrader.scan_row_notes (status);
CREATE INDEX IF NOT EXISTS idx_scan_row_notes_highlighted ON swingtrader.scan_row_notes (highlighted);
CREATE INDEX IF NOT EXISTS idx_scan_row_notes_stage       ON swingtrader.scan_row_notes (stage);

GRANT ALL ON swingtrader.scan_row_notes TO anon, authenticated, service_role;
