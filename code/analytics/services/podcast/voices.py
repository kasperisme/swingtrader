from __future__ import annotations

from dataclasses import dataclass

from .config import (
    ELEVENLABS_PRIMARY_VOICE_ID,
    ELEVENLABS_SECONDARY_VOICE_ID,
    ELEVENLABS_PRIMARY_VOICE_NAME,
    ELEVENLABS_SECONDARY_VOICE_NAME,
)

ELEVENLABS_MODEL = "eleven_multilingual_v2"
ELEVENLABS_OUTPUT_FORMAT = "mp3_44100_128"


@dataclass(frozen=True)
class VoiceConfig:
    name: str
    voice_id: str
    stability: float
    style: float
    model_id: str = ELEVENLABS_MODEL
    output_format: str = ELEVENLABS_OUTPUT_FORMAT


PRIMARY = VoiceConfig(
    name=ELEVENLABS_PRIMARY_VOICE_NAME,
    voice_id=ELEVENLABS_PRIMARY_VOICE_ID,
    stability=0.75,
    style=0.20,
)

SECONDARY = VoiceConfig(
    name=ELEVENLABS_SECONDARY_VOICE_NAME,
    voice_id=ELEVENLABS_SECONDARY_VOICE_ID,
    stability=0.60,
    style=0.45,
)

VOICES: dict[str, VoiceConfig] = {
    "primary": PRIMARY,
    "secondary": SECONDARY,
}

# Acts handled primarily by each voice (both may still appear for dialogue)
PRIMARY_ACTS = {1, 2, 5}
SECONDARY_ACTS = {3, 4}


def get_voice(name: str) -> VoiceConfig:
    try:
        return VOICES[name.lower()]
    except KeyError:
        raise ValueError(f"Unknown voice '{name}'. Valid voices: {list(VOICES)}")
