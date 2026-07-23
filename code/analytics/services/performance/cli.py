"""CLI — the unified performance foundation.

    cd code/analytics
    .venv/bin/python -m services.performance.cli status              # which platforms are wired/reachable
    .venv/bin/python -m services.performance.cli snapshot --days 28  # build + write the foundation
    .venv/bin/python -m services.performance.cli snapshot --json     # emit the raw JSON to stdout

`snapshot` writes output/performance/<date>/snapshot.{json,md}. The JSON is the
data foundation the action skills consume; the MD is the analyst digest.
"""

from __future__ import annotations

import argparse
import json

from . import snapshot as snap
from . import sources


def cmd_status(_args) -> int:
    print("Platform wiring\n" + "-" * 24)
    checks = {
        "GA4 Data API": lambda: sources.ga4_block(1),
        "Search Console": lambda: sources.gsc_block(1),
        "Meta Ads": lambda: sources.meta_block(snap._since(1)),
        "Supabase leads": lambda: sources.leads_block(snap._since(1)),
        "PostHog": sources.posthog_block,
    }
    all_ok = True
    for name, fn in checks.items():
        b = fn()
        if b.get("available"):
            print(f"  ✓ {name}")
        else:
            all_ok = False
            print(f"  ✗ {name}: {b.get('error', 'unavailable')[:90]}")
    print("\n" + ("  All platforms reachable." if all_ok
                  else "  Some platforms not wired (snapshot degrades gracefully — it uses what's live)."))
    return 0


def cmd_snapshot(args) -> int:
    s = snap.build_snapshot(args.days)
    if args.json:
        print(json.dumps(s, indent=2))
        return 0
    out = snap.write(s)
    print(snap.to_markdown(s))
    print(f"\n→ wrote {out / 'snapshot.json'}")
    print(f"→ wrote {out / 'snapshot.md'}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(prog="performance", description="Unified cross-platform performance foundation.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status").set_defaults(func=cmd_status)
    p = sub.add_parser("snapshot")
    p.add_argument("--days", type=int, default=28)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_snapshot)
    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
