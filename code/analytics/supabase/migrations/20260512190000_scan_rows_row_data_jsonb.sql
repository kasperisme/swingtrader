-- ---------------------------------------------------------------------------
-- user_scan_rows.row_data: TEXT → JSONB
--
-- The column was created as TEXT with a comment "row_data is JSON text" and
-- callers stored stringified JSON. JSONB gives us native typing, indexable
-- key access, and stops PostgREST clients from double-encoding objects.
-- Existing rows are valid JSON strings, so the cast is safe via USING.
-- ---------------------------------------------------------------------------

ALTER TABLE swingtrader.user_scan_rows
    ALTER COLUMN row_data TYPE JSONB USING row_data::jsonb;
