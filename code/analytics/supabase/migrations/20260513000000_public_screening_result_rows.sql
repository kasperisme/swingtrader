-- ---------------------------------------------------------------------------
-- public_screening_result_rows — canonical per-ticker output of a public
-- screening run. Modeled on user_scan_rows, but scoped to a public_screenings
-- + public_screening_results pair so the data doesn't have to be duplicated
-- inside public_screening_results.data_used.
--
-- One row per (run, ticker). Datasets follow the same vocabulary as
-- user_scan_rows ('trend_template', 'passed_stocks', 'charts_page') so
-- existing UI conventions transfer.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS swingtrader.public_screening_result_rows (
    id                  BIGSERIAL   PRIMARY KEY,
    public_screening_id UUID        NOT NULL REFERENCES swingtrader.public_screenings (id) ON DELETE CASCADE,
    result_id           UUID        NOT NULL REFERENCES swingtrader.public_screening_results (id) ON DELETE CASCADE,
    run_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    scan_date           DATE        NOT NULL,
    dataset             VARCHAR     NOT NULL,
    symbol              VARCHAR,
    row_data            JSONB       NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_psr_rows_result
    ON swingtrader.public_screening_result_rows (result_id);

CREATE INDEX IF NOT EXISTS idx_psr_rows_screening
    ON swingtrader.public_screening_result_rows (public_screening_id, run_at DESC);

CREATE INDEX IF NOT EXISTS idx_psr_rows_symbol
    ON swingtrader.public_screening_result_rows (symbol);

CREATE INDEX IF NOT EXISTS idx_psr_rows_dataset
    ON swingtrader.public_screening_result_rows (dataset);

ALTER TABLE swingtrader.public_screening_result_rows ENABLE ROW LEVEL SECURITY;

-- Rows for any *published* screening are readable by authenticated users,
-- mirroring the policy on public_screening_results.
DROP POLICY IF EXISTS psr_rows_select_published ON swingtrader.public_screening_result_rows;
CREATE POLICY psr_rows_select_published ON swingtrader.public_screening_result_rows
    FOR SELECT TO authenticated USING (
        EXISTS (
            SELECT 1 FROM swingtrader.public_screenings ps
            WHERE ps.id = public_screening_result_rows.public_screening_id
              AND ps.is_published = TRUE
        )
    );

GRANT ALL    ON swingtrader.public_screening_result_rows TO service_role;
GRANT SELECT ON swingtrader.public_screening_result_rows TO authenticated;
