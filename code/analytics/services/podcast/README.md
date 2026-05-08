# Hans Podcast Pipeline

Automated daily audio digest for The Impact Tape. Researches the day's market data with an agentic loop, writes a dialogue script, voices it with ElevenLabs, and publishes the packaged episode + cover art to Supabase Storage. The Next.js UI consumes `swingtrader.podcast_episodes` to render the public RSS feed at request time.

Scheduled daily on trading days. Optional human approval via Telegram before audio is rendered.

---

## Architecture

```
research_agent.py          ← agentic loop over base market tools + dossier fetchers
  │  (fallback: data_fetcher.fetch_live_data — parallel one-shot fetch)
  ▼
script_generator.py        ← Ollama validation pass → script pass (streaming /api/chat)
  │   prepends HOOK + WELCOME, appends SIGN_OFF
  ▼
telegram_gate.py           ← optional approval flow (Approve / Edit / Reject)
  ▼
elevenlabs_render.py       ← per-line TTS, ensures cached hook music bed
  ▼
episode_packager.py        ← pydub stitch (hook music overlay) + cover_art.py
  ▼
supabase_publisher.py      ← upload MP3 + cover to Storage, upsert podcast_episodes row
```

The UI reads `swingtrader.podcast_episodes` and serves the RSS feed from there. RSS XML is **not** assembled or stored on the analytics side.

---

## Voices

Three voices, all configured by env var. Voice IDs and names are not hardcoded — swap personas without touching code.

| Slot          | Env var                            | Stability | Style | Used in                |
| ------------- | ---------------------------------- | --------- | ----- | ---------------------- |
| **primary**   | `ELEVENLABS_PRIMARY_VOICE_*`       | 0.75      | 0.20  | acts 1, 2, 3, 6 anchor |
| **secondary** | `ELEVENLABS_SECONDARY_VOICE_*`     | 0.60      | 0.45  | acts 4, 5 anchor       |
| **hook**      | `ELEVENLABS_HOOK_VOICE_*` ("Hans") | 0.50      | 0.40  | HOOK + SIGN_OFF        |

Both anchor voices appear in every act for dialogue — the "anchor" frames the act, the other voice probes/reacts/clarifies. The hook voice is exclusive to the HOOK and SIGN_OFF acts so the show is bookended by the same Hans orchestrator persona. If `ELEVENLABS_HOOK_VOICE_ID` is unset, the hook falls back to the secondary voice ID.

---

## Episode Structure

The LLM produces six dialogue acts. The pipeline deterministically wraps them with a HOOK/WELCOME opener and a SIGN_OFF closer, so the on-air show has eight segments total:

| Act | Name                   | Voice               | Source        |
| --- | ---------------------- | ------------------- | ------------- |
| -1  | HOOK                   | hook                | deterministic |
| 0   | WELCOME                | primary + secondary | deterministic |
| 1   | COLD OPEN              | primary anchor      | LLM           |
| 2   | EXECUTIVE SUMMARY      | primary anchor      | LLM           |
| 3   | MARKET REGIME BRIEFING | primary anchor      | LLM           |
| 4   | TOP STORY DEEP DIVE    | secondary anchor    | LLM           |
| 5   | WATCHLIST PULSE        | secondary anchor    | LLM           |
| 6   | CLOSE + THESIS         | primary anchor      | LLM           |
| 7   | SIGN_OFF               | hook                | deterministic |

The HOOK plays under a soft music bed (`scripts/assets/audio/hook_music.mp3`, generated once via ElevenLabs sound effects and cached). The SIGN_OFF bookends the cold-open hook in Hans's voice.

Prompt rules enforced in [`templates/script_prompt.j2`](templates/script_prompt.j2):

- **Conversational dialogue** — every act is a real back-and-forth, not alternating monologues. 8–14 short interleaved lines per act.
- **Scene-setting** — orient the listener (where in the week, broad weather, who should care) before any stat.
- **One-fact-one-act** — each datum (stat, ticker, headline) is stated in exactly one act; other acts gesture at it indirectly.
- **Date / weekday stated once** — the weekday name is named only in MARKET REGIME BRIEFING; other acts use relative references ("today", "yesterday", "tomorrow").
- **ARIA per act** — Anchor → Reveal → Implication → Action.
- **ElevenLabs delivery** — `<break time="0.5s" />` for pauses (max 3s, used sparingly), numbers spelled out for TTS, ALL CAPS for emphasis.

