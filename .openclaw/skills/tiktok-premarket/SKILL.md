# TikTok Pre-Market — Skill

Generate short-form pre-market analysis videos for TikTok using data from NewsImpactScreener.

## Commands

### `generate`

Run the full TikTok pre-market pipeline. Fetches news trends, generates a script via Ollama, renders chart slides, creates voiceover, and assembles the MP4.

```bash
cd ~/projects/swingtrader/code/analytics
python scripts/generate_tiktok_premarket.py
```

For testing without video assembly:
```bash
python scripts/generate_tiktok_premarket.py --dry-run
```

Custom output directory:
```bash
python scripts/generate_tiktok_premarket.py --output-dir /tmp/tiktok-test
```

Output files are written to `~/projects/swingtrader/code/analytics/output/tiktok/` by default:
- `tiktok_premarket_YYYY-MM-DD.mp4` — Final video
- `manifest.json` — Metadata, script, hashtags
- `voiceover.mp3` — TTS audio
- `slides/` — Individual chart PNGs

### `review`

After generating, send the video to WhatsApp for human review.

1. Read `manifest.json` to get the video path and hashtags
2. Send the video file to WhatsApp with the caption: "TikTok pre-market for {date} ready. Reply **post** to publish or **skip** to discard."
3. Include the hashtags in the message for easy copy-paste

### `post`

Upload the approved video to TikTok. Currently manual — open TikTok app/website and upload the video file directly. Copy hashtags from `manifest.json`.

Future: automate via TikTok Content Posting API v2 when credentials are configured.

### `status`

Check the current state of today's TikTok pipeline:

```bash
cat ~/projects/swingtrader/code/analytics/output/tiktok/manifest.json
```

Look at `status` field:
- `"success"` — video is ready
- `"dry_run"` — assets generated, no video assembled
- `"error"` — pipeline failed, check `message`

## State File

`~/projects/swingtrader/code/analytics/output/tiktok/manifest.json`

## Cron Schedule

This skill should run via OpenClaw cron at **12:00 UTC (8:00 AM ET) on weekdays**.

```json
{
  "id": "tiktok-premarket",
  "schedule": "0 12 * * 1-5",
  "command": "generate",
  "timezone": "UTC"
}
```

## Dependencies

- Python packages: `edge-tts`, `matplotlib`, `Pillow`
- System: `ffmpeg` (v7+)
- Running Ollama instance with a chat model
- Supabase access (env vars in analytics/.env)

## Setup

```bash
cd ~/projects/swingtrader/code/analytics
pip install edge-tts matplotlib Pillow
# Verify:
python -c "import edge_tts, matplotlib; print('OK')"
ffmpeg -version | head -1
```

## Workflow

1. Cron triggers at 8:00 AM ET weekdays
2. Pipeline generates video (~2-3 minutes)
3. Video sent to WhatsApp for review
4. Human replies "post" or "skip"
5. If post: upload video to TikTok (manual for now)
