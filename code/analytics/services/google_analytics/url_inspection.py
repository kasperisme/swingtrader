"""url_inspection.py — ask Search Console what Google knows about specific URLs.

The URL Inspection API is the read half of the GSC inspector: verdict,
coverage state, last crawl, canonical. It CANNOT request indexing — there is no
public API for that button (the Indexing API is licensed for JobPosting and
livestream pages only, and using it for anything else is treated as spam).

So the job here is triage. Inspect the new URLs in bulk, and sort them into:

  indexed   nothing to do
  request   Google has not crawled it yet ("URL is unknown", "Discovered -
            currently not indexed"), or its last crawl saw a canonical tag the
            live page no longer has. These are the few worth clicking "Request
            indexing" on by hand — the UI allows roughly 10 a day per property,
            so spend them here.
  quality   "Crawled - currently not indexed". Google fetched it and declined.
            Re-requesting does not change that verdict; the page has to.
  fix       robots-blocked, noindex, fetch failure, a canonical pointing
            elsewhere, or Google treating it as a duplicate. A request cannot
            help until the cause is fixed.

Quota: 2,000 inspections/day and 600/minute per property. Read-only scope.
"""

from __future__ import annotations

import re
import urllib.request
from typing import Any

from . import client as gc

# coverageState strings are English prose, not an enum — match on stable stems.
_NOT_CRAWLED = ("unknown to google", "discovered - currently not indexed")
_CRAWLED_NOT_INDEXED = "crawled - currently not indexed"
_CANONICAL = re.compile(r'<link[^>]+rel="canonical"[^>]+href="([^"]+)"', re.I)


def inspect(url: str, site: str | None = None) -> dict[str, Any]:
    """One URL → a flat row. Errors come back as a row, not an exception, so a
    single out-of-property URL cannot sink a batch."""
    su = site or gc.site_url()
    try:
        resp = gc.gsc_client().urlInspection().index().inspect(
            body={"inspectionUrl": url, "siteUrl": su, "languageCode": "en-US"}
        ).execute()
    except Exception as e:  # HttpError for quota / URL outside the property
        return {"url": url, "bucket": "error", "error": f"{type(e).__name__}: {str(e)[:200]}"}

    result = resp.get("inspectionResult", {}) or {}
    idx = result.get("indexStatusResult", {}) or {}
    row = {
        "url": url,
        "verdict": idx.get("verdict"),
        "coverage": idx.get("coverageState"),
        "last_crawl": idx.get("lastCrawlTime"),
        "robots": idx.get("robotsTxtState"),
        "indexing": idx.get("indexingState"),
        "fetch": idx.get("pageFetchState"),
        "google_canonical": idx.get("googleCanonical"),
        "user_canonical": idx.get("userCanonical"),
        "in_sitemaps": idx.get("sitemap") or [],
        "referring_urls": idx.get("referringUrls") or [],
        # Deep link to this URL in the GSC inspector — where the manual
        # "Request indexing" button lives.
        "gsc_link": result.get("inspectionResultLink"),
    }
    row["bucket"], row["reason"] = classify(row)
    return row


def _norm(url: str) -> str:
    return url.strip().rstrip("/")


def _live_canonical(url: str) -> str | None:
    """The canonical the page declares right now (None if unreachable)."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "nis-url-inspection/1.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            html = resp.read(400_000).decode("utf-8", "replace")
    except Exception:
        return None
    m = _CANONICAL.search(html)
    return m.group(1) if m else None


def _known(state: str | None) -> str | None:
    """`*_UNSPECIFIED` means Google has no crawl data yet — not a failure. Every
    never-crawled URL reports it for robots, indexing AND fetch."""
    return None if not state or state.endswith("_UNSPECIFIED") else state


def classify(row: dict[str, Any]) -> tuple[str, str]:
    coverage = (row.get("coverage") or "").lower()
    if row.get("verdict") == "PASS":
        return "indexed", row.get("coverage") or "indexed"
    if _known(row.get("robots")) == "DISALLOWED":
        return "fix", "blocked by robots.txt"
    indexing = _known(row.get("indexing"))
    if indexing and indexing != "INDEXING_ALLOWED":
        return "fix", f"indexing not allowed ({indexing})"
    fetch = _known(row.get("fetch"))
    if fetch and fetch != "SUCCESSFUL":
        return "fix", f"fetch failed ({fetch})"
    gcan, ucan = row.get("google_canonical"), row.get("user_canonical")
    if gcan and ucan and _norm(gcan) != _norm(ucan):
        # Two different problems share this shape. If the page (as last
        # crawled) declared some OTHER url canonical, it may since have been
        # fixed — the live tag decides whether a recrawl is all it needs.
        # If it declared itself and Google still picked another, Google sees
        # it as a duplicate of `gcan`, and no request changes that.
        crawled = (row.get("last_crawl") or "?")[:10]
        if _norm(ucan) != _norm(row["url"]):
            live = _live_canonical(row["url"])
            if live and _norm(live) == _norm(row["url"]):
                return "request", (f"stale crawl ({crawled}) saw canonical → {ucan}; "
                                   f"live page is fixed, a recrawl picks it up")
            return "fix", f"page declares canonical → {live or ucan} (crawled {crawled})"
        return "fix", f"Google treats it as a duplicate of {gcan}"
    if any(stem in coverage for stem in _NOT_CRAWLED):
        return "request", row.get("coverage") or "not crawled"
    if _CRAWLED_NOT_INDEXED in coverage:
        return "quality", row.get("coverage")
    return "request", row.get("coverage") or "not indexed"


def inspect_many(urls: list[str], site: str | None = None, progress=None) -> list[dict[str, Any]]:
    su = site or gc.site_url()
    rows = []
    for i, url in enumerate(urls, 1):
        rows.append(inspect(url, su))
        if progress:
            progress(i, len(urls), rows[-1])
    return rows
