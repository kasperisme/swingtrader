"""CLI — Google Analytics (GA4) + Search Console insight for the site.

    cd code/analytics
    .venv/bin/python -m services.google_analytics.cli verify         # check creds + access
    .venv/bin/python -m services.google_analytics.cli summary --days 28
    .venv/bin/python -m services.google_analytics.cli channels       # acquisition (GA4)
    .venv/bin/python -m services.google_analytics.cli landing        # landing pages (GA4)
    .venv/bin/python -m services.google_analytics.cli conversions    # key events (GA4)
    .venv/bin/python -m services.google_analytics.cli queries        # search queries (GSC)
    .venv/bin/python -m services.google_analytics.cli sc-pages       # search pages (GSC)
    .venv/bin/python -m services.google_analytics.cli opportunities  # striking-distance SEO wins
    .venv/bin/python -m services.google_analytics.cli sitemaps        # registered sitemaps + last fetch (GSC)
    .venv/bin/python -m services.google_analytics.cli resubmit-sitemap  # ask Google to re-download it
    .venv/bin/python -m services.google_analytics.cli inspect --since 24h   # which new URLs Google hasn't indexed
    .venv/bin/python -m services.google_analytics.cli inspect https://www.newsimpactscreener.com/quote/NVDA

Add --json to any data command for machine-readable output.
"""

from __future__ import annotations

import argparse
import json
import sys

from . import client as gc


def _table(rows, cols, widths, headers=None):
    if not rows:
        print("  (no rows)")
        return
    hdr = headers or cols
    print("  " + "".join(f"{h:<{w}}" if i == 0 else f"{h:>{w}}"
                          for i, (h, w) in enumerate(zip(hdr, widths))))
    for r in rows:
        line = ""
        for i, (c, w) in enumerate(zip(cols, widths)):
            v = r.get(c, "")
            if isinstance(v, float):
                v = f"{v:,.2f}" if abs(v) < 1000 else f"{int(v):,}"
            v = str(v)
            if i == 0:
                v = v[:w - 1]
                line += f"{v:<{w}}"
            else:
                line += f"{v:>{w}}"
        print("  " + line)


def cmd_verify(args) -> int:
    print("Google integration preflight\n" + "-" * 32)
    ok = True
    # 1) config
    try:
        pid = gc.property_id(); print(f"  ✓ GA4_PROPERTY_ID       {pid}")
    except gc.GoogleError as e:
        ok = False; print(f"  ✗ GA4 property          {e}")
    try:
        su = gc.site_url(); print(f"  ✓ GSC_SITE_URL          {su}")
    except gc.GoogleError as e:
        ok = False; print(f"  ✗ Search Console site   {e}")
    # 2) credentials load
    try:
        email = gc.service_account_email()
        print(f"  ✓ service account       {email or '(loaded)'}")
    except gc.GoogleError as e:
        print(f"  ✗ credentials           {e}")
        print("\n  Fix the above, then re-run `verify`.")
        return 1
    # 3) live access checks
    try:
        from . import ga4
        s = ga4.summary(7)
        print(f"  ✓ GA4 Data API          reachable ({int(s.get('sessions', 0))} sessions/7d)")
    except Exception as e:
        ok = False
        print(f"  ✗ GA4 Data API          {type(e).__name__}: {str(e)[:120]}")
        print("      → GA Admin → Property Access Management → add the service-account email as Viewer,")
        print("        and enable 'Google Analytics Data API' in the Cloud project.")
    try:
        from . import search_console as sc
        s = sc.summary(7)
        print(f"  ✓ Search Console API     reachable ({int(s.get('clicks', 0))} clicks/7d)")
    except Exception as e:
        ok = False
        print(f"  ✗ Search Console API     {type(e).__name__}: {str(e)[:120]}")
        print("      → Search Console → Settings → Users and permissions → add the service-account")
        print("        email (Full/Restricted), and enable 'Google Search Console API' in the Cloud project.")
    print("\n" + ("  All green — you're connected." if ok else "  Some gates failed (see fixes above)."))
    return 0 if ok else 1


