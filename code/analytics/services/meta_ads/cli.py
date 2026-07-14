"""Read Meta ad performance and tie it to the feature A/B.

    python -m services.meta_ads.cli verify
    python -m services.meta_ads.cli insights [--since 2026-06-11]
    python -m services.meta_ads.cli reconcile [--since 2026-06-11]

`insights` rolls CTR / CPC / spend / Meta-attributed Leads up by utm_content
(the feature). `reconcile` puts Meta spend + clicks next to the REAL email leads
in Supabase — so you see cost-per-actual-lead per feature, both sides of the loop.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta

from . import client
from .client import MetaError

_LEAD_KEYS = ("lead",)  # any action_type containing this = a Lead conversion


def _num(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _leads(actions) -> float:
    total = 0.0
    for a in actions or []:
        if any(k in a.get("action_type", "") for k in _LEAD_KEYS):
            total += _num(a.get("value"))
    return total


def _time_range(since: str | None) -> dict:
    until = date.today().isoformat()
    start = since or (date.today() - timedelta(days=30)).isoformat()
    return {"since": start, "until": until}


def _ad_utm_map() -> dict[str, str]:
    """ad_id → utm_content, parsed from each ad's creative url_tags."""
    ads = client.paginate(
        client.get(f"{client.account()}/ads",
                   {"fields": "id,name,creative{url_tags}", "limit": 200})
    )
    out = {}
    for a in ads:
        tags = (a.get("creative") or {}).get("url_tags")
        out[a["id"]] = client.utm_from_url_tags(tags).get("utm_content", "—")
    return out


def _ad_insights(since: str | None) -> list[dict]:
    return client.paginate(client.get(
        f"{client.account()}/insights",
        {"level": "ad",
         "fields": "ad_id,ad_name,impressions,clicks,ctr,cpc,spend,actions",
         "time_range": json.dumps(_time_range(since)),
         "limit": 200},
    ))


def cmd_verify(_args) -> int:
    acc = client.get(client.account(),
                     {"fields": "name,account_status,currency,amount_spent"})
    print(f"✓ connected: {acc.get('name')}  ({client.account()})")
    print(f"  status={acc.get('account_status')}  currency={acc.get('currency')}  "
          f"lifetime spend={acc.get('amount_spent')}")
    return 0


def cmd_insights(args) -> int:
    rows = _ad_insights(args.since)
    if not rows:
        print("No ad insights in that window (no delivery yet?).")
        return 0
    utm = _ad_utm_map()
    print(f"\nPer ad — since {_time_range(args.since)['since']}:\n")
    print(f"  {'ad':<34}{'feat':<18}{'spend':>9}{'impr':>9}{'clicks':>8}{'CTR%':>7}{'CPC':>7}{'leads':>7}{'/lead':>8}")
    roll: dict[str, dict] = {}
    for r in rows:
        feat = utm.get(r.get("ad_id"), "—")
        spend, clicks, leads = _num(r.get("spend")), _num(r.get("clicks")), _leads(r.get("actions"))
        cpl = spend / leads if leads else 0
        print(f"  {(r.get('ad_name') or '')[:32]:<34}{feat[:16]:<18}{spend:>9.2f}"
              f"{int(_num(r.get('impressions'))):>9}{int(clicks):>8}{_num(r.get('ctr')):>7.2f}"
              f"{_num(r.get('cpc')):>7.2f}{int(leads):>7}{(cpl if cpl else 0):>8.2f}")
        g = roll.setdefault(feat, {"spend": 0, "impr": 0, "clicks": 0, "leads": 0})
        g["spend"] += spend; g["impr"] += _num(r.get("impressions"))
        g["clicks"] += clicks; g["leads"] += leads
    print(f"\nBy feature (utm_content):\n")
    print(f"  {'feature':<20}{'spend':>10}{'clicks':>8}{'CTR%':>7}{'leads':>7}{'/lead':>9}")
    for feat, g in sorted(roll.items(), key=lambda kv: -kv[1]["spend"]):
        ctr = (g["clicks"] / g["impr"] * 100) if g["impr"] else 0
        cpl = g["spend"] / g["leads"] if g["leads"] else 0
        print(f"  {feat[:18]:<20}{g['spend']:>10.2f}{int(g['clicks']):>8}{ctr:>7.2f}"
              f"{int(g['leads']):>7}{(cpl if cpl else 0):>9.2f}")
    return 0


def _db_leads_by_utm(since: str) -> dict[str, int]:
    """Real email leads per utm_content, from the two Supabase subscription tables."""
    from shared.db import get_supabase_client
    c = get_supabase_client()
    out: dict[str, int] = {}
    for table in ("market_screening_email_subscriptions", "news_briefing_subscriptions"):
        rows = (c.schema("swingtrader").table(table)
                .select("metadata,created_at").gte("created_at", since).limit(5000).execute().data or [])
        for r in rows:
            uc = ((r.get("metadata") or {}).get("utm") or {}).get("utm_content") or "— organic —"
            out[uc] = out.get(uc, 0) + 1
    return out


def cmd_reconcile(args) -> int:
    since = _time_range(args.since)["since"]
    meta = _ad_insights(args.since)
    utm = _ad_utm_map()
    spend: dict[str, float] = {}; clicks: dict[str, float] = {}
    for r in meta:
        f = utm.get(r.get("ad_id"), "—")
        spend[f] = spend.get(f, 0) + _num(r.get("spend"))
        clicks[f] = clicks.get(f, 0) + _num(r.get("clicks"))
    db = _db_leads_by_utm(since)
    feats = sorted(set(spend) | set(db), key=lambda f: -(spend.get(f, 0)))
    print(f"\nMeta spend/clicks vs REAL email leads — since {since}:\n")
    print(f"  {'feature':<22}{'spend':>10}{'meta clicks':>12}{'db leads':>10}{'$/lead':>9}")
    for f in feats:
        s, cl, lg = spend.get(f, 0), clicks.get(f, 0), db.get(f, 0)
        cpl = s / lg if lg else 0
        print(f"  {f[:20]:<22}{s:>10.2f}{int(cl):>12}{lg:>10}{(cpl if cpl else 0):>9.2f}")
    print("\n(db leads come from the pixel-independent Supabase capture — the source of truth.)")
    return 0


def cmd_preflight(_args) -> int:
    from . import campaigns
    return 1 if campaigns.preflight() else 0


def cmd_draft(args) -> int:
    from . import campaigns
    return campaigns.build_drafts(campaigns.FEATURES, args.budget, dry_run=not args.go)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="meta_ads")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("verify").set_defaults(func=cmd_verify)
    sub.add_parser("preflight", help="check every gate before `draft --go`").set_defaults(func=cmd_preflight)
    pi = sub.add_parser("insights"); pi.add_argument("--since"); pi.set_defaults(func=cmd_insights)
    pr = sub.add_parser("reconcile"); pr.add_argument("--since"); pr.set_defaults(func=cmd_reconcile)
    pd = sub.add_parser("draft", help="create the feature A/B as PAUSED drafts")
    pd.add_argument("--budget", type=float, default=70.0, help="DKK/day per ad set (default 70)")
    pd.add_argument("--go", action="store_true", help="actually create (default is dry-run)")
    pd.set_defaults(func=cmd_draft)
    args = ap.parse_args(argv)
    try:
        return args.func(args)
    except MetaError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
