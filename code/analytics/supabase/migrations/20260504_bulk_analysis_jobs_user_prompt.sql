-- ---------------------------------------------------------------------------
-- Add a user-provided prompt to bulk-analysis jobs.
--
-- The UI now asks the user "what should we look for?" before kicking off the
-- job; that string is stored here and passed to the Ollama analyst alongside
-- the standard technical-analysis snapshot. NULL = use the default prompt.
-- ---------------------------------------------------------------------------

ALTER TABLE swingtrader.user_bulk_analysis_jobs
    ADD COLUMN IF NOT EXISTS user_prompt TEXT;
