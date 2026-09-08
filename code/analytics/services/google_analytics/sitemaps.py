"""sitemaps.py — read sitemap status and force Google to re-fetch it.

Re-submitting a sitemap through the Search Console API is the only supported way
left to *ask* Google to re-crawl it: the old `google.com/ping?sitemap=` endpoint
was retired in 2023 and now 404s. It is a request, not a command — Google
re-downloads on its own schedule, typically within minutes to a day.

What it does NOT do: re-index the pages. A submit refreshes Google's copy of the
URL LIST; whether each URL then gets crawled and indexed is decided per-URL by
the usual signals. So a resubmit is the right move after the sitemap's CONTENTS
change (new sections, a different URL set, a host change) and useless as a
remedy for "crawled - currently not indexed".

Two caveats on the numbers the API reports back:

  * `contents[].submitted` is from the last download, so right after a submit it
    still shows the OLD count until Google actually re-fetches. Compare
    `lastDownloaded` before/after — that is the field that proves a re-fetch.
  * `contents[].indexed` is a long-dead legacy field. It reports 0 for
    essentially every property and says nothing about real indexing; use the
    Index coverage report / URL Inspection for that.

Requires the full `webmasters` scope (see `client.gsc_write_client`) and a
Search Console permission level of Full or Owner.
"""

from __future__ import annotations

from typing import Any

from . import client as gc

# The sitemap Next.js serves. Must be the CANONICAL host — submitting the apex
# while every page canonicalises to `www` is how you end up with a sitemap of
# redirects (which is exactly what this property did before the SEO pass).
DEFAULT_SITEMAP = "https://www.newsimpactscreener.com/sitemap.xml"


def permission_level(site: str | None = None) -> str | None:
    """Search Console permission for the configured property, e.g. siteFullUser."""
    su = site or gc.site_url()
    for entry in gc.gsc_client().sites().list().execute().get("siteEntry", []):
        if entry.get("siteUrl") == su:
            return entry.get("permissionLevel")
    return None


def list_sitemaps(site: str | None = None) -> list[dict[str, Any]]:
    su = site or gc.site_url()
    resp = gc.gsc_client().sitemaps().list(siteUrl=su).execute()
    return resp.get("sitemap", [])


def get(path: str = DEFAULT_SITEMAP, site: str | None = None) -> dict[str, Any] | None:
    su = site or gc.site_url()
    try:
        return gc.gsc_client().sitemaps().get(siteUrl=su, feedpath=path).execute()
    except Exception:
        return None


def submit(path: str = DEFAULT_SITEMAP, site: str | None = None) -> None:
    """(Re-)submit the sitemap. Idempotent — resubmitting an already-registered
    sitemap is the documented way to nudge a re-download."""
    su = site or gc.site_url()
    gc.gsc_write_client().sitemaps().submit(siteUrl=su, feedpath=path).execute()
