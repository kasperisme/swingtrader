from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from .config import ASSETS_DIR

log = logging.getLogger(__name__)

_SILENCE_300MS = 300
_SILENCE_500MS = 500
_INTERJECTION_GAP_MS = 50  # tight gap when a ≤3-word reaction sits next to a different voice
_INTERJECTION_MAX_WORDS = 3
_HOOK_MUSIC_GAIN_DB = -18  # soft bed so voice stays dominant
_HOOK_MUSIC_PRE_ROLL_MS = 800
_HOOK_MUSIC_TAIL_MS = 1200


def _gap_between(prev_meta: tuple[str, int], next_meta: tuple[str, int]) -> int:
    """Return inter-segment silence in ms.

    When a short reaction (≤3 words) sits next to a different-voice line on
    either side, drop the gap to 50ms so the interjection lands like a real
    talk-over rather than a paced hand-off. Same-voice transitions and two
    long lines from different voices keep the standard 300ms pause.
    """
    prev_voice, prev_words = prev_meta
    next_voice, next_words = next_meta
    if prev_voice != next_voice and (
        prev_words <= _INTERJECTION_MAX_WORDS
        or next_words <= _INTERJECTION_MAX_WORDS
    ):
        return _INTERJECTION_GAP_MS
    return _SILENCE_300MS


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
    # Track (voice, word_count) per non-hook segment so the stitcher can
    # tighten the gap around short reactions.
    hook_paths: list[Path] = []
    other_paths: list[Path] = []
    other_meta: list[tuple[str, int]] = []
    seg_idx = 0
    for act in script.get("acts", []):
        is_hook_act = act.get("name") == "HOOK" or act.get("bg_music")
        for line in act.get("lines", []):
            if seg_idx >= len(segments):
                break
            seg_path = segments[seg_idx]
            seg_idx += 1
            if is_hook_act:
                hook_paths.append(seg_path)
            else:
                voice = str(line.get("voice", "primary")).strip().lower()
                word_count = len((line.get("text") or "").split())
                other_paths.append(seg_path)
                other_meta.append((voice, word_count))

    combined = intro + AudioSegment.silent(duration=_SILENCE_500MS)

    if hook_paths:
        combined += _build_hook_chunk(hook_paths, ASSETS_DIR / "hook_music.mp3")
        combined += AudioSegment.silent(duration=_SILENCE_500MS)

    interjection_gaps = 0
    for i, seg_path in enumerate(other_paths):
        seg = AudioSegment.from_mp3(str(seg_path))
        combined += seg
        if i < len(other_paths) - 1:
            gap_ms = _gap_between(other_meta[i], other_meta[i + 1])
            if gap_ms == _INTERJECTION_GAP_MS:
                interjection_gaps += 1
            combined += AudioSegment.silent(duration=gap_ms)
    log.info(
        "Stitched %d segments — %d tight interjection gaps (%dms), rest at %dms",
        len(other_paths),
        interjection_gaps,
        _INTERJECTION_GAP_MS,
        _SILENCE_300MS,
    )

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
        script.get("episode_title", "The Impact Tape"),
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
        "title": script.get("episode_title", f"The Impact Tape — {date_str}"),
        "description": script.get("episode_description", ""),
        "duration_seconds": len(combined) // 1000,
        "file_size_bytes": audio_path.stat().st_size,
        "script_word_count": word_count,
        "elevenlabs_chars": char_count,
    }
