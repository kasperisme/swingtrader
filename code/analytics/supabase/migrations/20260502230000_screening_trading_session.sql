-- Add trading_session column to gate agent runs to market hours
ALTER TABLE swingtrader.user_scheduled_screenings
  ADD COLUMN IF NOT EXISTS trading_session text NOT NULL DEFAULT 'none';

-- Only allow valid values
ALTER TABLE swingtrader.user_scheduled_screenings
  ADD CONSTRAINT chk_trading_session CHECK (trading_session IN ('none', 'nyse'));