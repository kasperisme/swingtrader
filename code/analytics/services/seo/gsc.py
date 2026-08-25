"""Search Console writes — sitemap (re)submission.

`services.google_analytics.client` is deliberately read-only. Submitting a
sitemap needs the read-write scope, so it gets its own credential here rather
than widening the one every read path shares. The service account must be a
full user or owner on the property (it is: `siteFullUser`).
"""

from __future__ import annotations

from functools import lru_cache

from services.google_analytics.client import _credentials, site_url

_GSC_WRITE_SCOPE = "https://www.googleapis.com/auth/webmasters"


@lru_cache(maxsize=1)
def _write_client():
    from googleapiclient.discovery import build

    creds = _credentials()
    # Same service account, one extra scope — only for the write path.
    scoped = creds.with_scopes([*creds.scopes, _GSC_WRITE_SCOPE])
    return build("searchconsole", "v1", credentials=scoped, cache_discovery=False)


def list_sitemaps() -> list[dict]:
    svc = _write_client()
    res = svc.sitemaps().list(siteUrl=site_url()).execute()
    return res.get("sitemap", [])


def submit_sitemap(feedpath: str) -> None:
    """(Re)submit a sitemap. Idempotent — resubmitting nudges a re-read."""
    _write_client().sitemaps().submit(
        siteUrl=site_url(), feedpath=feedpath
    ).execute()


def delete_sitemap(feedpath: str) -> None:
    """Drop a stale entry — e.g. the apex-host sitemap that only redirects."""
    _write_client().sitemaps().delete(
        siteUrl=site_url(), feedpath=feedpath
    ).execute()
