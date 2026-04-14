# Analytics

Python scripts for news scoring, blog post generation, and X (Twitter) thread posting.

## Setup

```bash
cd code/analytics
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Copy `.env.example` to `.env` (or edit `.env` directly) and fill in the required vars listed below.

---

## Environment Variables

### Required

| Variable | Description |
|---|---|
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_KEY` | Supabase service role key |
| `SUPABASE_SCHEMA` | Schema name (e.g. `swingtrader`) |
| `SANITY_TOKEN` | Sanity write token (Editor role or above) |

### Optional — Sanity

| Variable | Default | Description |
|---|---|---|
| `SANITY_PROJECT_ID` | `y2lg8a3c` | Sanity project ID |
| `SANITY_DATASET` | `production` | Sanity dataset |

### Optional — Ollama

| Variable | Default | Description |
|---|---|---|
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama server URL |
| `OLLAMA_BLOG_MODEL` | `gemma4:e4b` | Model used for blog and X thread generation |
| `OLLAMA_BLOG_NUM_PREDICT` | `1500` | Max tokens for blog post |

### Optional — X (Twitter)

Required only when posting X threads. Uses OAuth 1.0a — Bearer Token alone is read-only and cannot post.

| Variable | Description |
|---|---|
| `X_CONSUMER_KEY` | OAuth 1.0a API Key (from X Developer Portal) |
| `X_CONSUMER_SECRET` | OAuth 1.0a API Secret |
| `X_ACCESS_TOKEN` | Access Token (generate in Developer Portal with Read+Write) |
| `X_ACCESS_SECRET` | Access Token Secret |
| `SITE_BASE_URL` | Base URL for blog backlinks (default: `https://newsimpactscreener.com`) |

### Optional — News

| Variable | Default | Description |
|---|---|---|
| `NEWS_LOOKBACK_HOURS` | mode-dependent | Override the default lookback window |
| `NEWS_MAX_ARTICLES` | `20` | Max articles pulled per run |
| `USE_SEMANTIC_RETRIEVAL` | `true` | Enable embedding-based snippet retrieval |

---

## Scripts

### `generate_blog_post.py` — Blog post + X thread

Pulls recently scored news from Supabase, generates a market analysis blog post via Ollama, publishes it to Sanity, then generates and posts a 4-tweet X thread with a backlink to the post.

**Modes:**

| Mode | Default lookback | Intended run time |
|---|---|---|
| `pre-market` | 14 h | 08:30 ET weekdays |
| `intra-market` | 6 h | 14:30 ET weekdays |

**Usage:**

```bash
# Full run — blog post + X thread
python scripts/generate_blog_post.py --mode pre-market
python scripts/generate_blog_post.py --mode intra-market

# Dry run — prints blog post and X thread to stdout, nothing published or posted
python scripts/generate_blog_post.py --mode pre-market --dry-run

# Blog post only — skip X thread
python scripts/generate_blog_post.py --mode pre-market --skip-x

# X thread only — skip blog generation and Sanity publishing
# Useful when the blog post is already live and you just want to post the thread
python scripts/generate_blog_post.py --mode pre-market --skip-sanity

# Override lookback window
python scripts/generate_blog_post.py --mode pre-market --lookback-hours 20

# Limit articles pulled
python scripts/generate_blog_post.py --mode pre-market --max-articles 10
```

**X thread structure:**

1. Hook — what moved and why it matters, with `$TICKER` callouts
2. Top 2 factor dimension moves (bullish/bearish) and sector/stock exposure
3. A risk or setup traders might be missing from the data
4. `"Full Pre-Market analysis: https://newsimpactscreener.com/blog/<slug> #SwingTrading #MarketNews #NewsImpact"`

### `run_blog_post.sh` — launchd wrapper

Shell wrapper used by the Mac Mini launchd jobs. Skips weekends automatically.

```bash
bash scripts/run_blog_post.sh pre-market
bash scripts/run_blog_post.sh intra-market
```

### `run_screener.py` / `run_daily_narrative.py`

See inline docstrings for usage.

---

## Scheduled Jobs (Mac Mini)

The blog post script is triggered by launchd at:
- **08:30 ET** — pre-market edition
- **14:30 ET** — intra-market edition

Weekends are skipped inside `run_blog_post.sh`.
