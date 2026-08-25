"""CLI — post-deploy search push.

    .venv/bin/python -m services.seo.cli sitemaps
    .venv/bin/python -m services.seo.cli submit-sitemap
    .venv/bin/python -m services.seo.cli drop-sitemap --url https://newsimpactscreener.com/sitemap.xml
    .venv/bin/python -m services.seo.cli indexnow --limit 500 [--dry-run]
"""

from __future__ import annotations

import argparse
import sys

from services.seo import gsc, indexnow

DEFAULT_SITEMAP = "https://www.newsimpactscreener.com/sitemap.xml"


def cmd_sitemaps(_args) -> int:
    rows = gsc.list_sitemaps()
    if not rows:
        print("  no sitemaps submitted")
        return 0
    for r in rows:
        counts = r.get("contents") or [{}]
        submitted = counts[0].get("submitted", "?")
        indexed = counts[0].get("indexed", "?")
        print(f"  {r['path']}")
        print(f"     submitted={submitted}  indexed={indexed}  "
              f"errors={r.get('errors', '?')}  warnings={r.get('warnings', '?')}")
        print(f"     lastSubmitted={r.get('lastSubmitted')}  "
              f"lastDownloaded={r.get('lastDownloaded')}")
    return 0


def cmd_submit_sitemap(args) -> int:
    gsc.submit_sitemap(args.url)
    print(f"  ✓ submitted {args.url}")
    return 0


def cmd_drop_sitemap(args) -> int:
    gsc.delete_sitemap(args.url)
    print(f"  ✓ removed {args.url}")
    return 0


def cmd_indexnow(args) -> int:
    urls = indexnow.urls_from_sitemap(args.sitemap, limit=args.limit)
    if not urls:
        print("  sitemap returned no URLs")
        return 1
    res = indexnow.submit(urls, dry_run=args.dry_run)
    print(f"  submitted={res['submitted']}  status={res['status']}")
    if res.get("error"):
        print(f"  error: {res['error']}")
        return 1
    for u in res.get("sample", []):
        print(f"     {u}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(prog="services.seo.cli")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("sitemaps").set_defaults(func=cmd_sitemaps)

    p = sub.add_parser("submit-sitemap")
    p.add_argument("--url", default=DEFAULT_SITEMAP)
    p.set_defaults(func=cmd_submit_sitemap)

    p = sub.add_parser("drop-sitemap")
    p.add_argument("--url", required=True)
    p.set_defaults(func=cmd_drop_sitemap)

    p = sub.add_parser("indexnow")
    p.add_argument("--sitemap", default=DEFAULT_SITEMAP)
    # Default to the freshest slice — the sitemap leads with the hubs and the
    # newest articles, and a 6.7k-URL blast every deploy is noise.
    p.add_argument("--limit", type=int, default=500)
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_indexnow)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
