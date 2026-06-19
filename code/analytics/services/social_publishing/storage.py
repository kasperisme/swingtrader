"""Stage local media to a public Supabase Storage URL.

Ayrshare (and every native platform API) fetches media by URL — it can't take a
local file. So before posting we upload the reel / slides to a public bucket and
hand the public URLs to the publisher. Mirrors the podcast service's uploader.

Object keys are deterministic (``setups/<TICKER>/<platform>/<filename>``) so a
rerun overwrites in place and yields the same URL instead of piling up copies.
"""

from __future__ import annotations

import logging
import mimetypes
from pathlib import Path

from shared.db import get_supabase_client

from . import config

log = logging.getLogger(__name__)


def _content_type(path: Path) -> str:
    guess, _ = mimetypes.guess_type(path.name)
    return guess or "application/octet-stream"


def _upload(file_path: Path, object_key: str) -> str:
    client = get_supabase_client()
    storage = client.storage.from_(config.SOCIAL_MEDIA_BUCKET)
    body = file_path.read_bytes()
    storage.upload(
        path=object_key,
        file=body,
        file_options={
            "content-type": _content_type(file_path),
            "upsert": "true",
            "cache-control": "public, max-age=3600",
        },
    )
    public = storage.get_public_url(object_key)
    log.info("Uploaded %s → %s (%d bytes)", object_key, public, len(body))
    return public


def stage_media(ticker: str, platform: str, paths: list[Path]) -> list[str]:
    """Upload each media file for a platform; return public URLs in order."""
    base = f"setups/{ticker.upper()}/{platform}"
    return [_upload(p, f"{base}/{p.name}") for p in paths]
