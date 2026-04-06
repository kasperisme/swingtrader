# build_vectors_cli

Fetches fundamental data from FMP and builds rank-normalised company embedding vectors across 43 dimensions in 8 clusters. Vectors are stored in DuckDB and cached to disk.

## Usage

```bash
# Build vectors for a list of tickers
python -m news_impact.build_vectors_cli --tickers AAPL MSFT NVDA JPM XOM

# Load tickers from a file (one per line, # comments ignored)
python -m news_impact.build_vectors_cli --file tickers.txt

# Refresh all tickers already in Supabase (daily update pattern)
python -m news_impact.build_vectors_cli --from-db
python -m news_impact.build_vectors_cli --from-db --no-cache

# Build vectors for an entire exchange
python -m news_impact.build_vectors_cli --exchange NASDAQ
python -m news_impact.build_vectors_cli --exchange NYSE NASDAQ

# Exchange build with liquidity filters (skip micro-caps and penny stocks)
python -m news_impact.build_vectors_cli --exchange NASDAQ --min-mktcap 1e9 --min-price 5

# Print a compact dimension table per company
python -m news_impact.build_vectors_cli --tickers AAPL MSFT --show

# Force fresh FMP fetch, bypass cache
python -m news_impact.build_vectors_cli --tickers AAPL --no-cache --show

# Tune batch size (vectors are persisted after each batch; safe to interrupt)
python -m news_impact.build_vectors_cli --exchange NYSE --batch-size 50
```

## Options

### Ticker source (mutually exclusive, one required)

| Flag | Description |
|---|---|
| `--tickers TICK ...` | Space-separated list of ticker symbols |
| `--file PATH` | Text file with one ticker per line (`#` comments ignored) |
| `--from-db` | Refresh all tickers that already have a vector in Supabase |
| `--exchange EXCH ...` | Fetch all active, non-ETF tickers from one or more exchanges via FMP screener |

### Exchange filters (only with `--exchange`)

| Flag | Default | Description |
|---|---|---|
| `--min-mktcap DOLLARS` | — | Skip tickers with market cap below this value (e.g. `1e9` for $1 B) |
| `--min-price DOLLARS` | — | Skip tickers priced below this value (e.g. `5`) |

### Other options

| Flag | Default | Description |
|---|---|---|
| `--batch-size N` | `100` | Tickers processed per batch; DB is flushed after each batch so an interrupted run loses at most one batch |
| `--show` | — | Print a compact dimension table for each ticker after building |
| `--no-cache` | — | Bypass disk/DB cache and fetch fresh data from FMP |

## Output (--show)

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
AAPL  Apple Inc.  |  Technology  |  $3.8T
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
GROWTH       rev_growth: 1.00  eps_growth: 1.00  acceleration: 0.80
VALUATION    multiple: 0.80    value: 0.40        momentum: 0.80
FINANCIAL    debt: 0.40        health: 0.40       quality: 0.80
MACRO        rate_sens: 0.60   dollar: 0.60       inflation: 0.80
SECTOR       tech: 0.80        finl: 0.50         hlth: 0.60
BUSINESS     recurring: 0.70   pricing: 0.80      capex: 0.40
GEOGRAPHY    china: 0.50       domestic: 0.60     tariff: 0.60
MARKET       inst_appeal: 0.60 inst_chg: 0.80
```

All scores are rank-normalised 0–1 within the universe of tickers passed in a single run. A score of 1.0 means highest in the group for that dimension.

## Dimension clusters

| Cluster | What it captures |
|---|---|
| `MACRO_SENSITIVITY` | Interest rate, dollar, inflation, credit spread exposure |
| `SECTOR_ROTATION` | GICS sector one-hot encoding |
| `BUSINESS_MODEL` | Revenue type, pricing power, capex intensity |
| `FINANCIAL_STRUCTURE` | Debt burden, health, earnings quality |
| `GROWTH_PROFILE` | Revenue/EPS growth, acceleration, forward estimates |
| `VALUATION_POSITIONING` | Multiples, momentum, crowding |
| `GEOGRAPHY_TRADE` | China, EM, domestic, tariff exposure |
| `MARKET_BEHAVIOUR` | Institutional ownership and changes |

## Caching & persistence

On each run, fresh vectors are:
1. Written to `news_impact/cache/{TICKER}_{YYYY-MM-DD}.json`
2. Upserted into the `company_vectors` table in DuckDB

On subsequent runs with `use_cache=True` (default), the DB is checked first (TTL: 24h), then the disk cache, before falling back to FMP.

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `FMP_API_KEY` | — | FMP API key (also accepts legacy `APIKEY`) |
| `FMP_BASE_URL` | `https://financialmodelingprep.com/stable/` | FMP base URL |
| `HANS_DUCKDB_PATH` | `data/swingtrader.duckdb` | DuckDB file path |
