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
         "fields": "ad_id,ad_name,impressions,reach,frequency,clicks,ctr,cpc,cpm,spend,actions",
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
    if args.campaign:
        slugs, camp_name = campaigns.discover_campaign(args.campaign)
        return campaigns.build_drafts(slugs, args.budget, dry_run=not args.go, campaign_name=camp_name)
    return campaigns.build_drafts(campaigns.FEATURES, args.budget, dry_run=not args.go)


def _load_manifests() -> dict[str, dict]:
    """ad_id → manifest row (design genome + campaign/magnet), from every
    output/ads/**/launch_manifest.json a `draft --go` wrote. This is the join
    table from Meta performance (keyed by ad_id) back to the ad's design."""
    root = client._ANALYTICS / "output" / "ads"
    out: dict[str, dict] = {}
    for mf in root.glob("**/launch_manifest.json"):
        try:
            rows = json.loads(mf.read_text())
        except (OSError, ValueError):
            continue
        for r in rows if isinstance(rows, list) else []:
            if r.get("ad_id"):
                out[str(r["ad_id"])] = r
    return out


# The design levers a new ad can be biased on. Kept small + stable so history aggregates.
_LEVERS = ["hook_type", "angle", "primary_emotion", "accent", "theme",
           "background_type", "has_proof", "bullet_count", "cta_label",
           "curiosity_type", "curiosity_strength", "impact_list_reveal"]


def _quantile(vals: list[float], q: float):
    """Nearest-rank quantile (no numpy). None if empty."""
    xs = sorted(v for v in vals if v is not None)
    if not xs:
        return None
    i = min(len(xs) - 1, max(0, int(round(q * (len(xs) - 1)))))
    return xs[i]


def _rollup(per: list[dict], field: str, min_impr: float) -> list[dict]:
    """Group delivered ads (impr ≥ min_impr) by one design field → normalized rates.
    All comparisons are RATES (per-impression / per-spend), so budget & days-active
    don't need dividing out. Rates are impression-weighted (pooled), and frequency is
    carried as a fatigue covariate (impression-weighted mean)."""
    roll: dict[str, dict] = {}
    for p in per:
        if p["impr"] < min_impr:
            continue
        key = str(p["design"].get(field, "—"))
        g = roll.setdefault(key, {"value": key, "n": 0, "spend": 0.0, "impr": 0.0,
                                  "clicks": 0.0, "leads": 0.0, "_freq_w": 0.0})
        g["n"] += 1
        for k in ("spend", "impr", "clicks", "leads"):
            g[k] += p[k]
        g["_freq_w"] += p["freq"] * p["impr"]        # impression-weighted frequency
    for g in roll.values():
        g["ctr"] = (g["clicks"] / g["impr"] * 100) if g["impr"] else 0.0       # per-impression
        g["cpm"] = (g["spend"] / g["impr"] * 1000) if g["impr"] else 0.0       # per-1k-impr
        g["cvr"] = (g["leads"] / g["clicks"] * 100) if g["clicks"] else 0.0    # per-click
        g["cpl"] = (g["spend"] / g["leads"]) if g["leads"] else None           # per-lead
        g["freq"] = (g["_freq_w"] / g["impr"]) if g["impr"] else 0.0
        del g["_freq_w"]
    # best first: lowest cost-per-lead when leads exist, else highest CTR
    return sorted(roll.values(), key=lambda g: (g["cpl"] if g["cpl"] is not None else 1e9, -g["ctr"]))