def cmd_discover(args) -> int:
    from . import discover
    print("GA4 properties the service account can access:")
    try:
        props = discover.ga4_properties()
        if props:
            for p in props:
                print(f"  · {p['property_name']:<32} GA4_PROPERTY_ID={p['property_id']}  ({p['account']})")
        else:
            print("  (none — grant the service-account email Viewer on the GA4 property)")
    except Exception as e:
        print(f"  ✗ {type(e).__name__}: {str(e)[:140]}")
        print("    (enable the 'Google Analytics Admin API' too, or just set GA4_PROPERTY_ID by hand.)")
    print("\nSearch Console sites the service account can access:")
    try:
        sites = discover.gsc_sites()
        if sites:
            for s in sites:
                print(f"  · {s['site_url']:<44} ({s['permission']})   GSC_SITE_URL={s['site_url']}")
        else:
            print("  (none — add the service-account email as a user in Search Console)")
    except Exception as e:
        print(f"  ✗ {type(e).__name__}: {str(e)[:140]}")
    return 0


def _emit(rows, args, cols, widths, headers=None):
    if getattr(args, "json", False):
        print(json.dumps(rows, indent=2))
    else:
        _table(rows, cols, widths, headers)


def cmd_summary(args) -> int:
    from . import ga4
    g = ga4.summary(args.days)
    s, sc_ok, sc_err = {}, False, ""
    try:
        from . import search_console as sc_mod
        s = sc_mod.summary(args.days); sc_ok = True
    except Exception as e:
        sc_err = "API not enabled yet" if ("has not been used" in str(e) or "is disabled" in str(e)) \
                 else f"{type(e).__name__}"
    if args.json:
        print(json.dumps({"ga4": g, "search_console": s or {"error": sc_err}}, indent=2)); return 0
    print(f"\nGA4 (last {args.days}d):")
    print(f"  sessions {int(g.get('sessions',0)):,} · users {int(g.get('totalUsers',0)):,} · "
          f"new {int(g.get('newUsers',0)):,} · views {int(g.get('screenPageViews',0)):,} · "
          f"engagement {g.get('engagementRate',0):.1%} · conversions {int(g.get('conversions',0)):,}")
    if sc_ok:
        print(f"Search Console (last {args.days}d, ends ~2d ago):")
        print(f"  clicks {int(s.get('clicks',0)):,} · impressions {int(s.get('impressions',0)):,} · "
              f"CTR {s.get('ctr',0):.2f}% · avg position {s.get('position',0):.1f}")
    else:
        print(f"Search Console: {sc_err} — enable the Search Console API to see organic search.")
    return 0


def _as_pct(rows, key="engagementRate"):
    for r in rows:
        if isinstance(r.get(key), (int, float)):
            r[key] = round(r[key] * 100, 1)      # GA4 ratio 0-1 → percent
    return rows


def cmd_channels(args) -> int:
    from . import ga4
    _emit(_as_pct(ga4.channels(args.days)), args,
          ["sessionDefaultChannelGroup", "sessions", "totalUsers", "engagementRate", "conversions"],
          [22, 10, 10, 14, 12], ["channel", "sessions", "users", "engagement%", "conv"])
    return 0


def cmd_landing(args) -> int:
    from . import ga4
    _emit(_as_pct(ga4.landing_pages(args.days, args.limit)), args,
          ["landingPagePlusQueryString", "sessions", "engagementRate", "conversions"],
          [46, 10, 14, 12], ["landing page", "sessions", "engagement%", "conv"])
    return 0


def cmd_conversions(args) -> int:
    from . import ga4
    _emit(ga4.conversions(args.days, args.limit), args,
          ["eventName", "conversions", "eventCount"], [30, 12, 12],
          ["event", "conversions", "count"])
    return 0


def cmd_queries(args) -> int:
    from . import search_console as sc
    _emit(sc.queries(args.days, args.limit), args,
          ["query", "clicks", "impressions", "ctr", "position"],
          [40, 8, 12, 8, 10], ["query", "clicks", "impr", "CTR%", "pos"])
    return 0


