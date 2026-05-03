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


def _generate_cover_art(date_str: str, title: str, output_path: Path) -> Path:
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (1400, 1400), color=(0, 0, 0))
    draw = ImageDraw.Draw(img)

    try:
        font_large = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 72)
        font_medium = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 48)
        font_small = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 36)
    except OSError:
        font_large = ImageFont.load_default()
        font_medium = font_large
        font_small = font_large

    # Branding
    draw.text((700, 200), "NewsImpact Daily", font=font_large, fill=(255, 215, 0), anchor="mm")
    draw.text((700, 300), "Market Intelligence Digest", font=font_small, fill=(180, 180, 180), anchor="mm")

    # Date
    draw.text((700, 450), date_str, font=font_medium, fill=(255, 255, 255), anchor="mm")

    # Episode title (wrap at ~40 chars per line)
    words = title.split()
    lines, current = [], []
    for word in words:
        if sum(len(w) + 1 for w in current) + len(word) > 38:
            lines.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        lines.append(" ".join(current))

    y_start = 650
    for i, line in enumerate(lines[:4]):
        draw.text((700, y_start + i * 80), line, font=font_medium, fill=(255, 255, 255), anchor="mm")

    # Bottom branding strip
    draw.rectangle([(0, 1300), (1400, 1400)], fill=(255, 215, 0))
    draw.text((700, 1350), "newsimpactscreener.com", font=font_small, fill=(0, 0, 0), anchor="mm")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(output_path), "PNG")
    log.info("Cover art saved: %s", output_path.name)
    return output_path


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
    _generate_cover_art(date_str, script.get("episode_title", "NewsImpact Daily"), cover_path)

    return {
        "audio_path": audio_path,
        "cover_path": cover_path,
        "title": script.get("episode_title", f"NewsImpact Daily — {date_str}"),
        "description": script.get("episode_description", ""),
        "duration_seconds": len(combined) // 1000,
        "file_size_bytes": audio_path.stat().st_size,
    }