def cmd_design(args) -> int:
    """Join Meta performance (by ad_id) to each ad's design genome — the loop that
    tells you which creative choices drive engagement, and feeds the next ad's design.
    Works even before delivery (shows the wired join with zero metrics)."""
    manifests = _load_manifests()
    if not manifests:
        print("No launch_manifest.json found. Create ads with `draft --campaign <…> --go` first "
              "(the manifest is what ties Meta ad_ids back to the design metadata).")
        return 0
    ins = {str(r.get("ad_id")): r for r in _ad_insights(args.since)}

    # LEFT-join every created ad → its insights (0 if it hasn't delivered yet)
    per = []
    for aid, man in manifests.items():
        r = ins.get(aid, {})
        d = man.get("design", {}) or {}
        spend, clicks = _num(r.get("spend")), _num(r.get("clicks"))
        impr, leads = _num(r.get("impressions")), _leads(r.get("actions"))
        per.append({"ad_id": aid, "campaign": man.get("campaign_name") or man.get("campaign"),
                    "magnet": man.get("lead_magnet"), "design": d, "delivered": bool(r),
                    "spend": spend, "clicks": clicks, "impr": impr, "leads": leads,
                    "freq": _num(r.get("frequency")), "cpm": _num(r.get("cpm")),
                    "ctr": (clicks / impr * 100) if impr else 0.0,
                    "cvr": (leads / clicks * 100) if clicks else 0.0})
    live = sum(1 for p in per if p["delivered"])

    # Clickbait guard: a strong curiosity gap that DOESN'T convert = high CTR + low CVR.
    # Flag ads/levers whose CTR is top-quartile while CVR is bottom-quartile (needs ≥4
    # delivered ads with clicks for the quartiles to carry any signal).
    _clk = [p for p in per if p["delivered"] and p["clicks"] >= 1 and p["impr"] >= args.min_impr]
    _ctr_hi = _quantile([p["ctr"] for p in _clk], 0.75) if len(_clk) >= 4 else None
    _cvr_lo = _quantile([p["cvr"] for p in _clk], 0.25) if len(_clk) >= 4 else None

    def _clickbait(ctr, cvr, clicks) -> bool:
        return bool(_ctr_hi and _cvr_lo is not None and clicks >= 1
                    and ctr >= _ctr_hi and cvr <= _cvr_lo)

    for p in per:
        p["clickbait"] = _clickbait(p["ctr"], p["cvr"], p["clicks"])

    if args.json:
        levers = {f: _rollup(per, f, args.min_impr) for f in _LEVERS}
        for rows in levers.values():
            for g in rows:
                g["clickbait"] = _clickbait(g["ctr"], g["cvr"], g["clicks"])
        print(json.dumps({"ads_total": len(per), "ads_delivered": live,
                          "min_impr": args.min_impr,
                          "clickbait_thresholds": {"ctr_p75": _ctr_hi, "cvr_p25": _cvr_lo},
                          "per_ad": per, "levers": levers}, indent=2))
        return 0

    print(f"\nTraceability — {len(per)} created ad(s) joined to design; {live} with delivery"
          f"{'' if live else ' yet (metrics 0 until you set them Active)'}:\n")
    print(f"  {'ad_id':<20}{'magnet':<16}{'hook':<12}{'proof':<6}"
          f"{'spend':>8}{'impr':>8}{'freq':>6}{'CPM':>7}{'CTR%':>7}{'leads':>6}{'CVR%':>7}")
    for p in sorted(per, key=lambda x: -x["spend"]):
        d = p["design"]
        print(f"  {p['ad_id'][:18]:<20}{(p['magnet'] or '—')[:14]:<16}"
              f"{str(d.get('hook_type') or '—')[:10]:<12}"
              f"{('yes' if d.get('has_proof') else 'no'):<6}"
              f"{p['spend']:>8.2f}{int(p['impr']):>8}{p['freq']:>6.1f}{p['cpm']:>7.2f}"
              f"{p['ctr']:>7.2f}{int(p['leads']):>6}{p['cvr']:>7.1f}"
              f"{'  ⚠clickbait' if p['clickbait'] else ''}")

    fields = _LEVERS if args.leaderboard else ([args.by] if args.by else [])
    for f in fields:
        rows = _rollup(per, f, args.min_impr)
        if not rows:
            continue
        print(f"\nBy design.{f}  (best first; rates are normalized; min_impr={args.min_impr}):")
        print(f"  {f:<20}{'ads':>5}{'impr':>9}{'freq':>6}{'CPM':>7}{'CTR%':>7}{'CVR%':>7}{'/lead':>9}")
        for g in rows:
            flags = ""
            if g["impr"] < 500:
                flags += "  ⚠low-n"
            if g["freq"] >= 3.0:
                flags += "  ⚠fatigue"          # high frequency depresses CTR — not a design loss
            if _clickbait(g["ctr"], g["cvr"], g["clicks"]):
                flags += "  ⚠clickbait"        # magnetic but doesn't convert (CTR↑ CVR↓)
            cpl = g["cpl"] if g["cpl"] is not None else 0
            print(f"  {g['value'][:18]:<20}{g['n']:>5}{int(g['impr']):>9}{g['freq']:>6.1f}"
                  f"{g['cpm']:>7.2f}{g['ctr']:>7.2f}{g['cvr']:>7.1f}{cpl:>9.2f}{flags}")

    if args.leaderboard and live:
        print("\n⚠ Rates already normalize budget & duration — don't divide by days/budget again.")
        print("  Compare like-for-like: watch ⚠fatigue (high frequency deflates CTR) and CPM gaps")
        print("  (budget/audience differences), treat a lever as a winner only above min_impr, and")
        print("  keep varying ONE lever per new ad.")
        print("  ⚠clickbait = top-quartile CTR but bottom-quartile CVR — a gap that pulls the click")
        print("  but not the lead. Judge curiosity levers on CVR / $-per-lead, never CTR alone.")
    return 0


