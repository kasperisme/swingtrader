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

    args = ap.parse_args()
    try:
        return args.func(args)
    except gc.GoogleError as e:
        print(f"config error: {e}", file=sys.stderr); return 1


if __name__ == "__main__":
    raise SystemExit(main())
