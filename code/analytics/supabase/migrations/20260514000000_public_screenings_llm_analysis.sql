-- ---------------------------------------------------------------------------
-- Public screening LLM bulk-analysis support.
--
--   public_screenings.llm_prompt
--       Optional per-screening instruction passed to the bulk-analytics LLM
--       after the initial screening produces its tickers. When NULL, no
--       post-processing runs. Publicly viewable (covered by the existing
--       public_screenings_select_published policy).
--
--   public_screening_results.bulk_analysis_*
--       Per-run state for the bulk-analysis pass. One pass per result row, so
--       state lives on the result itself rather than in a separate jobs table.
--       Status enum:
--         null      — screening had no llm_prompt; nothing to do
--         queued    — initial screening done, waiting for a worker
--         running   — worker is processing tickers
--         done      — every ticker enriched (or skipped on error)
--         error     — fatal error before any ticker was enriched
-- ---------------------------------------------------------------------------

ALTER TABLE swingtrader.public_screenings
    ADD COLUMN IF NOT EXISTS llm_prompt TEXT;

ALTER TABLE swingtrader.public_screening_results
    ADD COLUMN IF NOT EXISTS bulk_analysis_status      TEXT
        CHECK (bulk_analysis_status IN ('queued', 'running', 'done', 'error')),
    ADD COLUMN IF NOT EXISTS bulk_analysis_started_at  TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS bulk_analysis_finished_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS bulk_analysis_error       TEXT;

-- Worker dispatch index: cheap lookup of results waiting for analysis.
CREATE INDEX IF NOT EXISTS idx_psr_results_bulk_analysis_queued
    ON swingtrader.public_screening_results (bulk_analysis_status, run_at)
    WHERE bulk_analysis_status IN ('queued', 'running');
