-- ---------------------------------------------------------------------------
-- Rename `public_screenings*` → `market_screenings*` across the schema.
--
-- Pure metadata changes (ALTER … RENAME …) plus one function body rewrite for
-- `increment_public_screening_download`, whose body referenced the table by
-- name. No data is moved. No backward-compat views are created — callers
-- (Python services, Next.js server actions, API routes) ship together with
-- this migration.
--
-- Every operation is guarded with an existence check so the migration is
-- idempotent and safe to re-run after a partial apply (e.g. a transaction
-- that errored partway and rolled back, or a DB where some upstream object
-- never existed).
--
-- Affects:
--   tables:    public_screenings, public_screening_subscriptions,
--              public_screening_results, public_screening_result_rows
--   columns:   public_screening_id  (4 tables, incl. early_access_signups)
--   policies:  public_screenings_*, public_screening_subs_*,
--              public_screening_results_*, psr_rows_*
--   triggers:  trg_public_screenings_updated_at,
--              trg_public_screenings_recompute_next_run_at
--   funcs:     touch_public_screenings_updated_at,
--              recompute_public_screenings_next_run_at,
--              increment_public_screening_download   (body rewritten)
--   indexes:   idx_public_screening*, idx_psr_*
-- ---------------------------------------------------------------------------

BEGIN;


-- ── Helpers ─────────────────────────────────────────────────────────────────
-- All renames live in one DO block so we can use IF/THEN guards. Each block
-- checks pg_catalog before issuing the ALTER, so the migration is safe to
-- re-run and tolerates missing upstream objects (e.g. a DB where
-- early_access_signups was never created).

DO $migration$
DECLARE
    v_schema text := 'swingtrader';
