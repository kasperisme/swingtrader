from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from .config import ASSETS_DIR

log = logging.getLogger(__name__)

_SILENCE_300MS = 300
_SILENCE_500MS = 500


def _load_or_create_silent(path: Path, duration_ms: int = 2000) -> "AudioSegment":
    from pydub import AudioSegment
    from pydub.generators import Sine

    if path.exists():
        log.debug("Loading audio sting: %s", path.name)
        return AudioSegment.from_mp3(str(path))

    log.warning("Sting not found at %s, using %dms silence placeholder", path, duration_ms)
    return AudioSegment.silent(duration=duration_ms)


def _generate_cover_art(date_str: str, title: str, script: dict, output_path: Path) -> Path:
    """Delegate to services.podcast.cover_art.

    Kept as a thin shim so existing callers don't need to change. The cover_art
    module owns the AI image generation + typographic overlay pipeline and
    falls back to pure-Pillow when OPENAI_API_KEY isn't set.
    """
    from .cover_art import generate_cover_art
    return generate_cover_art(date_str, title, script, output_path)


def package_episode(
    segments: list[Path],
    script: dict,
    date_str: str,
    output_dir: Path,
) -> dict:
    from pydub import AudioSegment

    output_dir.mkdir(parents=True, exist_ok=True)

    intro = _load_or_create_silent(ASSETS_DIR / "intro_sting.mp3", 2000)
    outro = _load_or_create_silent(ASSETS_DIR / "outro_sting.mp3", 2000)

    combined = intro + AudioSegment.silent(duration=_SILENCE_500MS)

    for i, seg_path in enumerate(segments):
        seg = AudioSegment.from_mp3(str(seg_path))
        combined += seg
        if i < len(segments) - 1:
            combined += AudioSegment.silent(duration=_SILENCE_300MS)

    combined += outro

    audio_path = output_dir / f"{date_str}_episode.mp3"
    combined.export(str(audio_path), format="mp3", bitrate="128k")
    log.info("Episode exported: %s (%.1fs)", audio_path.name, len(combined) / 1000)

    cover_path = output_dir / f"{date_str}_cover.png"
    _generate_cover_art(
        date_str,
        script.get("episode_title", "NewsImpact Daily"),
        script,
        cover_path,
    )

    return {
        "audio_path": audio_path,
        "cover_path": cover_path,
        "title": script.get("episode_title", f"NewsImpact Daily — {date_str}"),
        "description": script.get("episode_description", ""),
        "duration_seconds": len(combined) // 1000,
        "file_size_bytes": audio_path.stat().st_size,
    }
