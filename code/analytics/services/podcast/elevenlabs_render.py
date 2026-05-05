from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path

from .config import (
    ASSETS_DIR,
    ELEVENLABS_API_KEY,
    PODCAST_HOOK_MUSIC_DURATION_S,
    PODCAST_HOOK_MUSIC_PROMPT,
)
from .voices import get_voice

log = logging.getLogger(__name__)

_PAUSE_RE = re.compile(r"\[PAUSE\]", re.IGNORECASE)


def _normalize_pauses(text: str) -> str:
    """Translate legacy [PAUSE] markers into ElevenLabs <break> tags.

    The eleven_multilingual_v2 model honors `<break time="x.xs" />` (max 3s).
    Older generated scripts may still contain bare [PAUSE] tokens — convert
    them rather than dropping them so any leftover text still produces a
    real pause. New scripts should emit `<break ... />` directly.
    """
    return _PAUSE_RE.sub('<break time="0.5s" />', text).strip()


async def render_segment(text: str, voice_name: str, output_path: Path) -> Path:
    """Render a single TTS segment via ElevenLabs SDK."""
    try:
        from elevenlabs.client import ElevenLabs
    except ImportError:
        raise RuntimeError("elevenlabs package not installed")

    if not ELEVENLABS_API_KEY:
        raise RuntimeError("ELEVENLABS_API_KEY not set")

    voice = get_voice(voice_name)
    clean_text = _normalize_pauses(text)
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


def ensure_hook_music(
    output_path: Path | None = None,
    *,
    prompt: str | None = None,
    duration_seconds: float | None = None,
) -> Path | None:
    """Generate (and cache) a soft hook music bed via ElevenLabs sound effects.

    The track is cached to disk so a daily podcast keeps a consistent intro
    bed without re-spending API credits. Delete the cached file to regenerate.
    Returns the path on success, None on failure (caller falls back to silence).
    """
    target = output_path or (ASSETS_DIR / "hook_music.mp3")
    if target.exists() and target.stat().st_size > 0:
        log.info(
            "Hook music ready (cached): %s (%d bytes)",
            target,
            target.stat().st_size,
        )
        return target

    if not ELEVENLABS_API_KEY:
        log.warning("ELEVENLABS_API_KEY not set — cannot generate hook music")
        return None

    try:
        from elevenlabs.client import ElevenLabs
    except ImportError:
        log.warning("elevenlabs package not installed — cannot generate hook music")
        return None

    target.parent.mkdir(parents=True, exist_ok=True)
    client = ElevenLabs(api_key=ELEVENLABS_API_KEY)
    effective_prompt = prompt or PODCAST_HOOK_MUSIC_PROMPT
    effective_duration = duration_seconds or PODCAST_HOOK_MUSIC_DURATION_S

    log.info(
        "Generating hook music via ElevenLabs sound effects: duration=%.1fs, prompt=%r",
        effective_duration,
        effective_prompt[:80],
    )
    try:
        audio = client.text_to_sound_effects.convert(
            text=effective_prompt,
            duration_seconds=effective_duration,
            prompt_influence=0.3,
        )
        audio_bytes = b"".join(audio)
        target.write_bytes(audio_bytes)
        log.info("Hook music cached (%d bytes) → %s", len(audio_bytes), target)
        return target
    except Exception as exc:
        log.warning("Hook music generation failed: %s", exc)
        return None


async def render_episode(script: dict, output_dir: Path) -> list[Path]:
    """Render all script lines sequentially, return ordered list of segment paths."""
    output_dir.mkdir(parents=True, exist_ok=True)
    segments: list[Path] = []

    has_hook = any(
        act.get("name") == "HOOK" or act.get("bg_music")
        for act in script.get("acts", [])
    )
    if has_hook:
        music_path = ensure_hook_music()
        if music_path is None:
            log.warning(
                "Hook act present but no bg music available — episode will play "
                "the hook without a music bed (set ELEVENLABS_API_KEY to enable "
                "sound-effects generation, or place a file at %s)",
                ASSETS_DIR / "hook_music.mp3",
            )

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
