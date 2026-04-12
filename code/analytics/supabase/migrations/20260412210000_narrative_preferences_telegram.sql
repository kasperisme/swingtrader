-- Telegram delivery: chat_id column + delivery_method allows 'telegram' (replaces 'email')

ALTER TABLE swingtrader.user_narrative_preferences
    ADD COLUMN IF NOT EXISTS telegram_chat_id VARCHAR;

UPDATE swingtrader.user_narrative_preferences
SET delivery_method = 'in_app'
WHERE delivery_method = 'email';

ALTER TABLE swingtrader.user_narrative_preferences
    DROP CONSTRAINT IF EXISTS user_narrative_preferences_delivery_method_check;

ALTER TABLE swingtrader.user_narrative_preferences
    ADD CONSTRAINT user_narrative_preferences_delivery_method_check
    CHECK (delivery_method IN ('telegram', 'in_app', 'both'));
