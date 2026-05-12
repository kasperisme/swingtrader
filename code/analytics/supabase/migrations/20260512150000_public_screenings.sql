-- ---------------------------------------------------------------------------
-- Public Screenings: curated screenings that admins publish and users subscribe to.
--
--   public_screenings               — admin-owned screening definitions
--   public_screening_subscriptions  — user ↔ public_screening junction
--   public_screening_results        — shared per-run history (one row per run)
--
-- Execution model: shared. The screening runs ONCE per schedule tick; results
-- fan out to all subscribers (Telegram + in-app feed). Writes are performed
-- exclusively via service_role; admin authorization is enforced in app code
-- via the ADMIN_USER_IDS env var, not via RLS.
-- ---------------------------------------------------------------------------


-- ── public_screenings ───────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS swingtrader.public_screenings (
    id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    author_user_id   UUID        NOT NULL REFERENCES auth.users (id) ON DELETE RESTRICT,
    slug             TEXT        NOT NULL UNIQUE,
    script_key       TEXT        NOT NULL,
    name             TEXT        NOT NULL,
    description      TEXT,
    category         TEXT,
    schedule         TEXT        NOT NULL DEFAULT '0 7 * * 1-5',
    timezone         TEXT        NOT NULL DEFAULT 'America/New_York',
    is_active        BOOLEAN     NOT NULL DEFAULT TRUE,
    is_published     BOOLEAN     NOT NULL DEFAULT FALSE,
    next_run_at      TIMESTAMPTZ,
    last_run_at      TIMESTAMPTZ,
    last_triggered   BOOLEAN,
    run_requested_at TIMESTAMPTZ,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_public_screenings_published
    ON swingtrader.public_screenings (is_published, is_active)
    WHERE is_published = TRUE;

CREATE INDEX IF NOT EXISTS idx_public_screenings_active
    ON swingtrader.public_screenings (is_active)
    WHERE is_active = TRUE;

CREATE INDEX IF NOT EXISTS idx_public_screenings_requested
    ON swingtrader.public_screenings (run_requested_at)
    WHERE run_requested_at IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_public_screenings_author
    ON swingtrader.public_screenings (author_user_id, created_at DESC);

CREATE OR REPLACE FUNCTION swingtrader.touch_public_screenings_updated_at()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN NEW.updated_at = NOW(); RETURN NEW; END; $$;

DROP TRIGGER IF EXISTS trg_public_screenings_updated_at ON swingtrader.public_screenings;
CREATE TRIGGER trg_public_screenings_updated_at
    BEFORE UPDATE ON swingtrader.public_screenings
    FOR EACH ROW EXECUTE FUNCTION swingtrader.touch_public_screenings_updated_at();

ALTER TABLE swingtrader.public_screenings ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS public_screenings_select_published ON swingtrader.public_screenings;
CREATE POLICY public_screenings_select_published ON swingtrader.public_screenings
    FOR SELECT TO authenticated USING (is_published = TRUE);

GRANT ALL    ON swingtrader.public_screenings TO service_role;
GRANT SELECT ON swingtrader.public_screenings TO authenticated;


-- ── public_screening_subscriptions ──────────────────────────────────────────

CREATE TABLE IF NOT EXISTS swingtrader.public_screening_subscriptions (
    id                    UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id               UUID        NOT NULL REFERENCES auth.users (id) ON DELETE CASCADE,
    public_screening_id   UUID        NOT NULL REFERENCES swingtrader.public_screenings (id) ON DELETE CASCADE,
    notifications_enabled BOOLEAN     NOT NULL DEFAULT TRUE,
    subscribed_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, public_screening_id)
);

CREATE INDEX IF NOT EXISTS idx_public_screening_subs_screening
    ON swingtrader.public_screening_subscriptions (public_screening_id);

CREATE INDEX IF NOT EXISTS idx_public_screening_subs_user
    ON swingtrader.public_screening_subscriptions (user_id, subscribed_at DESC);

ALTER TABLE swingtrader.public_screening_subscriptions ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS public_screening_subs_select_own ON swingtrader.public_screening_subscriptions;
CREATE POLICY public_screening_subs_select_own ON swingtrader.public_screening_subscriptions
    FOR SELECT TO authenticated USING (auth.uid() = user_id);

DROP POLICY IF EXISTS public_screening_subs_insert_own ON swingtrader.public_screening_subscriptions;
CREATE POLICY public_screening_subs_insert_own ON swingtrader.public_screening_subscriptions
    FOR INSERT TO authenticated WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS public_screening_subs_update_own ON swingtrader.public_screening_subscriptions;
CREATE POLICY public_screening_subs_update_own ON swingtrader.public_screening_subscriptions
    FOR UPDATE TO authenticated
    USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS public_screening_subs_delete_own ON swingtrader.public_screening_subscriptions;
CREATE POLICY public_screening_subs_delete_own ON swingtrader.public_screening_subscriptions
    FOR DELETE TO authenticated USING (auth.uid() = user_id);

GRANT ALL ON swingtrader.public_screening_subscriptions TO anon, authenticated, service_role;


-- ── public_screening_results ────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS swingtrader.public_screening_results (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    public_screening_id UUID        NOT NULL REFERENCES swingtrader.public_screenings (id) ON DELETE CASCADE,
    run_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at          TIMESTAMPTZ,
    status              TEXT        NOT NULL DEFAULT 'due'
        CHECK (status IN ('due', 'running', 'done', 'error')),
    triggered           BOOLEAN     NOT NULL DEFAULT FALSE,
    summary             TEXT,
    data_used           JSONB,
    error               TEXT,
    is_test             BOOLEAN     NOT NULL DEFAULT FALSE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_public_screening_results_screening
    ON swingtrader.public_screening_results (public_screening_id, run_at DESC);

CREATE INDEX IF NOT EXISTS idx_public_screening_results_status
    ON swingtrader.public_screening_results (status, run_at)
    WHERE status IN ('due', 'running');

CREATE INDEX IF NOT EXISTS idx_public_screening_results_triggered
    ON swingtrader.public_screening_results (public_screening_id, triggered, run_at DESC)
    WHERE triggered = TRUE;

ALTER TABLE swingtrader.public_screening_results ENABLE ROW LEVEL SECURITY;

-- Results for any *published* screening are readable by authenticated users.
-- This lets the gallery preview recent runs to attract subscribers.
DROP POLICY IF EXISTS public_screening_results_select_published ON swingtrader.public_screening_results;
CREATE POLICY public_screening_results_select_published ON swingtrader.public_screening_results
    FOR SELECT TO authenticated USING (
        EXISTS (
            SELECT 1 FROM swingtrader.public_screenings ps
            WHERE ps.id = public_screening_results.public_screening_id
              AND ps.is_published = TRUE
        )
    );

GRANT ALL    ON swingtrader.public_screening_results TO service_role;
GRANT SELECT ON swingtrader.public_screening_results TO authenticated;
