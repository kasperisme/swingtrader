-- ---------------------------------------------------------------------------
-- Daily Narrative: three new tables
--
--   user_portfolio_alerts    — stop losses / take profits / price alerts per ticker
--   user_narrative_preferences — when and how to deliver the daily narrative
--   daily_narratives           — generated narratives (one per user per date)
-- ---------------------------------------------------------------------------

-- ── user_portfolio_alerts ─────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS swingtrader.user_portfolio_alerts (
    id            UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       UUID        NOT NULL REFERENCES auth.users (id) ON DELETE CASCADE,
    ticker        VARCHAR     NOT NULL,
    alert_type    VARCHAR     NOT NULL CHECK (alert_type IN ('stop_loss', 'take_profit', 'price_alert')),
    price         NUMERIC     NOT NULL CHECK (price > 0),
    -- 'below': fire when market price drops below this level (stop loss)
    -- 'above': fire when market price rises above this level (take profit / alert)
    direction     VARCHAR     NOT NULL CHECK (direction IN ('above', 'below')),
    notes         TEXT,
    is_active     BOOLEAN     NOT NULL DEFAULT TRUE,
    triggered_at  TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_portfolio_alerts_user_ticker
    ON swingtrader.user_portfolio_alerts (user_id, ticker);

CREATE OR REPLACE FUNCTION swingtrader.touch_portfolio_alerts_updated_at()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN NEW.updated_at = NOW(); RETURN NEW; END; $$;

DROP TRIGGER IF EXISTS trg_portfolio_alerts_updated_at ON swingtrader.user_portfolio_alerts;
CREATE TRIGGER trg_portfolio_alerts_updated_at
    BEFORE UPDATE ON swingtrader.user_portfolio_alerts
    FOR EACH ROW EXECUTE FUNCTION swingtrader.touch_portfolio_alerts_updated_at();

ALTER TABLE swingtrader.user_portfolio_alerts ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS alerts_select_own ON swingtrader.user_portfolio_alerts;
CREATE POLICY alerts_select_own ON swingtrader.user_portfolio_alerts
    FOR SELECT TO authenticated USING (auth.uid() = user_id);

DROP POLICY IF EXISTS alerts_insert_own ON swingtrader.user_portfolio_alerts;
CREATE POLICY alerts_insert_own ON swingtrader.user_portfolio_alerts
    FOR INSERT TO authenticated WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS alerts_update_own ON swingtrader.user_portfolio_alerts;
CREATE POLICY alerts_update_own ON swingtrader.user_portfolio_alerts
    FOR UPDATE TO authenticated
    USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS alerts_delete_own ON swingtrader.user_portfolio_alerts;
CREATE POLICY alerts_delete_own ON swingtrader.user_portfolio_alerts
    FOR DELETE TO authenticated USING (auth.uid() = user_id);

GRANT ALL ON swingtrader.user_portfolio_alerts TO anon, authenticated, service_role;


-- ── user_narrative_preferences ────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS swingtrader.user_narrative_preferences (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             UUID        NOT NULL UNIQUE REFERENCES auth.users (id) ON DELETE CASCADE,
    is_enabled          BOOLEAN     NOT NULL DEFAULT TRUE,
    -- Local time to generate and deliver (default: 08:30 US Eastern = premarket)
    delivery_time       TIME        NOT NULL DEFAULT '08:30:00',
    timezone            VARCHAR     NOT NULL DEFAULT 'America/New_York',
    -- 'in_app': store in DB only; 'telegram': send Telegram DM; 'both': store + telegram
    delivery_method     VARCHAR     NOT NULL DEFAULT 'in_app'
                            CHECK (delivery_method IN ('telegram', 'in_app', 'both')),
    -- Telegram chat_id for the user (obtained when user /starts the bot)
    telegram_chat_id    VARCHAR,
    -- how many hours of news to look back
    lookback_hours      INTEGER     NOT NULL DEFAULT 24,
    include_portfolio   BOOLEAN     NOT NULL DEFAULT TRUE,
    include_screenings  BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE OR REPLACE FUNCTION swingtrader.touch_narrative_prefs_updated_at()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN NEW.updated_at = NOW(); RETURN NEW; END; $$;

DROP TRIGGER IF EXISTS trg_narrative_prefs_updated_at ON swingtrader.user_narrative_preferences;
CREATE TRIGGER trg_narrative_prefs_updated_at
    BEFORE UPDATE ON swingtrader.user_narrative_preferences
    FOR EACH ROW EXECUTE FUNCTION swingtrader.touch_narrative_prefs_updated_at();

ALTER TABLE swingtrader.user_narrative_preferences ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS narrative_prefs_select_own ON swingtrader.user_narrative_preferences;
CREATE POLICY narrative_prefs_select_own ON swingtrader.user_narrative_preferences
    FOR SELECT TO authenticated USING (auth.uid() = user_id);

DROP POLICY IF EXISTS narrative_prefs_insert_own ON swingtrader.user_narrative_preferences;
CREATE POLICY narrative_prefs_insert_own ON swingtrader.user_narrative_preferences
    FOR INSERT TO authenticated WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS narrative_prefs_update_own ON swingtrader.user_narrative_preferences;
CREATE POLICY narrative_prefs_update_own ON swingtrader.user_narrative_preferences
    FOR UPDATE TO authenticated
    USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);

GRANT ALL ON swingtrader.user_narrative_preferences TO anon, authenticated, service_role;


-- ── daily_narratives ─────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS swingtrader.daily_narratives (
    id                   UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id              UUID        NOT NULL REFERENCES auth.users (id) ON DELETE CASCADE,
    narrative_date       DATE        NOT NULL,
    -- Per-section structured JSON (see narrative_generator.py for schema)
    portfolio_section    JSONB,   -- [{ticker, sentiment, narrative, action, articles}]
    screening_section    JSONB,   -- [{ticker, narrative, articles}]
    alert_warnings       JSONB,   -- [{ticker, alert_type, alert_price, pct_away, narrative}]
    market_pulse         TEXT,    -- Free-text macro summary from Ollama
    model                VARCHAR,
    latency_ms           INTEGER,
    generated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    delivered_at         TIMESTAMPTZ,          -- NULL = not yet sent by email
    UNIQUE (user_id, narrative_date)
);

CREATE INDEX IF NOT EXISTS idx_daily_narratives_user_date
    ON swingtrader.daily_narratives (user_id, narrative_date DESC);

ALTER TABLE swingtrader.daily_narratives ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS narratives_select_own ON swingtrader.daily_narratives;
CREATE POLICY narratives_select_own ON swingtrader.daily_narratives
    FOR SELECT TO authenticated USING (auth.uid() = user_id);

GRANT ALL ON swingtrader.daily_narratives TO anon, authenticated, service_role;
