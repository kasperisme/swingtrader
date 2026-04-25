-- ---------------------------------------------------------------------------
-- Scheduled Screening Agent: two tables for prompt-driven screening jobs
--
--   user_scheduled_screenings  — job definitions (prompt + schedule)
--   user_screening_results     — per-run history (trigger/no-trigger + summary)
--
-- Delivery follows the daily narrative pattern:
--   - Always persisted to DB (in-app)
--   - Sent via Telegram if user has a chat_id in user_telegram_connections
-- ---------------------------------------------------------------------------

-- ── user_scheduled_screenings ────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS swingtrader.user_scheduled_screenings (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID        NOT NULL REFERENCES auth.users (id) ON DELETE CASCADE,
    name            TEXT        NOT NULL,
    prompt          TEXT        NOT NULL,
    schedule        TEXT        NOT NULL DEFAULT '0 7 * * 1-5',
    timezone        TEXT        NOT NULL DEFAULT 'America/New_York',
    is_active       BOOLEAN     NOT NULL DEFAULT TRUE,
    last_run_at     TIMESTAMPTZ,
    last_triggered  BOOLEAN,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_scheduled_screenings_user
    ON swingtrader.user_scheduled_screenings (user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_scheduled_screenings_active
    ON swingtrader.user_scheduled_screenings (is_active) WHERE is_active = TRUE;

CREATE OR REPLACE FUNCTION swingtrader.touch_scheduled_screenings_updated_at()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN NEW.updated_at = NOW(); RETURN NEW; END; $$;

DROP TRIGGER IF EXISTS trg_scheduled_screenings_updated_at ON swingtrader.user_scheduled_screenings;
CREATE TRIGGER trg_scheduled_screenings_updated_at
    BEFORE UPDATE ON swingtrader.user_scheduled_screenings
    FOR EACH ROW EXECUTE FUNCTION swingtrader.touch_scheduled_screenings_updated_at();

ALTER TABLE swingtrader.user_scheduled_screenings ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS screenings_select_own ON swingtrader.user_scheduled_screenings;
CREATE POLICY screenings_select_own ON swingtrader.user_scheduled_screenings
    FOR SELECT TO authenticated USING (auth.uid() = user_id);

DROP POLICY IF EXISTS screenings_insert_own ON swingtrader.user_scheduled_screenings;
CREATE POLICY screenings_insert_own ON swingtrader.user_scheduled_screenings
    FOR INSERT TO authenticated WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS screenings_update_own ON swingtrader.user_scheduled_screenings;
CREATE POLICY screenings_update_own ON swingtrader.user_scheduled_screenings
    FOR UPDATE TO authenticated
    USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS screenings_delete_own ON swingtrader.user_scheduled_screenings;
CREATE POLICY screenings_delete_own ON swingtrader.user_scheduled_screenings
    FOR DELETE TO authenticated USING (auth.uid() = user_id);

GRANT ALL ON swingtrader.user_scheduled_screenings TO anon, authenticated, service_role;


-- ── user_screening_results ──────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS swingtrader.user_screening_results (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    screening_id    UUID        NOT NULL REFERENCES swingtrader.user_scheduled_screenings (id) ON DELETE CASCADE,
    user_id         UUID        NOT NULL REFERENCES auth.users (id) ON DELETE CASCADE,
    run_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    triggered       BOOLEAN     NOT NULL DEFAULT FALSE,
    summary         TEXT,
    data_used       JSONB,
    delivered       BOOLEAN     NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_screening_results_screening
    ON swingtrader.user_screening_results (screening_id, run_at DESC);

CREATE INDEX IF NOT EXISTS idx_screening_results_user
    ON swingtrader.user_screening_results (user_id, run_at DESC);

CREATE INDEX IF NOT EXISTS idx_screening_results_triggered
    ON swingtrader.user_screening_results (user_id, triggered, run_at DESC)
    WHERE triggered = TRUE;

ALTER TABLE swingtrader.user_screening_results ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS screening_results_select_own ON swingtrader.user_screening_results;
CREATE POLICY screening_results_select_own ON swingtrader.user_screening_results
    FOR SELECT TO authenticated USING (auth.uid() = user_id);

GRANT ALL ON swingtrader.user_screening_results TO service_role;
GRANT SELECT ON swingtrader.user_screening_results TO authenticated;
