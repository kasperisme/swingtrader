"""IndexNow — push changed URLs to Bing/Yandex/Seznam/Naver.

One POST notifies every participating engine. The key is verified by fetching
`https://<host>/<key>.txt`, which the Next app serves from `public/`; keep
INDEXNOW_KEY here in step with `code/ui/lib/site.ts`.
"""

from __future__ import annotations

import json
import os
import urllib.request
import urllib.error
from typing import Iterable

ENDPOINT = "https://api.indexnow.org/IndexNow"

# Per the spec a single submission carries at most 10,000 URLs.
MAX_URLS = 10_000


def _config() -> tuple[str, str]:
    # Same .env discovery every other service uses, so the CLI behaves the same
    # whichever directory it is run from.
    from services.google_analytics.client import _load_env

    _load_env()
    host = (os.environ.get("SITE_HOST") or "www.newsimpactscreener.com").strip()
    key = (os.environ.get("INDEXNOW_KEY") or "").strip()
    if not key:
        raise RuntimeError(
            "INDEXNOW_KEY not set. Copy it from code/ui/lib/site.ts into "
            "code/analytics/.env — it must match the key file served at "
            f"https://{host}/<key>.txt"
        )
    return host, key


def submit(urls: Iterable[str], *, dry_run: bool = False) -> dict:
    """Notify IndexNow that `urls` changed. Returns a small result dict."""
    host, key = _config()

    seen: list[str] = []
    for u in urls:
        u = u.strip()
        # The endpoint rejects the whole batch if any URL is off-host.
        if u.startswith(f"https://{host}/") or u == f"https://{host}":
            if u not in seen:
                seen.append(u)
        if len(seen) >= MAX_URLS:
            break

    if not seen:
        return {"submitted": 0, "status": None, "note": "no in-host URLs to submit"}

    payload = {
        "host": host,
        "key": key,
        "keyLocation": f"https://{host}/{key}.txt",
        "urlList": seen,
    }
    if dry_run:
        return {"submitted": len(seen), "status": "dry-run", "sample": seen[:5]}

    req = urllib.request.Request(
        ENDPOINT,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            status = resp.status
    except urllib.error.HTTPError as e:
        # 422 = key/host mismatch, 403 = key file not reachable. Both are
        # config errors worth surfacing verbatim rather than swallowing.
        return {
            "submitted": len(seen),
            "status": e.code,
            "error": e.read().decode("utf-8", "replace")[:500],
        }

    return {"submitted": len(seen), "status": status, "sample": seen[:5]}


def urls_from_sitemap(sitemap_url: str, limit: int = MAX_URLS) -> list[str]:
    """Pull <loc> values out of a sitemap. Freshest-first is preserved."""
    import re

    with urllib.request.urlopen(sitemap_url, timeout=60) as resp:
        xml = resp.read().decode("utf-8", "replace")
    return re.findall(r"<loc>([^<]+)</loc>", xml)[:limit]
