from __future__ import annotations

import os
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_ANALYTICS_ROOT = Path(__file__).resolve().parents[2]

OUTPUT_DIR = _ANALYTICS_ROOT / "output" / "podcast"
EPISODES_DIR = OUTPUT_DIR / "episodes"
SCRIPTS_DIR = OUTPUT_DIR / "scripts"
RSS_FEED_PATH = OUTPUT_DIR / "rss_feed.xml"
ASSETS_DIR = _ANALYTICS_ROOT / "scripts" / "assets" / "audio"
TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "")
ELEVENLABS_MARCUS_VOICE_ID = os.environ.get("ELEVENLABS_MARCUS_VOICE_ID", "")
ELEVENLABS_KAI_VOICE_ID = os.environ.get("ELEVENLABS_KAI_VOICE_ID", "")

HANS_SCRIPT_MODEL = os.environ.get("HANS_SCRIPT_MODEL", "glm-4.6")
HANS_EXTRACT_MODEL = os.environ.get("HANS_EXTRACT_MODEL", "glm-5.1")
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")

R2_ENDPOINT_URL = os.environ.get("R2_ENDPOINT_URL", "")
R2_ACCESS_KEY_ID = os.environ.get("R2_ACCESS_KEY_ID", "")
R2_SECRET_ACCESS_KEY = os.environ.get("R2_SECRET_ACCESS_KEY", "")
R2_BUCKET_NAME = os.environ.get("R2_BUCKET_NAME", "")
R2_PUBLIC_BASE_URL = os.environ.get("R2_PUBLIC_BASE_URL", "")
R2_SYNC_TO_WEB = os.environ.get("R2_SYNC_TO_WEB", "false").lower() == "true"

PODCAST_ENABLED = os.environ.get("PODCAST_ENABLED", "true").lower() == "true"

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
