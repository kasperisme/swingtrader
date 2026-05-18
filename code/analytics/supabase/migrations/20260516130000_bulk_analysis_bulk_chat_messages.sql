-- Thread for the screenings "All tickers" AI tab (user prompt + run summary).

ALTER TABLE swingtrader.user_bulk_analysis_jobs
    ADD COLUMN IF NOT EXISTS bulk_chat_messages JSONB NOT NULL DEFAULT '[]'::jsonb;
