"""
Supabase publisher — uploads the packaged episode + cover to Supabase Storage,
and writes a complete metadata row to swingtrader.podcast_episodes.

The UI consumes that table (or the storage URLs directly) to render the RSS
feed at request time. RSS XML is no longer assembled or stored on the analytics
side — Supabase is the single source of truth.

Flow:
  1. Upload audio MP3 to bucket=podcast, path=YYYY-MM-DD_episode.mp3
  2. Upload cover PNG to bucket=podcast, path=YYYY-MM-DD_cover.png
  3. Build a stable GUID and public URLs
  4. Upsert into podcast_episodes (one row per date) — idempotent on rerun
  5. Return the audio public URL so the orchestrator can announce it

Configuration:
  SUPABASE_URL                — project URL
  SUPABASE_KEY                — service-role key (required for storage writes)
  PODCAST_STORAGE_BUCKET      — bucket name, default "podcast"
"""

from __future__ import annotations

import logging
import mimetypes
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from shared.db import get_supabase_client

log = logging.getLogger(__name__)

_BUCKET = os.environ.get("PODCAST_STORAGE_BUCKET", "podcast")
_SCHEMA = "swingtrader"


def _content_type(path: Path) -> str:
    guess, _ = mimetypes.guess_type(path.name)
    return guess or "application/octet-stream"


def _upload(file_path: Path, object_key: str) -> str:
    """Upload a single file to Supabase Storage, return its public URL.

    Idempotent: re-uploads overwrite the existing object so reruns produce
    the same URL. Raises RuntimeError on failure (let the orchestrator decide).
    """
    client = get_supabase_client()
    storage = client.storage.from_(_BUCKET)

    with open(file_path, "rb") as fh:
        body = fh.read()

    # supabase-py >= 2.0: file_options governs both content-type and upsert.
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


def _upsert_episode_row(
    *,
    date_str: str,
    title: str,
    description: str,
    audio_url: str,
    cover_url: str,
    duration_seconds: int,
    file_size_bytes: int,
    guid: str,
    script_word_count: int,
    elevenlabs_chars: int,
) -> None:
    """Insert or update the podcast_episodes row for this date.

    On a same-date rerun, the row is updated in place — keeps the feed clean
    instead of accumulating duplicate items.
    """
    client = get_supabase_client()
    estimated_cost = round(elevenlabs_chars * 0.00003, 4)
    payload = {
        "date": date_str,
        "title": title,
        "description": description,
        "episode_url": audio_url,    # legacy column kept for backwards compat
        "audio_url": audio_url,
        "cover_url": cover_url,
        "duration_seconds": duration_seconds,
        "file_size_bytes": int(file_size_bytes),
        "script_word_count": script_word_count,
        "elevenlabs_chars": elevenlabs_chars,
        "estimated_cost_usd": estimated_cost,
        "guid": guid,
        "published_at": datetime.now(timezone.utc).isoformat(),
        "status": "published",
    }
    client.schema(_SCHEMA).table("podcast_episodes").upsert(
        payload, on_conflict="guid"
    ).execute()
    log.info("podcast_episodes upserted (date=%s, guid=%s)", date_str, guid[:8])


async def publish_episode(metadata: dict, date_str: str) -> str:
    """Upload episode artefacts to Supabase + write metadata row.

    Returns the public audio URL. The UI's RSS handler renders the rest.
    """
    audio_path: Path = metadata["audio_path"]
    cover_path: Path = metadata["cover_path"]

    audio_key = f"{date_str}_episode.mp3"
    cover_key = f"{date_str}_cover.png"

    log.info("Publishing episode for %s to Supabase bucket=%s", date_str, _BUCKET)

    audio_url = _upload(audio_path, audio_key)
    cover_url = _upload(cover_path, cover_key)

    guid = str(uuid.uuid5(uuid.NAMESPACE_URL, audio_url))

    _upsert_episode_row(
        date_str=date_str,
        title=metadata["title"],
        description=metadata.get("description") or "",
        audio_url=audio_url,
        cover_url=cover_url,
        duration_seconds=int(metadata["duration_seconds"]),
        file_size_bytes=int(metadata["file_size_bytes"]),
        guid=guid,
        script_word_count=int(metadata.get("script_word_count") or 0),
        elevenlabs_chars=int(metadata.get("elevenlabs_chars") or 0),
    )

    log.info("Episode published: %s", audio_url)
    return audio_url
