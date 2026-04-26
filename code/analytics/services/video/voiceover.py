from __future__ import annotations

import base64
import logging
from pathlib import Path

import subprocess

from .config import ELEVENLABS_API_KEY, ELEVENLABS_VOICE_ID, ELEVENLABS_MODEL, OUTPUT_DIR

FFMPEG = "ffmpeg"

log = logging.getLogger(__name__)


async def generate_voiceover(
    text: str,
    output_path: Path | None = None,
    voice_id: str | None = None,
) -> tuple[Path, list[dict]]:
    try:
        from elevenlabs.client import ElevenLabs
    except ImportError:
        raise RuntimeError("elevenlabs not installed. Run: pip install elevenlabs")

    if not ELEVENLABS_API_KEY:
        raise RuntimeError("ELEVENLABS_API_KEY env var not set")

    voice_id = voice_id or ELEVENLABS_VOICE_ID
    output_path = output_path or OUTPUT_DIR / "voiceover.mp3"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    client = ElevenLabs(api_key=ELEVENLABS_API_KEY)

    log.info("Generating voiceover via ElevenLabs: %d chars, voice=%s", len(text), voice_id)

    response = client.text_to_speech.convert_with_timestamps(
        voice_id=voice_id,
        text=text,
        model_id=ELEVENLABS_MODEL,
        output_format="mp3_44100_128",
    )

    mp3_path = output_path.with_suffix(".mp3")
    mp3_path.write_bytes(base64.b64decode(response.audio_base_64))

    word_timings = _alignment_to_word_timings(
        response.alignment.characters,
        response.alignment.character_start_times_seconds,
        response.alignment.character_end_times_seconds,
        text,
    )

    log.info("Voiceover saved: %s, %d word timings", mp3_path.name, len(word_timings))
    return mp3_path, word_timings


def _alignment_to_word_timings(
    characters: list[str],
    starts: list[float],
    ends: list[float],
    text: str,
) -> list[dict]:
    """Convert ElevenLabs character-level alignment to word-level timings."""
    word_timings: list[dict] = []
    current_chars: list[str] = []
    current_start: float | None = None
    current_end: float = 0.0

    for char, start, end in zip(characters, starts, ends):
        if char in (" ", "\n", "\t"):
            if current_chars:
                word = "".join(current_chars)
                word_timings.append({"word": word, "start": current_start, "end": current_end})
                current_chars = []
                current_start = None
        else:
            if current_start is None:
                current_start = start
            current_chars.append(char)
            current_end = end

    if current_chars:
        word = "".join(current_chars)
        word_timings.append({"word": word, "start": current_start, "end": current_end})

    return word_timings


def generate_silent_audio(duration: float, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        FFMPEG, "-y",
        "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=stereo",
        "-t", f"{duration:.2f}",
        "-c:a", "libmp3lame", "-b:a", "128k",
        str(output_path.with_suffix(".mp3")),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"silent audio generation failed: {result.stderr[:300]}")
    log.info("Silent audio: %.1fs → %s", duration, output_path.name)
    return output_path.with_suffix(".mp3")


def build_captions(
    word_timings: list[dict],
    max_chars: int = 36,
) -> list[dict]:
    captions = []
    current_words: list[dict] = []
    current_len = 0

    for wt in word_timings:
        word = wt["word"]
        if current_len + len(word) + (1 if current_words else 0) > max_chars and current_words:
            text = " ".join(w["word"] for w in current_words)
            captions.append({
                "text": text,
                "start": current_words[0]["start"],
                "end": current_words[-1]["end"],
            })
            current_words = []
            current_len = 0

        current_words.append(wt)
        current_len += len(word) + (1 if len(current_words) > 1 else 0)

    if current_words:
        text = " ".join(w["word"] for w in current_words)
        captions.append({
            "text": text,
            "start": current_words[0]["start"],
            "end": current_words[-1]["end"],
        })

    return captions