Target runtime: **8–12 minutes** (~1100–1500 words at 130 wpm).

---

## File Structure

```
services/podcast/
├── config.py              # env vars, paths, feature flags
├── voices.py              # primary / secondary / hook VoiceConfig
├── data_fetcher.py        # parallel one-shot data fetch (fallback path)
├── research_agent.py      # agentic Ollama tool-loop over market registry + dossier tools
├── script_generator.py    # Ollama validate → script pipeline; HOOK/WELCOME/SIGN_OFF injection
├── elevenlabs_render.py   # per-line TTS + cached hook music bed
├── cover_art.py           # OpenAI gpt-image-1 background + Pillow typographic overlay
├── episode_packager.py    # pydub stitch with music overlay; cover art shim
├── supabase_publisher.py  # Storage upload + podcast_episodes upsert
├── telegram_gate.py       # Approve/Edit/Reject inline-keyboard flow
├── scheduler_hook.py      # orchestrator: run_daily_podcast + run_welcome_only
└── templates/
    └── script_prompt.j2   # Jinja2 prompt with persona, conversation, and routing rules

output/podcast/            # generated at runtime (analytics root)
├── episodes/
│   └── 2026-05-03/
│       ├── segments/      # per-line MP3s from ElevenLabs
│       ├── 2026-05-03_episode.mp3
│       └── 2026-05-03_cover.png
└── scripts/
    └── 2026-05-03.json    # saved script JSON

scripts/assets/audio/
└── hook_music.mp3         # cached hook bed (regenerated if deleted)

code/analytics/supabase/migrations/
├── 20260503_podcast_episodes.sql
├── 20260504_podcast_episodes_rss_columns.sql
├── 20260504_podcast_episodes_guid_constraint.sql
└── 20260504_podcast_storage_bucket.sql
```

---

## Research Pipeline

Two paths assemble the data dict that feeds the script prompt. Both produce the same shape, so the template is path-agnostic.

### Agentic path (`research_agent.py`, default — `PODCAST_AGENTIC=true`)

[`gather_dossier(today)`](research_agent.py) runs an Ollama tool-loop via `services.agent_core.run_tool_loop` against a registry combining two layers:

**Layer 1 — base market registry** (`build_market_registry()`, shared with other agents):

- `search_news` — semantic search over the news index
- `get_cluster_trends`, `get_dimension_trends` — themes pulsing in the news
- `get_ticker_sentiment`, `get_ticker_news`, `get_top_articles`
- `get_ticker_relationships`, `get_company_vectors`
- `fetch_url` — read article body when the title isn't enough

**Layer 2 — podcast dossier tools** (`_build_podcast_dossier_tools()`, thin wrappers over `data_fetcher`):

| Tool                              | Returns                                                                  | Description hint to the agent                                          |
| --------------------------------- | ------------------------------------------------------------------------ | ---------------------------------------------------------------------- |
| `get_market_regime_and_breadth`   | `{regime, breadth}`                                                      | "almost always worth calling" — foundation for MARKET REGIME BRIEFING  |
| `get_vix`                         | `{current, change_pct, direction}`                                       | "skip unless today's reading is genuinely notable"                     |
| `get_top_news`                    | `{ticker, impact_score, headline, factor_summary}`                       | "TOP STORY DEEP DIVE is built on this — call once"                     |
| `get_watchlist_setups`            | `[{ticker, rs_rank, stage, pct_from_pivot, setup_type}, …]`              | "WATCHLIST PULSE is built on this — call once"                         |
| `get_earnings`                    | `{ticker, surprise_pct}`                                                 | "skip if earnings season is quiet"                                     |
| `get_insider_activity`            | `{ticker, description}`                                                  | "strong fit when top news impact_score >= 8"                           |
| `get_news_24h_stats`              | `{articles_24h, sources_24h}`                                            | "always call once" — grounds the cold-open hook                        |

**System prompt** ([`_system_prompt`](research_agent.py)) tells the agent it's the *research producer*, not the writer. It hands over:

- An iteration budget — at most `PODCAST_RESEARCH_MAX_ROUNDS` tool rounds (default 12), with explicit "front-load must-haves, stop two rounds before cap" guidance.
- A **section-by-section research brief** mapping each podcast act to which dossier tools are required vs. conditional. e.g. act 4 says "if top news impact_score >= 8, also call `get_insider_activity`"; act 6 says "only call `get_earnings` during an active earnings week".
- An "optional cross-section context tools" note that allows the layer-1 RAG tools but only "when they would add real cross-section colour the writer can weave in".
- An output schema: when finished, emit a single JSON object `{"research_notes": "1–3 sentences of cross-section context the writer should know"}`. The writer combines this notes string with the raw `tool_results` automatically, so the agent doesn't need to repeat tool data in its final JSON.

