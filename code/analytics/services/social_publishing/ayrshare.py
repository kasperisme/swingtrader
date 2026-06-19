"""Ayrshare backend — alternative publishing aggregator.

Conforms to the same interface as the Zernio backend (see backends.py) so the
two are interchangeable via the SOCIAL_BACKEND env var. Ayrshare addresses
networks by platform name (not a per-account id), so account_id is unused here.

Docs: https://docs.ayrshare.com/rest-api/endpoints/post
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx

from . import config
from .backends import PublishResult

log = logging.getLogger(__name__)

NAME = "ayrshare"
NEEDS_ACCOUNT_ID = False


class AyrshareError(RuntimeError):
    pass


def is_configured() -> bool:
    return bool(config.AYRSHARE_API_KEY)


def account_id_for(platform: str) -> str | None:  # noqa: ARG001 - interface parity
    return None


def _headers() -> dict[str, str]:
    if not config.AYRSHARE_API_KEY:
        raise AyrshareError("AYRSHARE_API_KEY is not set in .env")
    headers = {
        "Authorization": f"Bearer {config.AYRSHARE_API_KEY}",
        "Content-Type": "application/json",
    }
    if config.AYRSHARE_PROFILE_KEY:
        headers["Profile-Key"] = config.AYRSHARE_PROFILE_KEY
    return headers


def _platform_options(platform: str, kind: str) -> dict:
    if platform == "instagram" and kind == "video":
        return {"instagramOptions": {"reels": True}}
    return {}


def publish(
    platform: str,
    caption: str,
    media_urls: list[str],
    kind: str,
    *,
    account_id: str | None = None,  # noqa: ARG001 - interface parity
    schedule_at: datetime | None = None,
) -> PublishResult:
    payload: dict = {
        "post": caption,
        "platforms": [platform],
        "mediaUrls": media_urls,
        **_platform_options(platform, kind),
    }
    if kind == "video":
        payload["isVideo"] = True
    if schedule_at is not None:
        payload["scheduleDate"] = schedule_at.astimezone(timezone.utc).isoformat()

    resp = httpx.post(
        f"{config.AYRSHARE_BASE_URL}/post",
        json=payload,
        headers=_headers(),
        timeout=120.0,
    )
    try:
        body = resp.json()
    except Exception:
        body = {"raw": resp.text}

    if resp.status_code >= 400:
        return PublishResult(False, detail=f"Ayrshare {resp.status_code}: {body}")

    status = body.get("status")
    errors = body.get("errors") or []
    post_ids = body.get("postIds") or []
    if status == "success" and not errors:
        urls = [pid.get("postUrl", "") for pid in post_ids if pid.get("postUrl")]
        return PublishResult(True, urls=urls, detail=", ".join(urls) or "published")
    return PublishResult(False, detail=f"status={status} errors={errors or body}")
