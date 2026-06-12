#!/usr/bin/env python3
"""Scrape a YouTube video and isolate its audio track.

Downloads the best available audio stream with yt-dlp and extracts it to a
standalone audio file (mp3 by default) via ffmpeg — no video is kept.

Usage:
    python -m scripts.scrape_youtube_audio "https://www.youtube.com/watch?v=fjzelp_mwuY"
    python scripts/scrape_youtube_audio.py <url> --format wav --outdir output/audio

Requires: yt-dlp (pip) + ffmpeg (system, e.g. `brew install ffmpeg`).
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

try:
    import yt_dlp
except ImportError:
    sys.exit("yt-dlp is not installed. Run: pip install yt-dlp")


def scrape_audio(url: str, outdir: Path, audio_format: str = "mp3", quality: str = "192") -> Path:
    """Download `url`'s audio and return the path to the extracted audio file."""
    if shutil.which("ffmpeg") is None:
        sys.exit("ffmpeg not found on PATH. Install it (macOS: `brew install ffmpeg`).")

    outdir.mkdir(parents=True, exist_ok=True)

    saved: list[str] = []

    def _hook(d: dict) -> None:
        if d.get("status") == "finished":
            saved.append(d.get("filename", ""))

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": str(outdir / "%(title)s [%(id)s].%(ext)s"),
        "noplaylist": True,
        "quiet": False,
        "progress_hooks": [_hook],
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": audio_format,
                "preferredquality": quality,
            }
        ],
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)

    # prepare_filename already includes outdir; just swap the extension to the
    # post-processed audio format.
    audio_path = Path(ydl.prepare_filename(info)).with_suffix(f".{audio_format}")
    return audio_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape a YouTube video and isolate its audio.")
    parser.add_argument("url", help="YouTube video URL")
    parser.add_argument(
        "--outdir",
        type=Path,
        default=Path("output/audio"),
        help="Directory to write the audio file (default: output/audio)",
    )
    parser.add_argument(
        "--format",
        dest="audio_format",
        default="mp3",
        choices=["mp3", "wav", "m4a", "flac", "opus"],
        help="Output audio format (default: mp3)",
    )
    parser.add_argument(
        "--quality",
        default="192",
        help="Audio bitrate in kbps for lossy formats (default: 192)",
    )
    args = parser.parse_args()

    path = scrape_audio(args.url, args.outdir, args.audio_format, args.quality)
    print(f"\nAudio saved to: {path}")


if __name__ == "__main__":
    main()
