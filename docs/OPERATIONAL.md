# SwingTrader Operational Runbooks

## Quick Status

```bash
# View all pipeline health
cd ~/projects/swingtrader/code/analytics && .venv/bin/python -m scripts.watchdog

# Tail recent logs
tail -50 ~/projects/swingtrader/logs/watchdog.log
tail -50 ~/projects/swingtrader/logs/swingtrader-news.log
```

---

## Common Issues & Fixes

### 1. FMP API 400 Bad Request (news/general-latest)

**Symptoms:**
- `[FMPFetcher] news/general-latest failed: Client error '400 Bad Request'`
- Watchdog alerts `[LOG:news_ingest]` with FMP errors

**Cause:** FMP rate limiting or invalid date range for backfill

**Fix:**
```bash
# Check if FMP key is valid
curl "https://financialmodelingprep.com/stable/news/general-latest?apikey=YOUR_KEY_HERE&limit=1"

# If key OK, likely rate limit — wait and retry
# The backfill jobs already have retry logic; they should recover on next run
```

---

### 2. Embeddings 400 Bad Request (Ollama)

**Symptoms:**
- `[embeddings] article_id=XXX failed: Client error '400 Bad Request' for url 'http://localhost:11434/api/embed'`

**Cause:** 
- Ollama model not loaded
- Model name changed (e.g., `mxbai-embed-large` vs `mxbai-embed-large:latest`)

**Fix:**
```bash
# Check Ollama status
ollama list

# Pull model if missing
ollama pull mxbai-embed-large:latest

# Restart embeddings processing
cd ~/projects/swingtrader/code/analytics
.venv/bin/python -m news_impact.embeddings_cli --process-pending --limit 10
```

---

### 3. Job marked STALE but running fine

**Symptoms:**
- Watchdog shows `[STALE]` but job runs on schedule
- Common for weekend-only jobs (blog_post, daily_narrative)

**Cause:** Jobs only run on weekdays, but watchdog expects them daily

**Fix:**
- This is expected behavior on weekends
- No action needed
- Job will resume on next weekday

---

### 4. WhatsApp alerts not sending

**Symptoms:**
- `[health] WhatsApp alert failed: [Errno 2] No such file or directory: 'openclaw'`

**Cause:** cron PATH doesn't include homebrew

**Fix:**
```bash
# Add PATH to crontab
crontab -e
# Add at top:
PATH=/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin
```

Also verify `OPENCLAW_WHATSAPP_TO` is set in `.env`.

---

### 5. Supabase connection errors

**Symptoms:**
- `HTTP/2 401` or `HTTP/2 403` in logs
- `job_health` updates failing

**Cause:** Invalid SUPABASE_KEY or SUPABASE_URL

**Fix:**
```bash
# Check .env
cat ~/projects/swingtrader/code/analytics/.env | grep SUPABASE
```

---

### 6. Ollama not responding

**Symptoms:**
- Embeddings timing out
- Chat completions hanging

**Cause:** Ollama service hung or crashed

**Fix:**
```bash
# Check Ollama process
ps aux | grep ollama

# Restart Ollama
brew services restart ollama
# or
ollama serve
```

---

## Manual Remediation Commands

```bash
# Restart news ingestion
~/projects/swingtrader/.local/bin/swingtrader-news --fmp-news --fmp-news-feed stock

# Retry failed embeddings
cd ~/projects/swingtrader/code/analytics
.venv/bin/python -m news_impact.embeddings_cli --process-pending --retry-failed --limit 50

# Force blog post run (test mode)
cd ~/projects/swingtrader/code/analytics
.venv/bin/python scripts/generate_blog_post.py --mode pre-market --dry-run
```

---

## Health Checks

| Check | Command |
|-------|---------|
| All pipelines | `tail -20 ~/projects/swingtrader/logs/watchdog.log` |
| News ingest | `tail -30 ~/projects/swingtrader/logs/swingtrader-news.log` |
| Embeddings | `tail -30 ~/projects/swingtrader/logs/embeddings.log` |
| Blog posts | `tail -20 ~/projects/swingtrader/logs/generate_blog_post.log` |
| Daily narrative | `tail -20 ~/projects/swingtrader/logs/narrative.log` |
| Telegram polling | `tail -10 ~/projects/swingtrader/logs/telegram_updates.log` |