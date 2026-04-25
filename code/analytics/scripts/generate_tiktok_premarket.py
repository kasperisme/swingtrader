#!/usr/bin/env python3
"""
generate_tiktok_premarket.py — Auto-generate TikTok pre-market analysis videos.

Fetches news trend data from Supabase, uses Ollama to write a short script,
generates chart slides via matplotlib, creates a voiceover with Edge-TTS,
and assembles the final MP4 with ffmpeg.

Usage:
  python scripts/generate_tiktok_premarket.py
  python scripts/generate_tiktok_premarkete.py --dry-run
  python scripts/generate_tiktok_premarket.py --output-dir /tmp/tiktok

Required env vars (analytics/.env):
  SUPABASE_URL, SUPABASE_KEY, SUPABASE_SCHEMA
  OLLAMA_BASE_URL         (default: http://localhost:11434)
  OLLAMA_TIKTOK_MODEL     (default: OLLAMA_BLOG_MODEL → gemma4:e4b)

Required system tools:
  ffmpeg, edge-tts (pip install edge-tts), matplotlib (pip install matplotlib Pillow)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import pathlib
from datetime import datetime, timezone

from dotenv import load_dotenv

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=_REPO_ROOT / ".env")
sys.path.insert(0, str(_REPO_ROOT))

from zoneinfo import ZoneInfo

EASTERN = ZoneInfo("America/New_York")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


async def run_pipeline(dry_run: bool = False, output_dir: pathlib.Path | None = None, animated: bool = True, no_audio: bool = False) -> dict:
    from tiktok.config import OUTPUT_DIR as _DEFAULT_OUTPUT, EASTERN as _EASTERN
    from tiktok.data_fetcher import (
        fetch_cluster_trends,
        fetch_top_articles,
        fetch_tickers_for_articles,
        compute_cluster_summary,
    )
    from tiktok.script_generator import generate_script, SCRIPT_BLOCKS
    from tiktok.voiceover import generate_voiceover, build_captions, generate_silent_audio
    from tiktok.chart_renderer import render_all_slides
    from tiktok.video_assembler import assemble_video, compute_block_durations
    from tiktok.slide_animator import render_all_animated_slides
    from tiktok.video_assembler import assemble_from_clips

    output = output_dir or _DEFAULT_OUTPUT
    output.mkdir(parents=True, exist_ok=True)

    now_et = datetime.now(_EASTERN)
    date_str = now_et.strftime("%A, %B %-d, %Y")
    date_short = now_et.strftime("%Y-%m-%d")

    log.info("=" * 60)
    log.info("TikTok Pre-Market Pipeline — %s", date_str)
    log.info("=" * 60)

    log.info("Step 1/6: Fetching data from Supabase...")
    cluster_rows = fetch_cluster_trends()
    articles = fetch_top_articles()

    if not articles:
        log.error("No scored articles found. Aborting.")
        return {"status": "error", "message": "No articles found"}

    article_ids = [a["id"] for a in articles]
    tickers_map = fetch_tickers_for_articles(article_ids)
    summary = compute_cluster_summary(cluster_rows, articles)

    log.info("Data: %d articles, %d clusters", len(articles), len(summary["cluster_ranking"]))

    log.info("Step 2/6: Generating TikTok script via Ollama...")
    script = await generate_script(summary, articles, tickers_map, date_str)
    log.info("Script blocks: %s", list(script.keys()))

    full_text = " ".join(script.get(b, "") for b in SCRIPT_BLOCKS)

    if no_audio:
        log.info("Step 3/6: --no-audio — generating silent audio track...")
        word_count = max(len(full_text.split()), 3)
        est_duration = word_count / 2.3
        audio_path = await asyncio.to_thread(
            generate_silent_audio, est_duration, output / "voiceover"
        )
        captions = []
        log.info("Silent audio: %s (%.1fs, no captions)", audio_path.name, est_duration)
    else:
        log.info("Step 3/6: Generating voiceover via Edge-TTS...")
        audio_path, word_timings = await generate_voiceover(full_text, output / "voiceover")
        captions = build_captions(word_timings)
        log.info("Voiceover: %s, %d captions", audio_path.name, len(captions))

    block_durations = compute_block_durations(script)

    if animated:
        log.info("Step 4/6: Rendering animated slides via matplotlib...")
        clips = render_all_animated_slides(
            summary, articles, tickers_map, date_str, script,
            block_durations, output / "clips",
        )
        log.info("Rendered %d animated clips", len(clips))

        if dry_run:
            manifest = {
                "status": "dry_run",
                "date": date_str,
                "script": script,
                "audio": str(audio_path),
                "clips": [str(c) for c in clips],
                "captions": len(captions),
                "summary": {
                    "total_articles": summary["total_articles"],
                    "top_clusters": [c["label"] for c in summary["cluster_ranking"][:3]],
                    "top_dimensions": [d["label"] for d in summary["top_dimensions"][:3]],
                },
            }
            manifest_path = output / "manifest.json"
            manifest_path.write_text(json.dumps(manifest, indent=2, default=str))
            log.info("Dry run complete. Manifest: %s", manifest_path)
            return manifest

        log.info("Step 5/6: Assembling video from clips...")
        video_path = assemble_from_clips(
            clips, audio_path, captions,
            output / f"tiktok_premarket_{date_short}.mp4",
            hook_duration=block_durations[0] if block_durations else 0,
        )
    else:
        log.info("Step 4/6: Rendering chart slides via Plotly...")
        slides = render_all_slides(summary, articles, tickers_map, date_str, script, output / "slides")
        log.info("Rendered %d slides", len(slides))

        if dry_run:
            manifest = {
                "status": "dry_run",
                "date": date_str,
                "script": script,
                "audio": str(audio_path),
                "slides": [str(s) for s in slides],
                "captions": len(captions),
                "summary": {
                    "total_articles": summary["total_articles"],
                    "top_clusters": [c["label"] for c in summary["cluster_ranking"][:3]],
                    "top_dimensions": [d["label"] for d in summary["top_dimensions"][:3]],
                },
            }
            manifest_path = output / "manifest.json"
            manifest_path.write_text(json.dumps(manifest, indent=2, default=str))
            log.info("Dry run complete. Manifest: %s", manifest_path)
            return manifest

        log.info("Step 5/6: Assembling video via ffmpeg...")
        video_path = assemble_video(
            slides, audio_path, captions,
            output / f"tiktok_premarket_{date_short}.mp4",
            slide_durations=block_durations,
        )

    manifest = {
        "status": "success",
        "date": date_str,
        "video": str(video_path),
        "script": script,
        "animated": animated,
        "summary": {
            "total_articles": summary["total_articles"],
            "top_clusters": [c["label"] for c in summary["cluster_ranking"][:3]],
            "top_dimensions": [d["label"] for d in summary["top_dimensions"][:3]],
        },
    }

    manifest_path = output / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, default=str))

    log.info("=" * 60)
    log.info("DONE — Video: %s", video_path)
    log.info("Hashtags: %s", " ".join(script.get("hashtags", [])))
    log.info("=" * 60)

    return manifest


def main():
    parser = argparse.ArgumentParser(description="Generate TikTok pre-market analysis video")
    parser.add_argument("--dry-run", action="store_true", help="Generate assets but skip video assembly")
    parser.add_argument("--output-dir", type=pathlib.Path, default=None, help="Output directory")
    parser.add_argument("--no-animated", action="store_true", help="Use static slides + Ken Burns instead of animated clips")
    parser.add_argument("--no-audio", action="store_true", help="Skip voiceover (silent audio) for design testing")
    args = parser.parse_args()

    result = asyncio.run(run_pipeline(dry_run=args.dry_run, output_dir=args.output_dir, animated=not args.no_animated, no_audio=args.no_audio))

    if result["status"] == "error":
        sys.exit(1)

    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
