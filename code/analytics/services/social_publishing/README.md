# social_publishing

The deterministic **last mile** for the nis-stock-breakdown content. Producing the
reel/carousel/caption is a hand-iterated creative process; this service does *no*
creative work — it reads the finished assets from `output/setups/<TICKER>/` and
pushes them to **Instagram, Facebook, TikTok and LinkedIn**.

Delivery goes through a **publishing aggregator** so we make one REST call instead
of maintaining four native OAuth flows + the Meta app review + the TikTok
content-posting audit. Two backends are supported and interchangeable via the
`SOCIAL_BACKEND` env var:

- **`zernio`** (default) — newer, has a free tier (first 2 accounts), official
  Meta/TikTok/LinkedIn partner. Addresses each network by a Zernio `accountId`.
- **`ayrshare`** — more battle-tested fallback. Addresses networks by name.

The asset/caption layer is identical for both; only the backend module changes
(`zernio.py` / `ayrshare.py`, behind `backends.py`). Swap with one env var.

No scheduler, no queue, no approval gate. You run it per ticker when ready.

## Usage

```bash
cd code/analytics

# One-time: list your connected Zernio accounts to fill the env mapping:
.venv/bin/python -m services.social_publishing.cli accounts

# Preview exactly what posts where — no network, no creds needed:
.venv/bin/python -m services.social_publishing.cli publish --ticker NWPX --dry-run

# Publish to all four networks:
.venv/bin/python -m services.social_publishing.cli publish --ticker NWPX

# Subset, or force the other backend:
.venv/bin/python -m services.social_publishing.cli publish --ticker NWPX \
    --platforms linkedin,instagram --backend ayrshare

# Schedule for an explicit local time (default tz America/New_York):
.venv/bin/python -m services.social_publishing.cli publish --ticker NWPX --at "2026-06-23 19:00"

# Schedule at each platform's best-engagement time:
.venv/bin/python -m services.social_publishing.cli publish --ticker NWPX --best-time
```

## Scheduling (`--at` / `--best-time`)

By default a post publishes immediately. Two ways to publish later instead:

- **`--at "YYYY-MM-DD HH:MM"`** — explicit local time. Timezone defaults to
  `America/New_York` (override with `--tz` or `SOCIAL_SCHEDULE_TZ`); the time is
  converted to UTC and sent as Zernio `scheduledFor`.
- **`--best-time`** — schedules each platform at its own best-engagement slot from
  Zernio's `/v1/analytics/best-time` (weekday×hour ranked by the account's own
  historical engagement), at the next future occurrence of the top slot.

`--best-time` is only as good as your post history: with few posts (or no
Analytics add-on → 403) it falls back to a **generic** Tue–Thu evening/midday
default, and the CLI prints `(generic default — no engagement history yet)` so a
fallback is never mistaken for real data. `--dry-run` prints the resolved `when:`
for every platform so you can confirm the timing before committing. `--at` and
`--best-time` are mutually exclusive.

## What it reads (`output/setups/<TICKER>/`)

| Asset | Used for |
|---|---|
| `reel_chart.mp4` (or `reel.mp4`) | the video for `kind=video` platforms |
| `slides/slide-*.png` | the images for `kind=carousel` platforms |
| `caption.txt` | the post copy (master / fallback) |
| `social/<platform>.txt` | **optional** per-platform caption override |
| `social/manifest.json` | **optional** per-platform `kind` + `media` override |

### Per-platform caption (recommended for LinkedIn)

LinkedIn wants a different voice than IG/TikTok — lead with the lesson, drop the
FOMO and "link in bio", ≤3 hashtags. Drop a `social/linkedin.txt` next to
`caption.txt` and it's used automatically; everything else falls back to
`caption.txt`.

### Manifest override (e.g. LinkedIn as a slide carousel)

```json
{
  "instagram": { "kind": "video",    "media": "reel_chart.mp4" },
  "linkedin":  { "kind": "carousel", "media": ["slides/slide-01.png", "slides/slide-02.png"] }
}
```

Defaults (no manifest): every platform ships the reel as video; Instagram video
posts as a Reel. TikTok is video-only and will reject `kind=carousel`.

## Setup

Add to `code/analytics/.env`:

```env
SOCIAL_BACKEND=zernio        # or "ayrshare"
SOCIAL_MEDIA_BUCKET=social   # Supabase Storage PUBLIC bucket for staged media

# Zernio (default backend)
ZERNIO_API_KEY=              # required to publish ("sk_..." from the dashboard)
ZERNIO_ACCOUNT_INSTAGRAM=    # per-network accountId — run `cli accounts` to get these
ZERNIO_ACCOUNT_FACEBOOK=
ZERNIO_ACCOUNT_TIKTOK=
ZERNIO_ACCOUNT_LINKEDIN=

# Ayrshare (alternative backend)
AYRSHARE_API_KEY=
AYRSHARE_PROFILE_KEY=        # optional — only on the Business plan
```

Reuses the existing `SUPABASE_URL` / `SUPABASE_KEY`. Create a **public** Supabase
Storage bucket named `social` (the aggregator fetches media by URL, so local
files are uploaded there first and the public URL is handed off).

In the aggregator's dashboard, connect the Instagram (Business), Facebook Page,
TikTok and LinkedIn accounts once. For Zernio, then run `cli accounts` and paste
the printed `ZERNIO_ACCOUNT_*` lines into `.env`. TikTok public posting requires
the aggregator's content-posting audit to be approved before live posts succeed.

## Modules

| File | Role |
|---|---|
| `config.py` | env + paths + platform defaults + backend selection |
| `assets.py` | resolve `output/setups/<TICKER>/` → one `PostPlan` per platform |
| `storage.py` | stage media to a public Supabase Storage URL |
| `schedule.py` | resolve `--at` / `--best-time` → an aware UTC datetime |
| `backends.py` | `PublishResult` + `get_backend()` selector |
| `zernio.py` | Zernio backend (default) — post (immediate polled / scheduled), `accounts`, `best_time_slots` |
| `ayrshare.py` | Ayrshare backend (alternative) |
| `cli.py` | `publish --ticker … [--platforms] [--backend] [--at/--best-time/--tz] [--dry-run]`, `accounts` |
