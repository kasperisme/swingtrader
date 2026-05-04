from __future__ import annotations

import os
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_ANALYTICS_ROOT = Path(__file__).resolve().parents[2]

OUTPUT_DIR = _ANALYTICS_ROOT / "output" / "podcast"
EPISODES_DIR = OUTPUT_DIR / "episodes"
SCRIPTS_DIR = OUTPUT_DIR / "scripts"
ASSETS_DIR = _ANALYTICS_ROOT / "scripts" / "assets" / "audio"
TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "")
ELEVENLABS_PRIMARY_VOICE_ID = os.environ.get("ELEVENLABS_PRIMARY_VOICE_ID", "")
ELEVENLABS_SECONDARY_VOICE_ID = os.environ.get("ELEVENLABS_SECONDARY_VOICE_ID", "")
ELEVENLABS_PRIMARY_VOICE_NAME = os.environ.get("ELEVENLABS_PRIMARY_VOICE_NAME", "")
ELEVENLABS_SECONDARY_VOICE_NAME = os.environ.get("ELEVENLABS_SECONDARY_VOICE_NAME", "")

# Hook voice (the "Hans" orchestrator persona). Distinct from the two co-host
# voices so the cold-open hook stands out from the welcome and acts. Falls
# back to the secondary voice ID when not configured.
ELEVENLABS_HOOK_VOICE_ID = os.environ.get("ELEVENLABS_HOOK_VOICE_ID", "")
ELEVENLABS_HOOK_VOICE_NAME = os.environ.get("ELEVENLABS_HOOK_VOICE_NAME", "Hans")

OLLAMA_PODCAST_SCRIPT_MODEL = os.environ.get(
    "OLLAMA_PODCAST_SCRIPT_MODEL", "glm-5.1:cloud"
)
OLLAMA_PODCAST_EXTRACT_MODEL = os.environ.get(
    "OLLAMA_PODCAST_EXTRACT_MODEL", "glm-5.1:cloud"
)
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434").rstrip(
    "/"
)

# OpenAI image generation (cover art)
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_IMAGE_MODEL = os.environ.get("OPENAI_IMAGE_MODEL", "gpt-image-1")
OPENAI_IMAGE_QUALITY = os.environ.get("OPENAI_IMAGE_QUALITY", "medium")  # low | medium | high

PODCAST_STORAGE_BUCKET = os.environ.get("PODCAST_STORAGE_BUCKET", "podcast")

# Hook music generated via ElevenLabs sound effects (cached as
# scripts/assets/audio/hook_music.mp3). Delete the file to regenerate.
PODCAST_HOOK_MUSIC_PROMPT = os.environ.get(
    "PODCAST_HOOK_MUSIC_PROMPT",
    "Cinematic ambient music bed for a financial news intro: low subtle pulse, "
    "soft synth pad, building anticipation, no melody, no drums, broadcast quality",
)
PODCAST_HOOK_MUSIC_DURATION_S = float(
    os.environ.get("PODCAST_HOOK_MUSIC_DURATION_S", "16")
)

PODCAST_ENABLED = os.environ.get("PODCAST_ENABLED", "true").lower() == "true"

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
