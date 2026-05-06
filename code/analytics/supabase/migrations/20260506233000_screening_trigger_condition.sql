-- Add a user-defined send gate. When condition_enabled=true the agent only
-- sends to Telegram if trigger_condition (plain English) evaluates true
-- against the data the LLM gathered.
ALTER TABLE swingtrader.user_scheduled_screenings
  ADD COLUMN IF NOT EXISTS condition_enabled boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS trigger_condition text;

ALTER TABLE swingtrader.user_scheduled_screenings
  ADD CONSTRAINT chk_trigger_condition_when_enabled
  CHECK (
    NOT condition_enabled
    OR (trigger_condition IS NOT NULL AND length(btrim(trigger_condition)) > 0)
  );
