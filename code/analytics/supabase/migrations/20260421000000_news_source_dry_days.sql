-- Track calendar days where a news source stream has been fully exhausted
-- (all available articles fetched/processed, no new content from the API).
-- Used to skip re-polling dry days in future runs.

CREATE TABLE IF NOT EXISTS swingtrader.news_source_dry_days (
    source_stream  VARCHAR NOT NULL,
    day            DATE    NOT NULL,
    marked_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    pages_checked  INTEGER NOT NULL DEFAULT 0,
    articles_found INTEGER NOT NULL DEFAULT 0,
    note           TEXT,
    PRIMARY KEY (source_stream, day)
);

CREATE INDEX IF NOT EXISTS idx_news_source_dry_days_day
    ON swingtrader.news_source_dry_days (day DESC);