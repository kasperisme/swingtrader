-- ---------------------------------------------------------------------------
-- tickers: universe of actively-traded NYSE and NASDAQ stocks
-- Seeded via scripts/seed_tickers.py (FMP company-screener endpoint).
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS swingtrader.tickers (
    symbol              VARCHAR     NOT NULL,
    exchange            VARCHAR     NOT NULL,       -- 'NYSE' | 'NASDAQ'
    company_name        VARCHAR,
    sector              VARCHAR,
    industry            VARCHAR,
    market_cap          BIGINT,
    price               DOUBLE PRECISION,
    volume              BIGINT,
    beta                DOUBLE PRECISION,
    country             VARCHAR,
    is_actively_trading BOOLEAN     NOT NULL DEFAULT TRUE,
    last_seen_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (symbol, exchange)
);

CREATE INDEX IF NOT EXISTS idx_tickers_exchange ON swingtrader.tickers (exchange);
CREATE INDEX IF NOT EXISTS idx_tickers_sector   ON swingtrader.tickers (sector);

-- Permissions (inherit same pattern as rest of schema)
GRANT ALL ON swingtrader.tickers TO anon, authenticated, service_role;