def cmd_capi_sync(args) -> int:
    from . import capi
    since = None
    if args.since:
        since = _time_range(args.since)["since"]
    return capi.sync(since=since, limit=args.limit, dry_run=args.dry_run,
                     test_event_code=args.test_code)


def cmd_capi_test(args) -> int:
    from . import capi
    resp = capi.send_test(args.test_code)
    print(f"events_received={resp.get('events_received')} · fbtrace_id={resp.get('fbtrace_id')}")
    for m in resp.get("messages") or []:
        print(f"  ⚠ {m}")
    print("→ check Events Manager → Test Events for the code you passed.")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="meta_ads")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("verify").set_defaults(func=cmd_verify)
    sub.add_parser("preflight", help="check every gate before `draft --go`").set_defaults(func=cmd_preflight)
    pi = sub.add_parser("insights"); pi.add_argument("--since"); pi.set_defaults(func=cmd_insights)
    pr = sub.add_parser("reconcile"); pr.add_argument("--since"); pr.set_defaults(func=cmd_reconcile)
    pg = sub.add_parser("design", help="join performance ↔ ad design genome (what drives engagement)")
    pg.add_argument("--since")
    pg.add_argument("--by", help="roll up by one design field, e.g. hook_type | accent | has_proof | theme")
    pg.add_argument("--leaderboard", action="store_true", help="rank every design lever, best first")
    pg.add_argument("--json", action="store_true", help="machine-readable (feed the next ad's design)")
    pg.add_argument("--min-impr", type=float, default=0.0, dest="min_impr",
                    help="ignore ads below this impression count in rollups (cut noise)")
    pg.set_defaults(func=cmd_design)
    pd = sub.add_parser("draft", help="create the feature A/B as PAUSED drafts")
    pd.add_argument("--campaign", help="a <date>-<short-name> dir under output/ads/ "
                    "(its briefing/ + market-screening/ subfolders become the ad sets)")
    pd.add_argument("--budget", type=float, default=70.0, help="DKK/day per ad set (default 70)")
    pd.add_argument("--go", action="store_true", help="actually create (default is dry-run)")
    pd.set_defaults(func=cmd_draft)
    ps = sub.add_parser("capi-sync", help="forward early_access_signups leads to Meta (Conversions API)")
    ps.add_argument("--since", help="only leads on/after YYYY-MM-DD (default: all unsent)")
    ps.add_argument("--limit", type=int, default=500, help="max leads per run (default 500)")
    ps.add_argument("--dry-run", action="store_true", help="show a sample hashed event; send nothing")
    ps.add_argument("--test", dest="test_code", help="Events Manager test_event_code — routes to Test Events; rows NOT marked sent")
    ps.set_defaults(func=cmd_capi_sync)
    pt = sub.add_parser("capi-test", help="send ONE synthetic Lead event to verify the connection")
    pt.add_argument("--test", dest="test_code", required=True, help="Events Manager test_event_code")
    pt.set_defaults(func=cmd_capi_test)
    args = ap.parse_args(argv)
    try:
        return args.func(args)
    except MetaError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
