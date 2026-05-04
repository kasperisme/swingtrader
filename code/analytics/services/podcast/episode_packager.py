from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from .config import ASSETS_DIR

log = logging.getLogger(__name__)

_SILENCE_300MS = 300
_SILENCE_500MS = 500
_HOOK_MUSIC_GAIN_DB = -18  # soft bed so voice stays dominant
_HOOK_MUSIC_PRE_ROLL_MS = 800
_HOOK_MUSIC_TAIL_MS = 1200


def _load_or_create_silent(path: Path, duration_ms: int = 2000) -> "AudioSegment":
    from pydub import AudioSegment
    from pydub.generators import Sine

    if path.exists():
        log.debug("Loading audio sting: %s", path.name)
        return AudioSegment.from_mp3(str(path))

    log.warning("Sting not found at %s, using %dms silence placeholder", path, duration_ms)
    return AudioSegment.silent(duration=duration_ms)


def _build_hook_chunk(voice_paths: list[Path], music_path: Path) -> "AudioSegment":
    """Concatenate hook voice lines and overlay a soft music bed.

    The bed swells in before the voice, ducks under it, and tails off into
    silence so the welcome that follows lands on a clean break. Falls back to
    voice + leading/trailing silence when music_path is missing.
    """
    from pydub import AudioSegment

    voice = AudioSegment.empty()
    for i, p in enumerate(voice_paths):
        voice += AudioSegment.from_mp3(str(p))
        if i < len(voice_paths) - 1:
            voice += AudioSegment.silent(duration=_SILENCE_300MS)

    total_ms = _HOOK_MUSIC_PRE_ROLL_MS + len(voice) + _HOOK_MUSIC_TAIL_MS

    if not music_path.exists():
        log.warning(
            "Hook music not found at %s — playing hook without bg music", music_path
        )
        return (
            AudioSegment.silent(duration=_HOOK_MUSIC_PRE_ROLL_MS)
            + voice
            + AudioSegment.silent(duration=_HOOK_MUSIC_TAIL_MS)
        )

    music = AudioSegment.from_mp3(str(music_path))
    if len(music) < total_ms:
        loops = (total_ms // len(music)) + 1
        music = music * loops
    music = music[:total_ms] + _HOOK_MUSIC_GAIN_DB
    music = music.fade_in(min(800, total_ms // 4)).fade_out(min(1200, total_ms // 3))

    bed = AudioSegment.silent(duration=total_ms)
    bed = bed.overlay(music, position=0)
    bed = bed.overlay(voice, position=_HOOK_MUSIC_PRE_ROLL_MS)
    log.info(
        "Hook chunk built: %d voice lines, %.1fs total, music bed at %d dB",
        len(voice_paths),
        total_ms / 1000,
        _HOOK_MUSIC_GAIN_DB,
    )
    return bed


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

    # Bucket segments into hook (gets a music bed) vs the rest, walking
    # script.acts in the same order render_episode produced segments in.
    hook_paths: list[Path] = []
    other_paths: list[Path] = []
    seg_idx = 0
    for act in script.get("acts", []):
        line_count = len(act.get("lines", []))
        bucket = (
            hook_paths
            if (act.get("name") == "HOOK" or act.get("bg_music"))
            else other_paths
        )
        for _ in range(line_count):
            if seg_idx < len(segments):
                bucket.append(segments[seg_idx])
                seg_idx += 1

    combined = intro + AudioSegment.silent(duration=_SILENCE_500MS)

    if hook_paths:
        combined += _build_hook_chunk(hook_paths, ASSETS_DIR / "hook_music.mp3")
        combined += AudioSegment.silent(duration=_SILENCE_500MS)

    for i, seg_path in enumerate(other_paths):
        seg = AudioSegment.from_mp3(str(seg_path))
        combined += seg
        if i < len(other_paths) - 1:
            combined += AudioSegment.silent(duration=_SILENCE_300MS)

    combined += outro

    audio_path = output_dir / f"{date_str}_episode.mp3"
    combined.export(str(audio_path), format="mp3", bitrate="128k")

    structure = " → ".join(
        ["intro"]
        + [
            (
                f"{act.get('name', f'act{i}')}[bgm]"
                if (act.get("name") == "HOOK" or act.get("bg_music"))
                else act.get("name", f"act{i}")
            )
            for i, act in enumerate(script.get("acts", []))
        ]
        + ["outro"]
    )
    log.info(
        "Bundled single-file episode → %s (%.1fs, %d segments stitched: %s)",
        audio_path,
        len(combined) / 1000,
        len(segments),
        structure,
    )

    cover_path = output_dir / f"{date_str}_cover.png"
    _generate_cover_art(
        date_str,
        script.get("episode_title", "NewsImpact Daily"),
        script,
        cover_path,
    )

    word_count = sum(
        len(line.get("text", "").split())
        for act in script.get("acts", [])
        for line in act.get("lines", [])
    )
    char_count = sum(
        len(line.get("text", ""))
        for act in script.get("acts", [])
        for line in act.get("lines", [])
    )

    return {
        "audio_path": audio_path,
        "cover_path": cover_path,
        "title": script.get("episode_title", f"NewsImpact Daily — {date_str}"),
        "description": script.get("episode_description", ""),
        "duration_seconds": len(combined) // 1000,
        "file_size_bytes": audio_path.stat().st_size,
        "script_word_count": word_count,
        "elevenlabs_chars": char_count,
    }
