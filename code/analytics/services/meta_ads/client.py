"""Thin Meta Graph (Marketing) API client — GET-only, paginated. Read access.

If a call fails with a version error, set META_API_VERSION in .env to a version
your app supports (the error message names the valid range).
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from urllib.parse import parse_qs

import requests
from dotenv import load_dotenv

_ANALYTICS = Path(__file__).resolve().parents[2]
load_dotenv(_ANALYTICS / ".env")

TOKEN = os.environ.get("META_ADS_TOKEN", "")
_ACCOUNT = os.environ.get("META_AD_ACCOUNT_ID", "")
VERSION = os.environ.get("META_API_VERSION", "v21.0")
BASE = f"https://graph.facebook.com/{VERSION}"


class MetaError(RuntimeError):
    pass


def account() -> str:
    if not _ACCOUNT:
        raise MetaError("META_AD_ACCOUNT_ID not set in .env")
    return _ACCOUNT if _ACCOUNT.startswith("act_") else f"act_{_ACCOUNT}"


@lru_cache(maxsize=1)
def account_currency() -> str:
    """The ad account's billing currency ISO code (e.g. 'DKK'). All spend/CPL figures
    are in this — never assume USD. Empty string if it can't be fetched."""
    try:
        return get(account(), {"fields": "currency"}).get("currency", "") or ""
    except Exception:
        return ""


def _check(r: requests.Response) -> dict:
    body = r.json() if r.content else {}
    if r.status_code >= 400 or (isinstance(body, dict) and "error" in body):
        err = body.get("error", {}) if isinstance(body, dict) else {}
        parts = [
            err.get("message") or str(body),
            err.get("error_user_title"),
            err.get("error_user_msg"),
        ]
        meta = {k: err[k] for k in ("code", "error_subcode", "type") if k in err}
        msg = " · ".join(str(p) for p in parts if p)
        hint = "  (set META_API_VERSION in .env)" if "version" in msg.lower() else ""
        raise MetaError(f"Meta API {r.status_code}: {msg}  {meta}{hint}")
    return body


def get(path: str, params: dict | None = None) -> dict:
    if not TOKEN:
        raise MetaError("META_ADS_TOKEN not set in .env")
    p = {"access_token": TOKEN, **(params or {})}
    return _check(requests.get(f"{BASE}/{path.lstrip('/')}", params=p, timeout=45))


def post(path: str, params: dict | None = None) -> dict:
    """Write call (needs ads_management). Used to pause ads/ad sets/campaigns."""
    if not TOKEN:
        raise MetaError("META_ADS_TOKEN not set in .env")
    p = {"access_token": TOKEN, **(params or {})}
    return _check(requests.post(f"{BASE}/{path.lstrip('/')}", data=p, timeout=45))


def paginate(first: dict) -> list[dict]:
    """Follow `paging.next` (full URLs, token already embedded) to the end."""
    data = list(first.get("data", []))
    nxt = first.get("paging", {}).get("next")
    while nxt:
        body = _check(requests.get(nxt, timeout=45))
        data.extend(body.get("data", []))
        nxt = body.get("paging", {}).get("next")
    return data


def utm_from_url_tags(url_tags: str | None) -> dict[str, str]:
    """Parse a creative's `url_tags` (e.g. 'utm_source=meta&utm_content=news_briefing')."""
    if not url_tags:
        return {}
    return {k: v[0] for k, v in parse_qs(url_tags).items() if v}