**User prompt** is one line: `"Research today's episode for {today}. Begin tool calls now, then emit the dossier JSON when you're done."`

**After the loop returns**, [`_gather_dossier_via_agent`](research_agent.py) doesn't trust the model's JSON to contain the data — it builds the dossier from the captured `tool_results` dict directly:

```python
data = {
    "date": today,
    **session_meta(today),                           # weekday, session_context
    "regime":      tool_results["get_market_regime_and_breadth"]["regime"],
    "breadth":     tool_results["get_market_regime_and_breadth"]["breadth"],
    "vix":         tool_results.get("get_vix") or {"current": 0, ...},
    "watchlist":   tool_results.get("get_watchlist_setups") or [],
    "articles_24h": tool_results["get_news_24h_stats"]["articles_24h"],
    "sources_24h":  tool_results["get_news_24h_stats"]["sources_24h"],
}
# Optional fields only included if the agent fetched them:
if tool_results.get("get_top_news"):          data["top_news"]  = …
if tool_results.get("get_earnings"):          data["earnings"]  = …
if tool_results.get("get_insider_activity"):  data["insider"]   = …
if research_notes:                            data["research_notes"] = research_notes
```

The model's `research_notes` is parsed by [`_parse_dossier_json`](research_agent.py), which is permissive: tries strict `json.loads`, then falls back to slicing from the first `{` to its matching `}` (string-aware, so braces inside string literals don't fool the bracket counter). If the agent skipped `get_market_regime_and_breadth` entirely, the code falls back to a synchronous `_fetch_regime_and_breadth()` call so the dossier always has a regime/breadth foundation.

The dossier dict then flows into [`script_prompt.j2`](templates/script_prompt.j2) — the same template the parallel fallback uses. The `research_notes` field surfaces in the prompt as a `RESEARCH NOTES (from upstream research agent — cross-section context the writer should weave in)` block, which the script-writing model reads alongside the structured market data.

**Failure handling**: Ollama Cloud often 502s before the first stream byte on long tool calls. `_gather_dossier_via_agent` is wrapped by `gather_dossier`, which on failure logs the error and falls back to `data_fetcher.fetch_live_data()` (when `PODCAST_RESEARCH_FALLBACK_ON_FAILURE=true`). The parallel path produces the same dict shape, so the script generator never sees the difference.

### Parallel-fetch fallback (`data_fetcher.py`)

`fetch_live_data()` runs every section concurrently in threads:

| Section          | Source                                                                                |
| ---------------- | ------------------------------------------------------------------------------------- |
| `top_news`       | `services.rag.get_top_articles` + `fetch_tickers_for_articles` (last 14h)             |
| `watchlist`      | Live FMP NYSE+NASDAQ pre-screen (SCREENER==1 & RS>80, top 5 by RS)                    |
| `vix`            | FMP `/quote/^VIX`                                                                     |
| `earnings`       | FMP earnings calendar (yesterday → tomorrow), biggest reported surprise               |
| `insider`        | FMP latest insider feed, top transaction by dollar value                              |
| `regime+breadth` | `services.screener.technical.get_market_direction` + cached NYSE+NASDAQ quote ratios  |
| `articles_24h` / `sources_24h` | Supabase `news_articles` head count + paginated unique publishers       |

Each section fails independently and falls back to defaults or omission — never raises.

---

## Script Generation

### Step 1 — Validation (streaming `/api/generate`)

Sends the data dict to `OLLAMA_PODCAST_EXTRACT_MODEL` to strip nulls, fill defaults, clamp ranges (`impact_score` to 0–10). Streams to keep the connection alive past Ollama Cloud's ~60s idle timeout. Best-effort: any error or unparseable response falls back to the unmodified input.

### Step 2 — Script generation (streaming `/api/chat`)

Sends the rendered Jinja2 prompt to `OLLAMA_PODCAST_SCRIPT_MODEL`. Streaming again — same idle-timeout reason. Retries up to `PODCAST_OLLAMA_RETRIES` (default 5) on transient backend errors (502/503/504/429/EOF/network drops) with exponential backoff. 429 / "too many concurrent" pauses are extended. The script and validation calls are spaced by `PODCAST_OLLAMA_CHAT_GAP_S` seconds (default 3) to reduce concurrency-rate limits.

