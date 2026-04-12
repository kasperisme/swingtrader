-- Align delivery_method server default with 20260412200000_daily_narrative.sql (new rows default to 'both')

ALTER TABLE swingtrader.user_narrative_preferences
    ALTER COLUMN delivery_method SET DEFAULT 'both';
