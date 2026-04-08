# score_news_cli

Embeds a news article into an impact vector by running 8 parallel local LLM calls — one per dimension cluster — then optionally scores a list of companies against that vector to surface tailwinds and headwinds.

Requires [Ollama](https://ollama.com) running locally with a model pulled (default: `devstral`).

## Usage

```bash
# Embed article only — no tickers needed
python -m news_impact.score_news_cli --text "Fed raises rates 50bps..."
python -m news_impact.score_news_cli --url "https://..."
python -m news_impact.score_news_cli --file article.txt

# Embed + score specific companies
python -m news_impact.score_news_cli --text "..." --tickers AAPL MSFT NVDA JPM XOM

# Use cached company vectors (no FMP refetch)
python -m news_impact.score_news_cli --text "..." --tickers AAPL MSFT --use-cache

# Re-score an article already in the DB (overwrites stored heads + vector)
python -m news_impact.score_news_cli --text "..." --refresh

# Score without writing to DuckDB
python -m news_impact.score_news_cli --text "..." --no-persist

# Fetch and score latest FMP stock news (market-wide)
python -m news_impact.score_news_cli --fmp-news
python -m news_impact.score_news_cli --fmp-news --limit 30

# Fetch FMP news filtered to specific tickers
python -m news_impact.score_news_cli --fmp-news --tickers AAPL MSFT NVDA

# Fetch FMP news for a date window (inclusive)
python -m news_impact.score_news_cli --fmp-news --from 2025-11-01 --to 2025-11-30

# Date window + ticker filter
python -m news_impact.score_news_cli --fmp-news --tickers AAPL --from 2025-11-01 --to 2025-11-30

# Paginate through older FMP news
python -m news_impact.score_news_cli --fmp-news --limit 20 --page 2
```

## Options

### Article source (mutually exclusive, one required)

| Flag | Description |
|---|---|
| `--url URL` | Fetch article from a URL (fetches full article, falls back to summary) |
| `--text TEXT` | Article text supplied inline |
| `--file PATH` | Read article text from a local file |
| `--fmp-news` | Fetch latest stock news from FMP and score each article |

### FMP news options (only with `--fmp-news`)

| Flag | Default | Description |
|---|---|---|
| `--limit N` | `20` | Max articles to fetch per call |
| `--page N` | `0` | Page offset for pagination (0-indexed) |
| `--from YYYY-MM-DD` | — | Start date filter for FMP fetch (inclusive) |
| `--to YYYY-MM-DD` | — | End date filter for FMP fetch (inclusive) |
| `--tickers` | — | Filter FMP news to these tickers only |

### Date range filtering with `--from` / `--to`

Use `--from` and `--to` with `--fmp-news` to constrain fetches to a specific date range.

- Format: `YYYY-MM-DD` (for example: `2025-11-01`)
- Can be used independently:
  - `--from` only: fetch from that date onward
  - `--to` only: fetch up to that date
- Can be combined with `--tickers`, `--limit`, and `--page`

Examples:

```bash
# Entire month window
python -m news_impact.score_news_cli --fmp-news --from 2025-11-01 --to 2025-11-30

# From a date onward
python -m news_impact.score_news_cli --fmp-news --from 2025-11-01

# Up to a date
python -m news_impact.score_news_cli --fmp-news --to 2025-11-30
```

### Scoring options

| Flag | Description |
|---|---|
| `--tickers TICK ...` | Score these tickers against the impact vector (merged with auto-extracted) |
| `--use-cache` | Load company vectors from disk/DB cache instead of re-fetching from FMP |
| `--top-n N` | Max companies per side in tailwinds/headwinds output (default: `6`) |

### Persistence options

| Flag | Description |
|---|---|
| `--no-persist` | Score without writing anything to DuckDB |
| `--refresh` | Re-score even if the article is already in the DB (overwrites stored heads and vector) |
| `--title TITLE` | Article title for storage and display |
| `--source SOURCE` | Source label stored with the article (e.g. `bloomberg`, `fmp`) |

### Other

| Flag | Description |
|---|---|
| `--verbose` / `-v` | Enable debug logging |

## Output

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Article: Fed raises rates by 50bps, surprises markets...
article_id=3
Companies mentioned: JPM, BAC, GS

Cluster confidence:
  MACRO_SENSITIVITY      ██████████  0.94
  FINANCIAL_STRUCTURE    ████████░░  0.81
  VALUATION_POSITIONING  ██████░░░░  0.63
  SECTOR_ROTATION        █████░░░░░  0.54
  GROWTH_PROFILE         ███░░░░░░░  0.31
  GEOGRAPHY_TRADE        █░░░░░░░░░  0.14
  BUSINESS_MODEL         █░░░░░░░░░  0.09
  MARKET_BEHAVIOUR       ░░░░░░░░░░  0.03

Top signals:
  interest_rate_sensitivity    -0.87
  debt_burden                  -0.81
  sector_financials            +0.76
  valuation_multiple           -0.68
  floating_rate_debt_ratio     -0.62

TAILWINDS              HEADWINDS
  JPM   +0.81          NVDA  -0.89
  XOM   +0.44          AAPL  -0.51
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

## How it works

1. **Ticker extraction** — an LLM call identifies any publicly traded companies mentioned in the article. These are merged with any explicit `--tickers` and fetched automatically.

2. **8 cluster heads** — one LLM call per dimension cluster runs in sequence (Ollama processes one request at a time). Each head returns `scores`, `reasoning`, and `confidence` as JSON.

3. **Aggregation** — scores are weighted by each head's confidence and merged into a single impact vector: `{dimension_key: float}` in the range `[-1.0, +1.0]`.

4. **Company scoring** — each company's score is the dot product of its dimension vector (0–1 rank) and the impact vector. Positive = tailwind, negative = headwind.

5. **Persistence** — article, all 8 head responses, and the aggregated vector are stored in DuckDB. Duplicate articles (same sha256) return the cached result unless `--refresh` is passed.

## DuckDB tables

| Table | Contents |
|---|---|
| `news_articles` | One row per article (deduped by sha256 of body) |
| `news_impact_heads` | 8 rows per article — one per cluster (scores, reasoning, confidence) |
| `news_impact_vectors` | Aggregated impact vector per article (`impact_json`, `top_dimensions`) |
| `news_article_tickers` | Ticker mentions per article — `source` is `extracted` (LLM) or `explicit` (--tickers) |

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `OLLAMA_IMPACT_MODEL` | `devstral` | Ollama model name |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama endpoint |
| `OLLAMA_CONCURRENCY` | `1` | Concurrent Ollama requests (keep at 1 for single-GPU) |
| `OLLAMA_TIMEOUT` | `120` | Per-request timeout in seconds |
| `OLLAMA_NUM_PREDICT` | `1024` | Max tokens per LLM response |
| `FMP_API_KEY` | — | Required only when fetching company vectors |
| `HANS_DUCKDB_PATH` | `data/swingtrader.duckdb` | DuckDB file path |

## Pulling the default model

```bash
ollama pull devstral
```

Faster alternatives (lower quality): `qwen2.5:7b`, `llama3.2:3b`
