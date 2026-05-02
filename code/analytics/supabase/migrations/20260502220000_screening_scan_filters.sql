-- Add scan_filters JSONB column to store ScreeningsFilters for agent ticker scoping
ALTER TABLE swingtrader.user_scheduled_screenings
  ADD COLUMN IF NOT EXISTS scan_filters jsonb DEFAULT NULL;
