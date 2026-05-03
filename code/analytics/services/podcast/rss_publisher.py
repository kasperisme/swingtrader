from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from xml.etree import ElementTree as ET

from jinja2 import Environment, FileSystemLoader

from .config import (
    R2_ACCESS_KEY_ID,
    R2_BUCKET_NAME,
    R2_ENDPOINT_URL,
    R2_PUBLIC_BASE_URL,
    R2_SECRET_ACCESS_KEY,
    R2_SYNC_TO_WEB,
    RSS_FEED_PATH,
    TEMPLATES_DIR,
)

log = logging.getLogger(__name__)

_jinja_env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=False)

_RSS_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"
  xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"
  xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>NewsImpact Daily &#x2014; Market Intelligence Digest</title>
    <link>https://newsimpactscreener.com</link>
    <description>Daily AI-generated market intelligence for swing traders.</description>
    <itunes:author>NewsImpactScreener</itunes:author>
    <itunes:category text="Business">
      <itunes:category text="Investing"/>
    </itunes:category>
    <itunes:image href="https://newsimpactscreener.com/podcast/cover.png"/>
    <language>en-us</language>
    <itunes:explicit>no</itunes:explicit>
  </channel>
</rss>
"""


def _ensure_rss_feed() -> str:
    if RSS_FEED_PATH.exists():
        return RSS_FEED_PATH.read_text(encoding="utf-8")
    RSS_FEED_PATH.parent.mkdir(parents=True, exist_ok=True)
    RSS_FEED_PATH.write_text(_RSS_TEMPLATE, encoding="utf-8")
    log.info("Created initial RSS feed: %s", RSS_FEED_PATH)
    return _RSS_TEMPLATE


def _upload_to_r2(file_path: Path, object_key: str) -> str | None:
    if not all([R2_ENDPOINT_URL, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET_NAME]):
        log.warning("R2 not configured — skipping upload, using local path")
        return None

    try:
        import boto3

        s3 = boto3.client(
            "s3",
            endpoint_url=R2_ENDPOINT_URL,
            aws_access_key_id=R2_ACCESS_KEY_ID,
            aws_secret_access_key=R2_SECRET_ACCESS_KEY,
        )
        s3.upload_file(
            str(file_path),
            R2_BUCKET_NAME,
            object_key,
            ExtraArgs={"ContentType": "audio/mpeg"},
        )
        public_url = f"{R2_PUBLIC_BASE_URL.rstrip('/')}/{object_key}"
        log.info("Uploaded to R2: %s", public_url)
        return public_url
    except Exception as exc:
        log.error("R2 upload failed: %s", exc)
        return None


async def publish_episode(metadata: dict, date_str: str) -> str:
    audio_path: Path = metadata["audio_path"]
    cover_path: Path = metadata["cover_path"]

    object_key = f"podcast/{date_str}_episode.mp3"
    cover_key = f"podcast/{date_str}_cover.png"

    audio_url = _upload_to_r2(audio_path, object_key)
    cover_url = _upload_to_r2(cover_path, cover_key)

    if audio_url is None:
        audio_url = str(audio_path.resolve())
    if cover_url is None:
        cover_url = f"https://newsimpactscreener.com/podcast/cover.png"

    pub_date = format_datetime(datetime.now(timezone.utc))
    episode_guid = str(uuid.uuid5(uuid.NAMESPACE_URL, audio_url))

    template = _jinja_env.get_template("rss_episode.j2")
    item_block = template.render(
        title=metadata["title"],
        description=metadata["description"],
        audio_url=audio_url,
        file_size_bytes=metadata["file_size_bytes"],
        pub_date=pub_date,
        duration_seconds=metadata["duration_seconds"],
        cover_url=cover_url,
        guid=episode_guid,
    )

    xml_str = _ensure_rss_feed()
    insert_after = "<channel>"
    insert_pos = xml_str.index(insert_after) + len(insert_after)
    updated_xml = xml_str[:insert_pos] + "\n" + item_block + xml_str[insert_pos:]

    RSS_FEED_PATH.write_text(updated_xml, encoding="utf-8")
    log.info("RSS feed updated: %s", RSS_FEED_PATH)

    if R2_SYNC_TO_WEB:
        rss_key = "podcast/rss_feed.xml"
        _upload_to_r2_xml(RSS_FEED_PATH, rss_key)

    return audio_url


def _upload_to_r2_xml(file_path: Path, object_key: str) -> None:
    if not all([R2_ENDPOINT_URL, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET_NAME]):
        return
    try:
        import boto3

        s3 = boto3.client(
            "s3",
            endpoint_url=R2_ENDPOINT_URL,
            aws_access_key_id=R2_ACCESS_KEY_ID,
            aws_secret_access_key=R2_SECRET_ACCESS_KEY,
        )
        s3.upload_file(
            str(file_path),
            R2_BUCKET_NAME,
            object_key,
            ExtraArgs={"ContentType": "application/rss+xml"},
        )
        log.info("RSS feed synced to R2: %s", object_key)
    except Exception as exc:
        log.error("RSS R2 sync failed: %s", exc)
