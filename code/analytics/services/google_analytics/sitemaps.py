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

import re
import urllib.request
from datetime import datetime, timedelta, timezone
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


# ── Reading the sitemap itself ──────────────────────────────────────────────
#
# "What is new?" is answered from the sitemap's own <lastmod>, which is why
# code/ui/app/sitemap.ts only emits a lastmod it can stand behind: a URL with
# none is never treated as new, and one stamped with the request time would
# make every URL look new on every run.

_URL_BLOCK = re.compile(r"<url>(.*?)</url>", re.S)
_LOC = re.compile(r"<loc>\s*([^<]+?)\s*</loc>")
_LASTMOD = re.compile(r"<lastmod>\s*([^<]+?)\s*</lastmod>")


def _parse_lastmod(raw: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def entries(sitemap_url: str = DEFAULT_SITEMAP) -> list[tuple[str, datetime | None]]:
    """(loc, lastmod) for every <url> in the sitemap, in sitemap order."""
    with urllib.request.urlopen(sitemap_url, timeout=60) as resp:
        xml = resp.read().decode("utf-8", "replace")
    out: list[tuple[str, datetime | None]] = []
    for block in _URL_BLOCK.findall(xml):
        loc = _LOC.search(block)
        if not loc:
            continue
        lm = _LASTMOD.search(block)
        out.append((loc.group(1).replace("&amp;", "&"),
                    _parse_lastmod(lm.group(1)) if lm else None))
    return out


def parse_since(spec: str) -> timedelta:
    """'90m' / '24h' / '7d' → timedelta."""
    m = re.fullmatch(r"\s*(\d+)\s*([mhd])\s*", spec or "")
    if not m:
        raise ValueError(f"bad duration {spec!r} — use e.g. 90m, 24h, 7d")
    n, unit = int(m.group(1)), m.group(2)
    return {"m": timedelta(minutes=n), "h": timedelta(hours=n), "d": timedelta(days=n)}[unit]


def changed_since(since: timedelta, sitemap_url: str = DEFAULT_SITEMAP) -> list[str]:
    """URLs whose <lastmod> falls inside the window, newest first."""
    cutoff = datetime.now(timezone.utc) - since
    fresh = [(loc, lm) for loc, lm in entries(sitemap_url) if lm and lm >= cutoff]
    fresh.sort(key=lambda e: e[1], reverse=True)
    return [loc for loc, _ in fresh]
