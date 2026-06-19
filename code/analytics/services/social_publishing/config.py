from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

_ANALYTICS_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(dotenv_path=_ANALYTICS_ROOT / ".env")

# Where the nis-stock-breakdown skill writes its per-ticker assets.
SETUPS_DIR = _ANALYTICS_ROOT / "output" / "setups"

# Which publishing aggregator delivers the post. "zernio" (default) or "ayrshare".
# Both fan a post out to every connected network through one REST API and own the
# platform tokens + the TikTok/Meta app review. The asset/caption layer is
# identical for both — only the backend module changes (see backends.py).
SOCIAL_BACKEND = os.environ.get("SOCIAL_BACKEND", "zernio").strip().lower()

# --- Zernio (default backend) ----------------------------------------------
#   ZERNIO_API_KEY            — required to publish (Bearer "sk_..." key)
#   ZERNIO_ACCOUNT_<PLATFORM> — the Zernio accountId for each connected network,
#                               e.g. ZERNIO_ACCOUNT_INSTAGRAM=acc_xxx. Get them
#                               with `cli accounts`.
ZERNIO_API_KEY = os.environ.get("ZERNIO_API_KEY", "")
ZERNIO_BASE_URL = os.environ.get(
    "ZERNIO_BASE_URL", "https://zernio.com/api/v1"
).rstrip("/")

# --- Ayrshare (alternative backend) ----------------------------------------
AYRSHARE_API_KEY = os.environ.get("AYRSHARE_API_KEY", "")
AYRSHARE_PROFILE_KEY = os.environ.get("AYRSHARE_PROFILE_KEY", "")
AYRSHARE_BASE_URL = os.environ.get(
    "AYRSHARE_BASE_URL", "https://api.ayrshare.com/api"
).rstrip("/")

# Supabase Storage bucket holding the publicly-fetchable media. Every aggregator
# pulls media by URL, so local files are staged here first and the public URL is
# handed off. Must be a PUBLIC bucket. Reuses SUPABASE_URL/SUPABASE_KEY.
SOCIAL_MEDIA_BUCKET = os.environ.get("SOCIAL_MEDIA_BUCKET", "social")

# The four platforms we target. Names match both aggregators' identifiers.
PLATFORMS = ("instagram", "facebook", "tiktok", "linkedin")

# Default media kind per platform. "video" ships the reel; "carousel" ships the
# slide PNGs. TikTok is video-only. A per-ticker social/manifest.json can
# override any of these (see assets.py).
DEFAULT_KIND = {
    "instagram": "video",
    "facebook": "video",
    "tiktok": "video",
    "linkedin": "video",
}
