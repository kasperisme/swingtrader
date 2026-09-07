-- ---------------------------------------------------------------------------
-- user_ticker_chart_workspace.note — the free-text note per user per ticker
--
-- This migration is referenced BY NAME in app/actions/chart-workspace.ts, which
-- catches the missing-column error and tells the user to "apply migration
-- 20260421120000_user_ticker_chart_workspace_note.sql". The file never existed.
-- The read path (`.select("annotations, ai_chat_messages, note")`) has a
-- fallback that retries without the column, but chartWorkspaceNoteSave() has
-- none, so saving a note surfaced:
--
--   column user_ticker_chart_workspace.note does not exist
--
-- The filename deliberately keeps the timestamp the error message quotes, even
-- though later migrations have already been applied — renaming it would leave
-- that message pointing at nothing.
--
-- Nothing else is needed. The RLS policies from
-- 20260419120000_user_ticker_chart_workspace.sql are table-wide (USING
-- auth.uid() = user_id for select/insert/update/delete) and the GRANTs are
-- table-level, so both extend to a new column automatically. No backfill: an
-- absent note is NULL, which the action already maps to "" on read.
-- ---------------------------------------------------------------------------

ALTER TABLE swingtrader.user_ticker_chart_workspace
    ADD COLUMN IF NOT EXISTS note TEXT;

COMMENT ON COLUMN swingtrader.user_ticker_chart_workspace.note IS
    'Free-text note the user keeps against this ticker, shown in the quote page '
    'chart workspace. NULL when cleared; the app renders NULL as an empty string.';
