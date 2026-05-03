from __future__ import annotations

from dataclasses import dataclass

from .config import ELEVENLABS_MARCUS_VOICE_ID, ELEVENLABS_KAI_VOICE_ID

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


MARCUS = VoiceConfig(
    name="marcus",
    voice_id=ELEVENLABS_MARCUS_VOICE_ID,
    stability=0.75,
    style=0.20,
)

KAI = VoiceConfig(
    name="kai",
    voice_id=ELEVENLABS_KAI_VOICE_ID,
    stability=0.60,
    style=0.45,
)

VOICES: dict[str, VoiceConfig] = {
    "marcus": MARCUS,
    "kai": KAI,
}

# Acts handled primarily by each voice (both may still appear for dialogue)
MARCUS_ACTS = {1, 2, 5}
KAI_ACTS = {3, 4}


def get_voice(name: str) -> VoiceConfig:
    try:
        return VOICES[name.lower()]
    except KeyError:
        raise ValueError(f"Unknown voice '{name}'. Valid voices: {list(VOICES)}")
