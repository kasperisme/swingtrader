CREATE TABLE IF NOT EXISTS swingtrader.user_trading_strategy (
  user_id    UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  strategy   TEXT NOT NULL DEFAULT '',
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE swingtrader.user_trading_strategy ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users manage own trading strategy"
  ON swingtrader.user_trading_strategy
  FOR ALL
  USING  (auth.uid() = user_id)
  WITH CHECK (auth.uid() = user_id);
