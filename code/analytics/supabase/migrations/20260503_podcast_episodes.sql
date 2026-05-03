CREATE TABLE IF NOT EXISTS swingtrader.podcast_episodes (
    id SERIAL PRIMARY KEY,
    date DATE NOT NULL,
    title TEXT NOT NULL,
    episode_url TEXT,
    duration_seconds INTEGER,
    script_word_count INTEGER,
    elevenlabs_chars INTEGER,
    estimated_cost_usd REAL,
    status TEXT DEFAULT 'published',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS podcast_episodes_date_idx ON swingtrader.podcast_episodes (date DESC);
