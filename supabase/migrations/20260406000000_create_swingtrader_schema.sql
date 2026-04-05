-- SwingTrader schema migration
-- Creates all tables in the 'swingtrader' schema.
--
-- Run via:
--   supabase db push
-- or paste into Supabase Dashboard → SQL editor → Run.
--
-- After running, expose the schema in:
--   Supabase Dashboard → Settings → API → Extra search path → add "swingtrader"

CREATE SCHEMA IF NOT EXISTS swingtrader;

-- ---------------------------------------------------------------------------
-- scan_runs: one row per screening run
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS swingtrader.scan_runs (
    id          BIGSERIAL PRIMARY KEY,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    scan_date   DATE        NOT NULL,
    source      VARCHAR     NOT NULL,
    market_json TEXT,
    result_json TEXT
);

-- ---------------------------------------------------------------------------
-- scan_rows: normalised per-stock rows (row_data is JSON text)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS swingtrader.scan_rows (
    id        BIGSERIAL PRIMARY KEY,
    run_id    BIGINT  NOT NULL,
    scan_date DATE    NOT NULL,
    dataset   VARCHAR NOT NULL,
    symbol    VARCHAR,
    row_data  TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_scan_rows_run     ON swingtrader.scan_rows (run_id);
CREATE INDEX IF NOT EXISTS idx_scan_rows_symbol  ON swingtrader.scan_rows (symbol);
CREATE INDEX IF NOT EXISTS idx_scan_rows_dataset ON swingtrader.scan_rows (dataset);

-- ---------------------------------------------------------------------------
-- scan_jobs: background screener process state
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS swingtrader.scan_jobs (
    id               BIGSERIAL PRIMARY KEY,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at       TIMESTAMPTZ NOT NULL,
    finished_at      TIMESTAMPTZ,
    status           VARCHAR     NOT NULL,
    scan_source      VARCHAR     NOT NULL,
    script_rel       VARCHAR     NOT NULL,
    args_json        TEXT,
    pid              INTEGER,
    exit_code        INTEGER,
    scan_run_id      BIGINT,
    stdout_log       TEXT,
    stderr_log       TEXT,
    error_message    TEXT,
    progress_message VARCHAR
);

CREATE INDEX IF NOT EXISTS idx_scan_jobs_status  ON swingtrader.scan_jobs (status);
CREATE INDEX IF NOT EXISTS idx_scan_jobs_started ON swingtrader.scan_jobs (started_at);

-- ---------------------------------------------------------------------------
-- news_articles: article content and metadata
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS swingtrader.news_articles (
    id           BIGSERIAL PRIMARY KEY,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    url          VARCHAR,
    title        VARCHAR,
    body         TEXT    NOT NULL,
    source       VARCHAR,
    article_hash VARCHAR NOT NULL UNIQUE
);

-- ---------------------------------------------------------------------------
-- news_impact_heads: per-cluster LLM scoring results
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS swingtrader.news_impact_heads (
    id             BIGSERIAL        PRIMARY KEY,
    article_id     BIGINT           NOT NULL,
    cluster        VARCHAR          NOT NULL,
    scores_json    TEXT             NOT NULL,
    reasoning_json TEXT,
    confidence     DOUBLE PRECISION NOT NULL,
    model          VARCHAR          NOT NULL,
    latency_ms     INTEGER,
    created_at     TIMESTAMPTZ      NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_news_heads_article ON swingtrader.news_impact_heads (article_id);

-- ---------------------------------------------------------------------------
-- news_impact_vectors: aggregated impact dimension vectors
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS swingtrader.news_impact_vectors (
    id             BIGSERIAL   PRIMARY KEY,
    article_id     BIGINT      NOT NULL UNIQUE,
    impact_json    TEXT        NOT NULL,
    top_dimensions TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- company_vectors: fundamental dimension vectors per ticker per date
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS swingtrader.company_vectors (
    id              BIGSERIAL   PRIMARY KEY,
    ticker          VARCHAR     NOT NULL,
    vector_date     DATE        NOT NULL,
    dimensions_json TEXT        NOT NULL,
    raw_json        TEXT,
    metadata_json   TEXT,
    fetched_at      TIMESTAMPTZ NOT NULL,
    UNIQUE (ticker, vector_date)
);

CREATE INDEX IF NOT EXISTS idx_company_vectors_ticker ON swingtrader.company_vectors (ticker);

-- ---------------------------------------------------------------------------
-- news_article_tickers: ticker mentions extracted from articles
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS swingtrader.news_article_tickers (
    article_id BIGINT  NOT NULL,
    ticker     VARCHAR NOT NULL,
    source     VARCHAR NOT NULL,
    PRIMARY KEY (article_id, ticker)
);

CREATE INDEX IF NOT EXISTS idx_article_tickers_ticker ON swingtrader.news_article_tickers (ticker);

-- ---------------------------------------------------------------------------
-- Permissions
-- Grant anon, authenticated and service_role full access to the schema so
-- PostgREST can serve it once it is added to the extra search path.
-- ---------------------------------------------------------------------------
GRANT USAGE ON SCHEMA swingtrader TO anon, authenticated, service_role;
GRANT ALL ON ALL TABLES    IN SCHEMA swingtrader TO anon, authenticated, service_role;
GRANT ALL ON ALL SEQUENCES IN SCHEMA swingtrader TO anon, authenticated, service_role;

ALTER DEFAULT PRIVILEGES IN SCHEMA swingtrader
    GRANT ALL ON TABLES    TO anon, authenticated, service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA swingtrader
    GRANT ALL ON SEQUENCES TO anon, authenticated, service_role;