BEGIN

    -- ── Tables ──────────────────────────────────────────────────────────────

    IF to_regclass(v_schema || '.public_screenings') IS NOT NULL THEN
        EXECUTE 'ALTER TABLE swingtrader.public_screenings RENAME TO market_screenings';
    END IF;

    IF to_regclass(v_schema || '.public_screening_subscriptions') IS NOT NULL THEN
        EXECUTE 'ALTER TABLE swingtrader.public_screening_subscriptions RENAME TO market_screening_subscriptions';
    END IF;

    IF to_regclass(v_schema || '.public_screening_results') IS NOT NULL THEN
        EXECUTE 'ALTER TABLE swingtrader.public_screening_results RENAME TO market_screening_results';
    END IF;

    IF to_regclass(v_schema || '.public_screening_result_rows') IS NOT NULL THEN
        EXECUTE 'ALTER TABLE swingtrader.public_screening_result_rows RENAME TO market_screening_result_rows';
    END IF;

    -- ── Foreign-key columns ─────────────────────────────────────────────────

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_schema = v_schema
           AND table_name   = 'market_screening_subscriptions'
           AND column_name  = 'public_screening_id'
    ) THEN
        EXECUTE 'ALTER TABLE swingtrader.market_screening_subscriptions
                 RENAME COLUMN public_screening_id TO market_screening_id';
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_schema = v_schema
           AND table_name   = 'market_screening_results'
           AND column_name  = 'public_screening_id'
    ) THEN
        EXECUTE 'ALTER TABLE swingtrader.market_screening_results
                 RENAME COLUMN public_screening_id TO market_screening_id';
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_schema = v_schema
           AND table_name   = 'market_screening_result_rows'
           AND column_name  = 'public_screening_id'
    ) THEN
        EXECUTE 'ALTER TABLE swingtrader.market_screening_result_rows
                 RENAME COLUMN public_screening_id TO market_screening_id';
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_schema = v_schema
           AND table_name   = 'early_access_signups'
           AND column_name  = 'public_screening_id'
    ) THEN
        EXECUTE 'ALTER TABLE swingtrader.early_access_signups
                 RENAME COLUMN public_screening_id TO market_screening_id';
    END IF;

    -- ── Policies ────────────────────────────────────────────────────────────
    -- (Renames are looked up by old policy name; only fires if the old name
    -- still exists on the (renamed) table.)

    IF EXISTS (
        SELECT 1 FROM pg_policies
         WHERE schemaname = v_schema
           AND tablename  = 'market_screenings'
           AND policyname = 'public_screenings_select_published'
    ) THEN
        EXECUTE 'ALTER POLICY public_screenings_select_published
                 ON swingtrader.market_screenings
                 RENAME TO market_screenings_select_published';
    END IF;

    IF EXISTS (
        SELECT 1 FROM pg_policies
         WHERE schemaname = v_schema
           AND tablename  = 'market_screening_subscriptions'
           AND policyname = 'public_screening_subs_select_own'
    ) THEN
        EXECUTE 'ALTER POLICY public_screening_subs_select_own
                 ON swingtrader.market_screening_subscriptions
                 RENAME TO market_screening_subs_select_own';
    END IF;

    IF EXISTS (
        SELECT 1 FROM pg_policies
         WHERE schemaname = v_schema
           AND tablename  = 'market_screening_subscriptions'
           AND policyname = 'public_screening_subs_insert_own'
    ) THEN
        EXECUTE 'ALTER POLICY public_screening_subs_insert_own
                 ON swingtrader.market_screening_subscriptions
                 RENAME TO market_screening_subs_insert_own';
    END IF;

    IF EXISTS (
        SELECT 1 FROM pg_policies
         WHERE schemaname = v_schema
           AND tablename  = 'market_screening_subscriptions'
           AND policyname = 'public_screening_subs_update_own'
    ) THEN
        EXECUTE 'ALTER POLICY public_screening_subs_update_own
                 ON swingtrader.market_screening_subscriptions
                 RENAME TO market_screening_subs_update_own';
    END IF;

    IF EXISTS (
        SELECT 1 FROM pg_policies
         WHERE schemaname = v_schema
           AND tablename  = 'market_screening_subscriptions'
           AND policyname = 'public_screening_subs_delete_own'
    ) THEN
        EXECUTE 'ALTER POLICY public_screening_subs_delete_own
                 ON swingtrader.market_screening_subscriptions
                 RENAME TO market_screening_subs_delete_own';
    END IF;

    IF EXISTS (
        SELECT 1 FROM pg_policies
         WHERE schemaname = v_schema
           AND tablename  = 'market_screening_results'
           AND policyname = 'public_screening_results_select_published'
    ) THEN
        EXECUTE 'ALTER POLICY public_screening_results_select_published
                 ON swingtrader.market_screening_results
                 RENAME TO market_screening_results_select_published';
    END IF;

    IF EXISTS (
        SELECT 1 FROM pg_policies
         WHERE schemaname = v_schema
           AND tablename  = 'market_screening_result_rows'
           AND policyname = 'psr_rows_select_published'
    ) THEN
        EXECUTE 'ALTER POLICY psr_rows_select_published
                 ON swingtrader.market_screening_result_rows
                 RENAME TO msr_rows_select_published';
    END IF;

    -- ── Triggers ────────────────────────────────────────────────────────────

    IF EXISTS (
        SELECT 1 FROM pg_trigger t
          JOIN pg_class c    ON c.oid = t.tgrelid
          JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname = v_schema
           AND c.relname = 'market_screenings'
           AND t.tgname  = 'trg_public_screenings_updated_at'
    ) THEN
        EXECUTE 'ALTER TRIGGER trg_public_screenings_updated_at
                 ON swingtrader.market_screenings
                 RENAME TO trg_market_screenings_updated_at';
    END IF;

    IF EXISTS (
        SELECT 1 FROM pg_trigger t
          JOIN pg_class c    ON c.oid = t.tgrelid
          JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname = v_schema
           AND c.relname = 'market_screenings'
           AND t.tgname  = 'trg_public_screenings_recompute_next_run_at'
    ) THEN
        EXECUTE 'ALTER TRIGGER trg_public_screenings_recompute_next_run_at
                 ON swingtrader.market_screenings
                 RENAME TO trg_market_screenings_recompute_next_run_at';
    END IF;

    -- ── Trigger functions ───────────────────────────────────────────────────
    -- (Bodies don't reference any renamed table by name, so a name swap suffices.)

    IF EXISTS (
        SELECT 1 FROM pg_proc p
          JOIN pg_namespace n ON n.oid = p.pronamespace
         WHERE n.nspname = v_schema
           AND p.proname = 'touch_public_screenings_updated_at'
    ) THEN
        EXECUTE 'ALTER FUNCTION swingtrader.touch_public_screenings_updated_at()
                 RENAME TO touch_market_screenings_updated_at';
    END IF;

    IF EXISTS (
        SELECT 1 FROM pg_proc p
          JOIN pg_namespace n ON n.oid = p.pronamespace
         WHERE n.nspname = v_schema
           AND p.proname = 'recompute_public_screenings_next_run_at'
    ) THEN
        EXECUTE 'ALTER FUNCTION swingtrader.recompute_public_screenings_next_run_at()
                 RENAME TO recompute_market_screenings_next_run_at';
    END IF;

    -- ── Download incrementer ────────────────────────────────────────────────
    -- Body references the table by name, so we drop the old function (if it
    -- exists) and create the new one fresh. The CREATE OR REPLACE outside this
    -- DO block ensures the new function exists exactly once.

    EXECUTE 'DROP FUNCTION IF EXISTS swingtrader.increment_public_screening_download(UUID)';

    -- ── Indexes ─────────────────────────────────────────────────────────────

    IF to_regclass(v_schema || '.idx_public_screenings_published') IS NOT NULL THEN
        EXECUTE 'ALTER INDEX swingtrader.idx_public_screenings_published RENAME TO idx_market_screenings_published';
    END IF;
    IF to_regclass(v_schema || '.idx_public_screenings_active') IS NOT NULL THEN
        EXECUTE 'ALTER INDEX swingtrader.idx_public_screenings_active RENAME TO idx_market_screenings_active';
    END IF;
    IF to_regclass(v_schema || '.idx_public_screenings_requested') IS NOT NULL THEN
        EXECUTE 'ALTER INDEX swingtrader.idx_public_screenings_requested RENAME TO idx_market_screenings_requested';
    END IF;
    IF to_regclass(v_schema || '.idx_public_screenings_author') IS NOT NULL THEN
        EXECUTE 'ALTER INDEX swingtrader.idx_public_screenings_author RENAME TO idx_market_screenings_author';
    END IF;
    IF to_regclass(v_schema || '.idx_public_screenings_download_count') IS NOT NULL THEN
        EXECUTE 'ALTER INDEX swingtrader.idx_public_screenings_download_count RENAME TO idx_market_screenings_download_count';
    END IF;
    IF to_regclass(v_schema || '.idx_public_screening_subs_screening') IS NOT NULL THEN
        EXECUTE 'ALTER INDEX swingtrader.idx_public_screening_subs_screening RENAME TO idx_market_screening_subs_screening';
    END IF;
    IF to_regclass(v_schema || '.idx_public_screening_subs_user') IS NOT NULL THEN
        EXECUTE 'ALTER INDEX swingtrader.idx_public_screening_subs_user RENAME TO idx_market_screening_subs_user';
    END IF;
    IF to_regclass(v_schema || '.idx_public_screening_results_screening') IS NOT NULL THEN
        EXECUTE 'ALTER INDEX swingtrader.idx_public_screening_results_screening RENAME TO idx_market_screening_results_screening';
    END IF;
    IF to_regclass(v_schema || '.idx_public_screening_results_status') IS NOT NULL THEN
        EXECUTE 'ALTER INDEX swingtrader.idx_public_screening_results_status RENAME TO idx_market_screening_results_status';
    END IF;
    IF to_regclass(v_schema || '.idx_public_screening_results_triggered') IS NOT NULL THEN
        EXECUTE 'ALTER INDEX swingtrader.idx_public_screening_results_triggered RENAME TO idx_market_screening_results_triggered';
    END IF;
    IF to_regclass(v_schema || '.idx_psr_rows_result') IS NOT NULL THEN
        EXECUTE 'ALTER INDEX swingtrader.idx_psr_rows_result RENAME TO idx_msr_rows_result';
    END IF;
    IF to_regclass(v_schema || '.idx_psr_rows_screening') IS NOT NULL THEN
        EXECUTE 'ALTER INDEX swingtrader.idx_psr_rows_screening RENAME TO idx_msr_rows_screening';
    END IF;
    IF to_regclass(v_schema || '.idx_psr_rows_symbol') IS NOT NULL THEN
        EXECUTE 'ALTER INDEX swingtrader.idx_psr_rows_symbol RENAME TO idx_msr_rows_symbol';
    END IF;
    IF to_regclass(v_schema || '.idx_psr_rows_dataset') IS NOT NULL THEN
        EXECUTE 'ALTER INDEX swingtrader.idx_psr_rows_dataset RENAME TO idx_msr_rows_dataset';
    END IF;
    IF to_regclass(v_schema || '.idx_psr_results_bulk_analysis_queued') IS NOT NULL THEN
        EXECUTE 'ALTER INDEX swingtrader.idx_psr_results_bulk_analysis_queued RENAME TO idx_msr_results_bulk_analysis_queued';
    END IF;
    IF to_regclass(v_schema || '.idx_early_access_signups_screening') IS NOT NULL THEN
        EXECUTE 'ALTER INDEX swingtrader.idx_early_access_signups_screening RENAME TO idx_early_access_signups_market_screening';
    END IF;

    -- Auto-generated PK / unique-constraint indexes. PG doesn't auto-rename
    -- these when their table or column is renamed; do it explicitly so a
    -- `\d` listing stays consistent with the new naming.
    IF to_regclass(v_schema || '.public_screenings_pkey') IS NOT NULL THEN
        EXECUTE 'ALTER INDEX swingtrader.public_screenings_pkey RENAME TO market_screenings_pkey';
    END IF;
    IF to_regclass(v_schema || '.public_screening_results_pkey') IS NOT NULL THEN
        EXECUTE 'ALTER INDEX swingtrader.public_screening_results_pkey RENAME TO market_screening_results_pkey';
    END IF;
    IF to_regclass(v_schema || '.public_screening_result_rows_pkey') IS NOT NULL THEN
        EXECUTE 'ALTER INDEX swingtrader.public_screening_result_rows_pkey RENAME TO market_screening_result_rows_pkey';
    END IF;
    IF to_regclass(v_schema || '.public_screening_subscriptions_pkey') IS NOT NULL THEN
        EXECUTE 'ALTER INDEX swingtrader.public_screening_subscriptions_pkey RENAME TO market_screening_subscriptions_pkey';
    END IF;
    IF to_regclass(v_schema || '.public_screenings_slug_key') IS NOT NULL THEN
        EXECUTE 'ALTER INDEX swingtrader.public_screenings_slug_key RENAME TO market_screenings_slug_key';
    END IF;
    IF to_regclass(v_schema || '.public_screening_subscriptions_user_id_public_screening_id_key') IS NOT NULL THEN
        EXECUTE 'ALTER INDEX swingtrader.public_screening_subscriptions_user_id_public_screening_id_key
                 RENAME TO market_screening_subscriptions_user_id_market_screening_id_key';
    END IF;

END
$migration$;


-- ── Download incrementer body (outside the DO block so we can use $$ quoting) ──

CREATE OR REPLACE FUNCTION swingtrader.increment_market_screening_download(
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
    UPDATE swingtrader.market_screenings
       SET download_count = download_count + 1
     WHERE id = p_id
       AND is_published = TRUE
    RETURNING download_count INTO v_new_count;

    RETURN v_new_count;
END;
$$;

REVOKE ALL ON FUNCTION swingtrader.increment_market_screening_download(UUID) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION swingtrader.increment_market_screening_download(UUID) TO service_role;

COMMIT;