### Step 3 — JSON parsing + retry

The model may emit `<think>...</think>` reasoning tokens before the JSON. The parser strips those, finds the first `{`, removes trailing markdown fences, and attempts `json.loads`. On parse failure: retries once with the error appended as a follow-up message. Second failure raises `PodcastScriptError`.

### Step 4 — Deterministic act injection

After the LLM returns valid JSON, the pipeline injects:

- HOOK (act -1, hook voice, with `bg_music=True`) — built from live `articles_24h` / `sources_24h` so Hans's "I have read N articles from M sources" line is grounded.
- WELCOME (act 0, primary + secondary greeting by name) — skipped if either voice name is unset.
- SIGN_OFF (act 7, hook voice) — bookends the cold-open hook with "This was Hans…".

Idempotent: re-running on a script that already contains a HOOK or SIGN_OFF won't double-inject.

The final script JSON is saved to `output/podcast/scripts/{date}.json`.

---

## Telegram Approval Flow

When a script is ready, the pipeline sends a formatted summary with an inline keyboard:

```
📻 PODCAST DRAFT READY — 2026-05-03

🎯 NVIDIA's Chip Surge and the Bull Confirmation
⏱ ~9 min (1180 words)

COLD OPEN: Markets are roaring back...
REGIME: Bull Confirmed, 14 days in...

[~$0.24 to render audio — LLM cost: $0.00 (local)]

[ ✅ Approve ]  [ ✏️ Edit ]  [ ❌ Reject ]
```

| Decision             | Behaviour                                                                                  |
| -------------------- | ------------------------------------------------------------------------------------------ |
| **Approve**          | Proceeds to ElevenLabs rendering                                                           |
| **Edit**             | Sends script JSON to chat; waits 5 min for edited reply; falls back to original on timeout |
| **Reject**           | Logs `status=rejected` to Supabase and exits                                               |
| **Timeout (10 min)** | Treated as Reject                                                                          |

If `TELEGRAM_BOT_TOKEN` or `TELEGRAM_CHAT_ID` are not set, the gate is skipped and the pipeline auto-approves. `run_daily_podcast(skip_approval=True)` bypasses the gate explicitly.

---

## Cover Art

[`cover_art.py`](cover_art.py) generates the episode cover in two layers:

1. **AI background** — OpenAI `gpt-image-1` (`OPENAI_IMAGE_MODEL`) at 1024×1024, prompted from the episode title + description. The prompt explicitly forbids text in the image because gpt-image-1 mangles short titles. Quality controlled by `OPENAI_IMAGE_QUALITY` (low / medium / high).
2. **Typographic overlay** — Pillow draws the date and wrapped title over the AI image at the final cover size.

If the OpenAI call fails, falls back to a pure-typographic cover.

---

## Storage & Database

Audio + cover are uploaded to a single Supabase Storage bucket (`PODCAST_STORAGE_BUCKET`, default `podcast`):

- `YYYY-MM-DD_episode.mp3`
- `YYYY-MM-DD_cover.png`

Re-uploads overwrite the existing object so reruns produce stable URLs.

Table: `swingtrader.podcast_episodes`

| Column               | Type        | Notes                                  |
| -------------------- | ----------- | -------------------------------------- |
| `id`                 | serial      | PK                                     |
| `date`               | date        | Episode date                           |
| `title`              | text        |                                        |
| `description`        | text        | Show notes                             |
| `episode_url`        | text        | Public MP3 URL (legacy)                |
| `audio_url`          | text        | Public MP3 URL (RSS `<enclosure>`)     |
| `cover_url`          | text        | Public cover PNG URL                   |
| `file_size_bytes`    | bigint      | RSS `<enclosure length=…>`             |
| `guid`               | text UNIQUE | Stable RSS `<guid>` (upsert key)       |
| `published_at`       | timestamptz | RSS `<pubDate>`                        |
| `duration_seconds`   | integer     |                                        |
| `script_word_count`  | integer     |                                        |
| `elevenlabs_chars`   | integer     | Cost tracking                          |
| `estimated_cost_usd` | real        | `chars × $0.00003`                     |
| `status`             | text        | `published` / `rejected` / `error` / `local_only` |
| `created_at`         | timestamptz |                                        |

Apply migrations:

```bash
psql $DATABASE_URL -f code/analytics/supabase/migrations/20260503_podcast_episodes.sql
psql $DATABASE_URL -f code/analytics/supabase/migrations/20260504_podcast_episodes_rss_columns.sql
psql $DATABASE_URL -f code/analytics/supabase/migrations/20260504_podcast_episodes_guid_constraint.sql
psql $DATABASE_URL -f code/analytics/supabase/migrations/20260504_podcast_storage_bucket.sql
```

---

## Environment Variables

```env
# ElevenLabs
ELEVENLABS_API_KEY=
ELEVENLABS_PRIMARY_VOICE_ID=
ELEVENLABS_PRIMARY_VOICE_NAME=
ELEVENLABS_SECONDARY_VOICE_ID=
ELEVENLABS_SECONDARY_VOICE_NAME=
ELEVENLABS_HOOK_VOICE_ID=                          # optional, falls back to secondary
ELEVENLABS_HOOK_VOICE_NAME=Hans

# Hook music bed (cached at scripts/assets/audio/hook_music.mp3)
PODCAST_HOOK_MUSIC_PROMPT="Cinematic ambient music bed..."
PODCAST_HOOK_MUSIC_DURATION_S=16

# Ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_PODCAST_SCRIPT_MODEL=glm-5.1:cloud          # script generation (Step 2)
OLLAMA_PODCAST_EXTRACT_MODEL=glm-5.1:cloud         # data validation (Step 1)
OLLAMA_PODCAST_RESEARCH_MODEL=                     # agentic research (falls back to script model)

PODCAST_OLLAMA_RETRIES=5
PODCAST_OLLAMA_CHAT_GAP_S=3
PODCAST_RESEARCH_MAX_ROUNDS=12
PODCAST_RESEARCH_OLLAMA_RETRIES=3
PODCAST_RESEARCH_FALLBACK_ON_FAILURE=true

# OpenAI (cover art)
OPENAI_API_KEY=
OPENAI_IMAGE_MODEL=gpt-image-1
OPENAI_IMAGE_QUALITY=medium                        # low | medium | high

# Supabase storage
SUPABASE_URL=
SUPABASE_KEY=                                      # service-role key
PODCAST_STORAGE_BUCKET=podcast

# Feature flags
PODCAST_ENABLED=true
PODCAST_AGENTIC=true                               # false → use parallel data_fetcher

# Telegram (shared with the rest of the platform; gate is skipped if unset)
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
```

---

## Dependencies

```
jinja2>=3.1.0
pydub>=0.25.1
httpx
elevenlabs                   # SDK for TTS + sound effects (hook music)
openai                       # gpt-image-1 cover art
pillow                       # typographic overlay
supabase                     # storage + table writes
```

`ffmpeg` must be installed on the host for pydub MP3 encoding:

```bash
brew install ffmpeg
```

---

## Running

The orchestrator is `run_daily_podcast` in [`scheduler_hook.py`](scheduler_hook.py). It accepts a data fetcher callable and three flags for cheap testing:

```python
from services.podcast.scheduler_hook import run_daily_podcast
from services.podcast.research_agent import gather_dossier  # or data_fetcher.fetch_live_data

await run_daily_podcast(
    gather_dossier,                # Awaitable[dict] | dict
    script_only=False,             # stop after JSON script
    skip_approval=False,           # bypass Telegram gate
    skip_publish=False,            # render+package locally only
)
```

**Welcome-only smoke test** — renders only the HOOK + WELCOME opener so you can verify voice config and audio stitching with minimal API spend. No LLM call, no Telegram, no Supabase:

```python
from services.podcast.scheduler_hook import run_welcome_only
mp3_path = await run_welcome_only()
```

**Schedule** (4:30 PM ET, trading days only):

```python
scheduler.add_job(
    lambda: asyncio.run(run_daily_podcast(gather_dossier)),
    trigger="cron",
    hour=16, minute=30,
    timezone="America/New_York",
    day_of_week="mon-fri",
)
```

---

## Cost Estimate

| Component                                  | Cost                                |
| ------------------------------------------ | ----------------------------------- |
| LLM (validation + script via Ollama Cloud) | per Ollama Cloud pricing            |
| ElevenLabs TTS (~8000 chars/episode)       | ~$0.24 at $0.03/1k chars            |
| ElevenLabs hook music                      | one-time (cached after first build) |
| OpenAI gpt-image-1 cover (medium quality)  | ~$0.04/image                        |
| Supabase Storage                           | ~$0.01/episode                      |
| **Total per episode**                      | **~$0.30 + LLM**                    |