def cmd_sc_pages(args) -> int:
    from . import search_console as sc
    _emit(sc.pages(args.days, args.limit), args,
          ["page", "clicks", "impressions", "ctr", "position"],
          [50, 8, 12, 8, 10], ["page", "clicks", "impr", "CTR%", "pos"])
    return 0


def cmd_opportunities(args) -> int:
    from . import search_console as sc
    rows = sc.opportunities(args.days, args.min_impr, args.limit)
    _emit(rows, args,
          ["query", "page", "impressions", "ctr", "position", "lost_clicks_est"],
          [30, 34, 10, 8, 8, 10],
          ["query", "page", "impr", "CTR%", "pos", "~lost/mo"])
    if not args.json:
        print("\n  Striking distance: real search demand, ranking p1-2, losing clicks to CTR.")
        print("  Rewrite the title/meta on the top rows first — fastest organic wins.")
    return 0


def cmd_sitemaps(args) -> int:
    from . import sitemaps as sm
    rows = sm.list_sitemaps()
    if args.json:
        print(json.dumps(rows, indent=2)); return 0
    print(f"Search Console sitemaps — {gc.site_url()}  ({sm.permission_level()})\n" + "-" * 60)
    if not rows:
        print("  (none registered)"); return 0
    for e in rows:
        c = (e.get("contents") or [{}])[0]
        print(f"  {e.get('path')}")
        print(f"    last submitted   {e.get('lastSubmitted', '-')}")
        print(f"    last downloaded  {e.get('lastDownloaded', '-')}")
        print(f"    urls (at last download) {c.get('submitted', '-')}"
              f"   errors {e.get('errors', '-')}  warnings {e.get('warnings', '-')}")
        if e.get("isPending"):
            print("    status           PENDING — Google has not processed the submit yet")
    return 0


def cmd_resubmit_sitemap(args) -> int:
    """Force Google to re-download the sitemap.

    Reports the before/after `lastDownloaded` because that — not the submit call
    returning 200 — is the only evidence Google actually re-fetched anything.
    """
    from . import sitemaps as sm
    path = args.path or sm.DEFAULT_SITEMAP
    level = sm.permission_level()
    print(f"Property   {gc.site_url()}  ({level})")
    print(f"Sitemap    {path}")
    if level not in ("siteOwner", "siteFullUser"):
        print(f"\n  ✗ Permission '{level}' cannot submit sitemaps. The service account "
              f"({gc.service_account_email()}) needs Full or Owner in Search Console.",
              file=sys.stderr)
        return 1

    before = sm.get(path) or {}
    print(f"Before     downloaded {before.get('lastDownloaded', 'never')} "
          f"({(before.get('contents') or [{}])[0].get('submitted', '?')} urls)")
    if args.dry_run:
        print("\n  dry run — not submitting."); return 0

    sm.submit(path)
    after = sm.get(path) or {}
    print(f"After      submitted  {after.get('lastSubmitted', '-')}")
    print(f"           downloaded {after.get('lastDownloaded', 'never')}")
    print("\n  ✓ Submitted. Google re-downloads on its own schedule (minutes to a day);")
    print("    re-run `sitemaps` and watch `last downloaded` move to confirm.")
    print("    A resubmit refreshes the URL LIST — it does not force per-page indexing.")
    return 0


_BUCKET_ORDER = ("request", "fix", "quality", "error", "indexed")


