"""Zernio backend — unified social publishing API (the default).

Posts one network per call: `POST /v1/posts` with a single-entry `platforms`
array (`[{platform, accountId}]`), the caption in `content`, and media in
`mediaItems` ([{type, url}], URLs must be publicly reachable over HTTPS — we
stage to a public Supabase bucket first). Account IDs come from `GET /v1/accounts`;
map each to a platform via ``ZERNIO_ACCOUNT_<PLATFORM>`` env vars.

Publishing is asynchronous: the create call only *accepts* the post, so we poll
`GET /v1/posts/{id}` until the platform reaches published/failed and report the
real outcome (verified the hard way — a 200 here does NOT mean it went live).

Schema confirmed against the OpenAPI spec at https://docs.zernio.com/api/openapi.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone

import httpx

from . import config
from .backends import PublishResult

log = logging.getLogger(__name__)

NAME = "zernio"
NEEDS_ACCOUNT_ID = True

# Publishing is async: the create call only *accepts* the post, then each
# platform's publish runs in the background and can still fail (e.g. media not
# fetchable). Poll the post until the platform reaches a terminal status.
_POLL_TIMEOUT_S = float(os.environ.get("ZERNIO_POLL_TIMEOUT_S", "180"))
_POLL_INTERVAL_S = float(os.environ.get("ZERNIO_POLL_INTERVAL_S", "6"))
_TERMINAL = {"published", "failed"}


class ZernioError(RuntimeError):
    pass


def is_configured() -> bool:
    return bool(config.ZERNIO_API_KEY)


def _headers() -> dict[str, str]:
    if not config.ZERNIO_API_KEY:
        raise ZernioError("ZERNIO_API_KEY is not set in .env")
    return {
        "Authorization": f"Bearer {config.ZERNIO_API_KEY}",
        "Content-Type": "application/json",
    }


def account_id_for(platform: str) -> str | None:
    """The Zernio accountId for a platform, from ZERNIO_ACCOUNT_<PLATFORM>."""
    return os.environ.get(f"ZERNIO_ACCOUNT_{platform.upper()}") or None


def list_accounts() -> list[dict]:
    """GET /v1/accounts → the connected social accounts (for setup/mapping)."""
    resp = httpx.get(
        f"{config.ZERNIO_BASE_URL}/accounts", headers=_headers(), timeout=30.0
    )
    resp.raise_for_status()
    data = resp.json()
    if isinstance(data, dict):
        return data.get("accounts") or data.get("data") or []
    return data if isinstance(data, list) else []


def best_time_slots(
    platform: str, account_id: str | None, source: str = "all"
) -> list[dict]:
    """GET /v1/analytics/best-time → weekday×hour slots ranked by the account's
    own historical engagement. Returns [] when the Analytics add-on is absent
    (403) or there's no post history yet — the caller then falls back."""
    params = {"source": source}
    if platform:
        params["platform"] = platform
    if account_id:
        params["accountId"] = account_id
    try:
        resp = httpx.get(
            f"{config.ZERNIO_BASE_URL}/analytics/best-time",
            params=params,
            headers=_headers(),
            timeout=30.0,
        )
    except Exception as exc:
        log.warning("best-time request failed: %s", exc)
        return []
    if resp.status_code == 403:
        log.info("best-time needs the Analytics add-on — falling back to default")
        return []
    if resp.status_code >= 400:
        return []
    body = resp.json() if resp.content else {}
    return body.get("slots") or []


def _platform_specific(platform: str) -> dict:
    """Per-platform settings Zernio needs for a direct publish.

    TikTok direct posts (post_mode DIRECT_POST) require a privacyLevel that
    matches the account's creator_info options, plus the interaction flags for
    video. Privacy is env-overridable: an app not yet audited for public posting
    may only allow SELF_ONLY — set ZERNIO_TIKTOK_PRIVACY=SELF_ONLY then.
    """
    if platform == "tiktok":
        return {
            "privacyLevel": os.environ.get(
                "ZERNIO_TIKTOK_PRIVACY", "PUBLIC_TO_EVERYONE"
            ),
            "allowComment": True,
            "allowDuet": True,
            "allowStitch": True,
        }
    return {}


def _platform_entry(post: dict, platform: str) -> dict:
    """Pull the matching platform sub-object out of a post payload."""
    for pl in post.get("platforms", []):
        if pl.get("platform") == platform:
            return pl
    return {}


