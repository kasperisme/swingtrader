"""client.py — service-account auth + config for the GA4 Data API and the
Search Console API.

Credentials (in code/analytics/.env, gitignored):
  GA4_PROPERTY_ID=123456789                       # numeric property id (GA Admin → Property Settings)
  GSC_SITE_URL=sc-domain:newsimpactscreener.com   # Search Console property
  GOOGLE_APPLICATION_CREDENTIALS=/abs/path/sa.json # service-account JSON key …
  # …or inline it instead (handy for Vercel/CI):
  GOOGLE_SERVICE_ACCOUNT_JSON={"type":"service_account",...}   # raw or base64

The same service account must be granted **Viewer** on the GA4 property and added
as a **user** in Search Console. Read-only scopes only.
"""

from __future__ import annotations

import base64
import json
import os
import pathlib
from functools import lru_cache

_GA4_SCOPE = "https://www.googleapis.com/auth/analytics.readonly"
_GSC_SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"


class GoogleError(RuntimeError):
    """Config/auth error with a human fix."""


def _load_env() -> None:
    """Best-effort .env load so CLI usage mirrors the other services."""
    try:
        from dotenv import load_dotenv
    except Exception:
        return
    here = pathlib.Path(__file__).resolve()
    for parent in here.parents:
        env = parent / ".env"
        if env.exists():
            load_dotenv(env)
            return


def property_id() -> str:
    _load_env()
    pid = (os.environ.get("GA4_PROPERTY_ID") or "").strip().lstrip("properties/")
    if not pid:
        raise GoogleError("GA4_PROPERTY_ID not set in .env (the NUMERIC property id from "
                          "GA Admin → Property Settings — not the G-… measurement id).")
    return pid


def site_url() -> str:
    _load_env()
    su = (os.environ.get("GSC_SITE_URL") or "").strip()
    if not su:
        raise GoogleError("GSC_SITE_URL not set in .env (e.g. sc-domain:newsimpactscreener.com "
                          "for a Domain property, or the exact https URL for a URL-prefix property).")
    return su


@lru_cache(maxsize=1)
def _credentials():
    _load_env()
    from google.oauth2 import service_account

    scopes = [_GA4_SCOPE, _GSC_SCOPE]
    inline = (os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON") or "").strip()
    if inline:
        try:
            raw = inline if inline.startswith("{") else base64.b64decode(inline).decode("utf-8")
            info = json.loads(raw)
        except Exception as e:
            raise GoogleError(f"GOOGLE_SERVICE_ACCOUNT_JSON is set but not valid JSON/base64: {e}")
        return service_account.Credentials.from_service_account_info(info, scopes=scopes)

    path = (os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") or "").strip()
    if not path:
        raise GoogleError("No service-account credentials found. Set GOOGLE_APPLICATION_CREDENTIALS "
                          "to the JSON key path, or GOOGLE_SERVICE_ACCOUNT_JSON to the inline key.")
    if not pathlib.Path(path).exists():
        raise GoogleError(f"GOOGLE_APPLICATION_CREDENTIALS points to a missing file: {path}")
    return service_account.Credentials.from_service_account_file(path, scopes=scopes)


def service_account_email() -> str | None:
    try:
        return getattr(_credentials(), "service_account_email", None)
    except Exception:
        return None


@lru_cache(maxsize=1)
def ga4_client():
    """GA4 Data API (v1beta) client."""
    from google.analytics.data_v1beta import BetaAnalyticsDataClient
    return BetaAnalyticsDataClient(credentials=_credentials())


@lru_cache(maxsize=1)
def gsc_client():
    """Search Console API (v3) client."""
    from googleapiclient.discovery import build
    return build("searchconsole", "v1", credentials=_credentials(), cache_discovery=False)