def cmd_inspect(args) -> int:
    """Triage new URLs through the URL Inspection API.

    Cannot request indexing (no public API does). Prints the short list worth
    spending the GSC UI's ~10 daily manual requests on, each with a deep link.
    """
    from . import sitemaps as sm
    from . import url_inspection as ui

    if args.urls:
        urls = list(dict.fromkeys(args.urls))
        origin = "given"
    else:
        try:
            window = sm.parse_since(args.since)
        except ValueError as e:
            print(f"  ✗ {e}", file=sys.stderr); return 2
        urls = sm.changed_since(window, args.sitemap or sm.DEFAULT_SITEMAP)
        origin = f"sitemap lastmod within {args.since}"
    if args.match:
        urls = [u for u in urls if args.match in u]
    urls = urls[: args.limit]
    if not urls:
        print(f"  no URLs to inspect ({origin}{', matching ' + args.match if args.match else ''})")
        return 0

    if not args.json:
        print(f"Inspecting {len(urls)} URL(s) — {origin}. Quota 2,000/day per property.\n")

    def _progress(i, n, row):
        if not args.json:
            print(f"  [{i:>3}/{n}] {row['bucket']:<8} {row['url']}", flush=True)

    rows = ui.inspect_many(urls, progress=_progress)
    if args.json:
        print(json.dumps(rows, indent=2)); return 0

    by = {b: [r for r in rows if r["bucket"] == b] for b in _BUCKET_ORDER}
    print("\n" + "  ".join(f"{b} {len(by[b])}" for b in _BUCKET_ORDER))

    if by["request"]:
        print("\nRequest indexing by hand — uncrawled, or last crawled before a fix (UI allows ~10/day):")
        for r in by["request"]:
            print(f"  · {r['url']}\n      {r['reason']}\n      {r['gsc_link']}")
    if by["fix"]:
        print("\nFix first — a request can't help until the cause is gone:")
        for r in by["fix"]:
            print(f"  · {r['url']}\n      {r['reason']}")
    if by["quality"]:
        print("\nCrawled, not indexed — Google declined; improve the page, don't re-request:")
        for r in by["quality"]:
            print(f"  · {r['url']}  (last crawl {r.get('last_crawl') or '?'})")
    if by["error"]:
        print("\nErrors:")
        for r in by["error"]:
            print(f"  · {r['url']}\n      {r['error']}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(prog="google_analytics", description="GA4 + Search Console insight.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def _common(p, limit_default=25):
        p.add_argument("--days", type=int, default=28)
        p.add_argument("--limit", type=int, default=limit_default)
        p.add_argument("--json", action="store_true")

    sub.add_parser("verify").set_defaults(func=cmd_verify)
    sub.add_parser("discover").set_defaults(func=cmd_discover)
    p = sub.add_parser("summary"); p.add_argument("--days", type=int, default=28); p.add_argument("--json", action="store_true"); p.set_defaults(func=cmd_summary)
    p = sub.add_parser("channels"); _common(p); p.set_defaults(func=cmd_channels)
    p = sub.add_parser("landing"); _common(p); p.set_defaults(func=cmd_landing)
    p = sub.add_parser("conversions"); _common(p); p.set_defaults(func=cmd_conversions)
    p = sub.add_parser("queries"); _common(p, 50); p.set_defaults(func=cmd_queries)
    p = sub.add_parser("sc-pages"); _common(p, 50); p.set_defaults(func=cmd_sc_pages)
    p = sub.add_parser("opportunities"); _common(p, 30); p.add_argument("--min-impr", type=float, default=100.0, dest="min_impr"); p.set_defaults(func=cmd_opportunities)
    p = sub.add_parser("sitemaps"); p.add_argument("--json", action="store_true"); p.set_defaults(func=cmd_sitemaps)
    p = sub.add_parser("resubmit-sitemap")
    p.add_argument("--path", default=None, help="sitemap URL (default: the canonical www sitemap)")
    p.add_argument("--dry-run", action="store_true", dest="dry_run")
    p.set_defaults(func=cmd_resubmit_sitemap)
    p = sub.add_parser("inspect", help="URL Inspection triage for new URLs")
    p.add_argument("urls", nargs="*", help="URLs to inspect (default: recently-changed sitemap URLs)")
    p.add_argument("--since", default="7d", help="sitemap lastmod window when no URLs are given (90m/24h/7d)")
    p.add_argument("--sitemap", default=None, help="sitemap URL (default: the canonical www sitemap)")
    p.add_argument("--match", default=None, help="only URLs containing this substring, e.g. /articles/")
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_inspect)

    args = ap.parse_args()
    try:
        return args.func(args)
    except gc.GoogleError as e:
        print(f"config error: {e}", file=sys.stderr); return 1


if __name__ == "__main__":
    raise SystemExit(main())