def _poll_outcome(post_id: str, platform: str) -> PublishResult:
    """Poll GET /v1/posts/{id} until the platform publish is terminal.

    Returns the real outcome: published (with the live URL), failed (with the
    platform error), or — if it's still running past the timeout — accepted, so
    the caller knows it was queued but not yet confirmed.
    """
    url = f"{config.ZERNIO_BASE_URL}/posts/{post_id}"
    deadline = time.monotonic() + _POLL_TIMEOUT_S
    last = "processing"
    while time.monotonic() < deadline:
        try:
            resp = httpx.get(url, headers=_headers(), timeout=30.0)
            body = resp.json() if resp.content else {}
        except Exception as exc:
            log.warning("poll error for %s: %s", post_id, exc)
            time.sleep(_POLL_INTERVAL_S)
            continue
        post = body.get("post", body)
        pl = _platform_entry(post, platform)
        last = pl.get("status") or post.get("status") or last
        if last in _TERMINAL:
            if last == "published":
                live = pl.get("platformPostUrl") or ""
                return PublishResult(True, urls=[live] if live else [], detail=live or "published")
            err = pl.get("errorMessage") or pl.get("error") or "failed"
            return PublishResult(False, detail=f"failed: {err}")
        time.sleep(_POLL_INTERVAL_S)
    return PublishResult(
        False,
        detail=f"accepted but still '{last}' after {_POLL_TIMEOUT_S:.0f}s "
        f"(post {post_id}) — check Zernio for the final result",
    )


def publish(
    platform: str,
    caption: str,
    media_urls: list[str],
    kind: str,
    *,
    account_id: str | None,
    schedule_at: datetime | None = None,
) -> PublishResult:
    if not account_id:
        return PublishResult(
            False,
            detail=f"no Zernio accountId for {platform} "
            f"(set ZERNIO_ACCOUNT_{platform.upper()} — run `cli accounts`)",
        )

    # Per the OpenAPI spec: media goes in `mediaItems` (array of MediaItem
    # {type,url}); URLs must be publicly reachable over HTTPS (our Supabase
    # public URLs qualify). Networks are targeted via the `platforms` array of
    # {platform, accountId}, with optional per-platform `platformSpecificData`.
    mtype = "video" if kind == "video" else "image"
    target: dict = {"platform": platform, "accountId": account_id}
    psd = _platform_specific(platform)
    if psd:
        target["platformSpecificData"] = psd

    payload: dict = {
        "content": caption,
        "mediaItems": [{"type": mtype, "url": u} for u in media_urls],
        "platforms": [target],
    }
    if schedule_at is not None:
        # Always send UTC + timezone:"UTC" so there's no offset ambiguity.
        payload["scheduledFor"] = schedule_at.astimezone(timezone.utc).isoformat()
        payload["timezone"] = "UTC"
    else:
        payload["publishNow"] = True

    resp = httpx.post(
        f"{config.ZERNIO_BASE_URL}/posts",
        json=payload,
        headers=_headers(),
        timeout=120.0,
    )
    try:
        body = resp.json()
    except Exception:
        body = {"raw": resp.text}

    if resp.status_code == 409:
        # Content-hash dedup: same content+media to this account within 24h.
        existing = (body.get("details") or {}).get("existingPostId") or body.get("existingPostId")
        return PublishResult(
            False,
            detail=f"duplicate within 24h (existingPostId={existing}) — "
            f"change the caption or media to re-post",
        )
    if resp.status_code == 429:
        return PublishResult(False, detail=f"rate limited: {body.get('error') or body}")
    if resp.status_code >= 400:
        return PublishResult(False, detail=f"Zernio {resp.status_code}: {body}")

    post = body.get("post", body)
    post_id = post.get("_id") or post.get("id") or body.get("existingPost", {}).get("_id")
    if not post_id:
        return PublishResult(False, detail=f"accepted but no post id in response: {body}")

    if schedule_at is not None:
        # Scheduled posts won't publish now — confirm acceptance, don't poll.
        st = _platform_entry(post, platform).get("status") or post.get("status") or "scheduled"
        iso = schedule_at.astimezone(timezone.utc).isoformat()
        return PublishResult(True, detail=f"scheduled ({st}) for {iso}  [post {post_id}]")

    # Immediate publish is async — poll for the real terminal outcome.
    return _poll_outcome(post_id, platform)
