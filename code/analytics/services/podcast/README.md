# Hans Podcast Pipeline

Automated daily audio digest for NewsImpact Daily. Generates a podcast episode from market data, voices it with ElevenLabs, and distributes it via RSS to Spotify and Apple Podcasts.

Runs at 4:30 PM ET on trading days. Requires human approval via Telegram before audio is rendered.

---

## Architecture

```
data_fetcher_fn()
      │
      ▼
script_generator.py        ← GLM-5.1 validates data, GLM-4.6 writes script
      │
      ▼
telegram_gate.py           ← sends draft summary, waits for Approve/Edit/Reject
      │
      ▼
elevenlabs_render.py       ← TTS per line, sequential (rate limit safe)
      │
      ▼
episode_packager.py        ← pydub stitch + Pillow cover art
      │
      ▼
rss_publisher.py           ← R2 upload + RSS XML prepend
      │
      ▼
Supabase podcast_episodes  ← logs date, title, url, cost, status
```

---

## Voices

| Voice      | Persona              | Stability | Style | Acts    |
| ---------- | -------------------- | --------- | ----- | ------- |
| **Marcus** | Authoritative anchor | 0.75      | 0.20  | 1, 2, 5 |
| **Kai**    | Energetic analyst    | 0.60      | 0.45  | 3, 4    |

Both voices may appear in any act for dialogue. Voice IDs are set via env vars.

---

## Episode Structure

Five acts following the **ARIA** framework (Anchor → Reveal → Implication → Action):

| Act | Name                   | Primary Voice |
| --- | ---------------------- | ------------- |
| 1   | COLD OPEN              | Marcus        |
| 2   | MARKET REGIME BRIEFING | Marcus        |
| 3   | TOP STORY DEEP DIVE    | Kai           |
| 4   | WATCHLIST PULSE        | Kai           |
| 5   | CLOSE + THESIS         | Marcus        |

Target runtime: **8–12 minutes** (~1100–1500 words at 130 wpm).

---

## File Structure

```
services/podcast/
├── config.py              # env vars + path constants
├── voices.py              # Marcus + Kai VoiceConfig dataclasses
├── script_generator.py    # Ollama two-model pipeline
├── elevenlabs_render.py   # TTS rendering via ElevenLabs SDK
├── episode_packager.py    # pydub audio stitch + Pillow cover art
├── rss_publisher.py       # R2 upload + RSS feed management
├── telegram_gate.py       # approval flow with inline keyboard
├── scheduler_hook.py      # orchestrator: full pipeline end-to-end
└── templates/
    ├── script_prompt.j2   # Jinja2 prompt for GLM-4.6
    └── rss_episode.j2     # iTunes-compatible <item> block

output/podcast/            # generated at runtime
├── episodes/
│   └── 2026-05-03/
│       ├── segments/      # per-line MP3s from ElevenLabs
│       ├── 2026-05-03_episode.mp3
│       └── 2026-05-03_cover.png
├── scripts/
│   └── 2026-05-03.json    # saved script JSON
└── rss_feed.xml           # live RSS feed (prepend on each publish)

scripts/assets/audio/      # optional audio stings
├── intro_sting.mp3        # 2s silent placeholder if missing
└── outro_sting.mp3        # 2s silent placeholder if missing

supabase/migrations/
└── 20260503_podcast_episodes.sql
```

---

## Script Generation Pipeline

### Step 1 — Data validation (GLM-5.1)

`POST /api/generate` — strips nulls, fills defaults, validates numeric ranges (e.g. `impact_score` clamped to 0–10).

### Step 2 — Script generation (GLM-4.6)

`POST /api/chat` — uses the `templates/script_prompt.j2` Jinja2 template rendered with cleaned market data. Returns structured JSON with five acts, each containing a list of `{voice, text}` lines.

### Step 3 — Response cleaning

GLM-4.6 may emit `<think>...</think>` reasoning tokens before the JSON. The parser:

1. Strips everything before the first `{`
2. Strips trailing markdown fences
3. On parse failure: retries once with the error appended
4. On second failure: raises `PodcastScriptError` and aborts

Model names are controlled by env vars — swap without touching code:

```
HANS_SCRIPT_MODEL=glm-4.6
HANS_EXTRACT_MODEL=glm-5.1
```

---

## Telegram Approval Flow

When a script is ready, the pipeline sends a formatted summary to Telegram with an inline keyboard:

```
📻 PODCAST DRAFT READY — 2026-05-03

🎯 NVIDIA's Chip Surge and the Bull Confirmation
⏱ ~9 min (1180 words)

COLD OPEN: Markets are roaring back...
REGIME: Bull Confirmed, 14 days in...

[~$0.12–0.18 to render audio — LLM cost: $0.00 (local)]

[ ✅ Approve ]  [ ✏️ Edit ]  [ ❌ Reject ]
```

| Decision             | Behaviour                                                                                  |
| -------------------- | ------------------------------------------------------------------------------------------ |
| **Approve**          | Proceeds to ElevenLabs rendering                                                           |
| **Edit**             | Sends script JSON to chat; waits 5 min for edited reply; falls back to original on timeout |
| **Reject**           | Logs `status=rejected` to Supabase and exits                                               |
| **Timeout (10 min)** | Treated as Reject                                                                          |

If `TELEGRAM_BOT_TOKEN` or `TELEGRAM_CHAT_ID` are not set, the pipeline auto-approves.

---

## RSS Feed

The feed lives at `output/podcast/rss_feed.xml`. New episodes are **prepended** (newest first). On first run the file is created from an embedded iTunes-compatible template.

If Cloudflare R2 is configured (`R2_SYNC_TO_WEB=true`), the updated feed is re-uploaded after each publish.

Submit the RSS URL to:

- **Spotify for Podcasters** — podcasters.spotify.com
- **Apple Podcasts Connect** — podcastsconnect.apple.com

---

## Database

Table: `swingtrader.podcast_episodes`

| Column               | Type        | Notes                              |
| -------------------- | ----------- | ---------------------------------- |
| `id`                 | serial      | PK                                 |
| `date`               | date        | Episode date                       |
| `title`              | text        | Episode title                      |
| `episode_url`        | text        | Public MP3 URL                     |
| `duration_seconds`   | integer     |                                    |
| `script_word_count`  | integer     |                                    |
| `elevenlabs_chars`   | integer     | Used for cost tracking             |
| `estimated_cost_usd` | real        | `chars × $0.00003`                 |
| `status`             | text        | `published` / `rejected` / `error` |
| `created_at`         | timestamptz |                                    |

Apply the migration:

```bash
psql $DATABASE_URL -f supabase/migrations/20260503_podcast_episodes.sql
```

---

## Environment Variables

Add to `.env`:

```env
# ElevenLabs
ELEVENLABS_API_KEY=
ELEVENLABS_PRIMARY_VOICE_ID=
ELEVENLABS_SECONDARY_VOICE_ID=

# Ollama models (defaults shown)
OLLAMA_PODCAST_SCRIPT_MODEL=glm-5.1
OLLAMA_PODCAST_EXTRACT_MODEL=glm-4.6

# Cloudflare R2 (optional — falls back to local file path)
R2_ENDPOINT_URL=https://<ACCOUNT_ID>.r2.cloudflarestorage.com
R2_ACCESS_KEY_ID=
R2_SECRET_ACCESS_KEY=
R2_BUCKET_NAME=
R2_PUBLIC_BASE_URL=
R2_SYNC_TO_WEB=false

# Feature flag
PODCAST_ENABLED=true

# Telegram (uses existing TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID)
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
```

---

## Dependencies

New additions to `requirements.txt`:

```
jinja2>=3.1.0
pydub>=0.25.1
boto3>=1.35.0
```

`ffmpeg` must be installed on the host for pydub MP3 encoding:

```bash
brew install ffmpeg
```

Install Python deps:

```bash
pip install -r requirements.txt
```

---

## Running

**Test with mock data:**

```bash
python scripts/run_podcast.py --mock
```

**Live run (implement `_live_data_fetcher` in `run_podcast.py` first):**

```bash
python scripts/run_podcast.py
```

**Schedule via APScheduler** (4:30 PM ET, trading days only):

```python
from services.podcast.scheduler_hook import run_daily_podcast

scheduler.add_job(
    lambda: asyncio.run(run_daily_podcast(your_data_fetcher)),
    trigger="cron",
    hour=16, minute=30,
    timezone="America/New_York",
    day_of_week="mon-fri",
)
```

---

## Cost Estimate

| Component                            | Cost                     |
| ------------------------------------ | ------------------------ |
| LLM (GLM-4.6 + GLM-5.1 via Ollama)   | $0.00 — fully local      |
| ElevenLabs TTS (~8000 chars/episode) | ~$0.24 at $0.03/1k chars |
| Cloudflare R2 storage                | ~$0.01/episode           |
| **Total per episode**                | **~$0.25**               |
