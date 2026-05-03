from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path

from .config import ELEVENLABS_API_KEY
from .voices import get_voice

log = logging.getLogger(__name__)

_PAUSE_RE = re.compile(r"\[PAUSE\]", re.IGNORECASE)


def _strip_pause_markers(text: str) -> str:
    return _PAUSE_RE.sub("", text).strip()


async def render_segment(text: str, voice_name: str, output_path: Path) -> Path:
    """Render a single TTS segment via ElevenLabs SDK."""
    try:
        from elevenlabs.client import ElevenLabs
    except ImportError:
        raise RuntimeError("elevenlabs package not installed")

    if not ELEVENLABS_API_KEY:
        raise RuntimeError("ELEVENLABS_API_KEY not set")

    voice = get_voice(voice_name)
    clean_text = _strip_pause_markers(text)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    client = ElevenLabs(api_key=ELEVENLABS_API_KEY)

    log.debug("Rendering segment: voice=%s, chars=%d → %s", voice.name, len(clean_text), output_path.name)

    try:
        audio = client.text_to_speech.convert(
            voice_id=voice.voice_id,
            text=clean_text,
            model_id=voice.model_id,
            output_format=voice.output_format,
            voice_settings={
                "stability": voice.stability,
                "similarity_boost": 0.75,
                "style": voice.style,
                "use_speaker_boost": True,
            },
        )
        audio_bytes = b"".join(audio)
        output_path.write_bytes(audio_bytes)
        return output_path
    except Exception as exc:
        if "429" in str(exc):
            log.warning("Rate limited by ElevenLabs, waiting 60s before retry")
            await asyncio.sleep(60)
            audio = client.text_to_speech.convert(
                voice_id=voice.voice_id,
                text=clean_text,
                model_id=voice.model_id,
                output_format=voice.output_format,
                voice_settings={
                    "stability": voice.stability,
                    "similarity_boost": 0.75,
                    "style": voice.style,
                    "use_speaker_boost": True,
                },
            )
            audio_bytes = b"".join(audio)
            output_path.write_bytes(audio_bytes)
            return output_path
        raise


async def render_episode(script: dict, output_dir: Path) -> list[Path]:
    """Render all script lines sequentially, return ordered list of segment paths."""
    output_dir.mkdir(parents=True, exist_ok=True)
    segments: list[Path] = []

    for act_data in script.get("acts", []):
        act_num = act_data["act"]
        for line_idx, line in enumerate(act_data.get("lines", [])):
            voice = line["voice"]
            text = line["text"]
            filename = f"act{act_num:02d}_{line_idx:03d}_{voice}.mp3"
            out_path = output_dir / filename

            log.info("Rendering act=%d line=%d voice=%s", act_num, line_idx, voice)
            await render_segment(text, voice, out_path)
            segments.append(out_path)

    log.info("Rendered %d segments", len(segments))
    return segments
