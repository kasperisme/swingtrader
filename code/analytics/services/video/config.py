from __future__ import annotations

import os
from pathlib import Path
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

_REPO_ROOT = Path(__file__).resolve().parent.parent

EASTERN = ZoneInfo("America/New_York")

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
OLLAMA_TIKTOK_MODEL = (
    os.environ.get("OLLAMA_TIKTOK_MODEL")
    or os.environ.get("OLLAMA_BLOG_MODEL")
    or os.environ.get("OLLAMA_IMPACT_MODEL")
    or "gemma4:e4b"
)

OUTPUT_DIR = Path(os.environ.get("TIKTOK_OUTPUT_DIR", str(_REPO_ROOT / "output" / "tiktok")))

VIDEO_WIDTH = 1080
VIDEO_HEIGHT = 1920
VIDEO_FPS = 24
VIDEO_CODEC = "libx264"
AUDIO_CODEC = "aac"

SAFE_ZONE_RIGHT = 1.0
SAFE_ZONE_BOTTOM = 0.15

ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_ID = os.environ.get("ELEVENLABS_VOICE_ID", "onwK4e9ZLuTAKqWW03F9")  # Daniel
ELEVENLABS_MODEL = os.environ.get("ELEVENLABS_MODEL", "eleven_turbo_v2_5")

BACKGROUND_MUSIC = os.environ.get("TIKTOK_BG_MUSIC", "")
BG_MUSIC_VOLUME = float(os.environ.get("TIKTOK_BG_MUSIC_VOLUME", "0.08"))

REPORTER_VIDEO = os.environ.get(
    "TIKTOK_REPORTER_VIDEO",
    str(_REPO_ROOT / "scripts" / "assets" / "reporter.mp4"),
)

LOOKBACK_HOURS = int(os.environ.get("TIKTOK_LOOKBACK_HOURS", "14"))
MAX_ARTICLES = int(os.environ.get("TIKTOK_MAX_ARTICLES", "15"))

from services.rag.taxonomy import CLUSTERS, CLUSTER_ID_TO_LABEL, DIM_KEY_TO_LABEL  # noqa: F401

CAPTION_FONT_SIZE = 52
CAPTION_MAX_CHARS = 32

BG_COLOR = "#FCFAF6"
TEXT_COLOR = "#0E1629"
TEXT_COLOR_DIM = "#536278"
BRAND_COLOR = "#F49E0A"
BRAND_COLOR_DIM = "#DFD6CD"
ACCENT_GREEN = "#10B981"
ACCENT_RED = "#EF4444"
ACCENT_YELLOW = "#F19040"
