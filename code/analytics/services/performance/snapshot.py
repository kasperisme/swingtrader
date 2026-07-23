"""snapshot.py — the unified performance foundation.

Pulls every wired platform (sources.py), joins them along the funnel, and derives
a deterministic set of **action flags** — each finding routed to the skill/action
that fixes it. Writes output/performance/<date>/snapshot.{json,md}. The JSON is the
machine-readable foundation the action skills consume; the MD is the analyst digest.

The funnel spine, joined on utm_content / feature:
  paid impressions → clicks → (landing) → REAL leads → cost-per-lead   (Meta ⋈ Supabase)
  organic search impressions → clicks                                  (Search Console)
  channel mix + engagement                                             (GA4)
"""

from __future__ import annotations

import datetime as _dt
import json
import pathlib
from typing import Any

from . import sources

# analytics-root/output/performance/<date>/
_ANALYTICS = pathlib.Path(__file__).resolve().parents[2]
_OUT = _ANALYTICS / "output" / "performance"


def _since(days: int) -> str:
    return (_dt.date.today() - _dt.timedelta(days=days)).isoformat()


def build_snapshot(days: int = 28) -> dict[str, Any]:
    since = _since(days)
    blocks = {
        "ga4": sources.ga4_block(days),
        "search_console": sources.gsc_block(days),
        "meta_ads": sources.meta_block(since),
        "leads": sources.leads_block(since),
        "posthog": sources.posthog_block(),
    }
    snap: dict[str, Any] = {
        "generated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "window_days": days, "since": since,
        "platforms": {k: ({"available": True} if v.get("available")
                          else {"available": False, "error": v.get("error")})
                      for k, v in blocks.items()},
        **blocks,
    }
    snap["efficiency"] = _efficiency(blocks["meta_ads"], blocks["leads"])
    snap["funnel"] = _funnel(blocks)
    snap["health_flags"] = _flags(snap)
    return snap


def _efficiency(meta: dict, leads: dict) -> list[dict]:
    """Meta spend/clicks by feature ⋈ REAL Supabase leads → cost per actual lead."""
    if not meta.get("available"):
        return []
    db = leads.get("by_feature", {}) if leads.get("available") else {}
    rows = []
    for g in meta.get("by_feature", []):
        f = g["feature"]
        real = int(db.get(f, 0))
        rows.append({
            "feature": f, "spend": round(g["spend"], 2), "clicks": int(g["clicks"]),
            "impressions": int(g["impressions"]),
            "ctr": round(g["clicks"] / g["impressions"] * 100, 2) if g["impressions"] else 0.0,
            "real_leads": real,
            "cost_per_lead": round(g["spend"] / real, 2) if real else None,
            "landing_cvr": round(real / g["clicks"] * 100, 2) if g["clicks"] else 0.0,
        })
    return sorted(rows, key=lambda r: -r["spend"])


def _funnel(blocks: dict) -> dict:
    """The joined top-of-funnel spine (paid + organic + conversion truth)."""
    meta, gsc, ga, leads = (blocks["meta_ads"], blocks["search_console"],
                            blocks["ga4"], blocks["leads"])
    out: dict[str, Any] = {}
    if meta.get("available"):
        t = meta["totals"]
        out["paid"] = {
            "impressions": int(t["impressions"]), "clicks": int(t["clicks"]),
            "spend": round(t["spend"], 2),
            "ctr": round(t["clicks"] / t["impressions"] * 100, 2) if t["impressions"] else 0.0,
        }
    if gsc.get("available"):
        s = gsc["summary"]
        out["organic_search"] = {"impressions": int(s.get("impressions", 0)),
                                 "clicks": int(s.get("clicks", 0)),
                                 "ctr": round(s.get("ctr", 0), 2)}
    if ga.get("available"):
        out["ga4_sessions"] = ga["summary"]["sessions"]
    if leads.get("available"):
        out["real_leads"] = leads["total"]
    # blended cost per lead across all paid features with leads
    if meta.get("available") and leads.get("available"):
        spend = meta["totals"]["spend"]
        paid_leads = sum(v for k, v in leads["by_feature"].items() if k not in ("— organic —",))
        out["blended_cost_per_lead"] = round(spend / paid_leads, 2) if paid_leads else None
    return out


def _flags(snap: dict) -> list[dict]:
    """Deterministic findings, each ROUTED to the action that fixes it. This is the
    'data foundation for actions' — plain rules over the joined snapshot."""
    flags: list[dict] = []
    ga, gsc, meta, leads = (snap["ga4"], snap["search_console"], snap["meta_ads"], snap["leads"])

    def add(sev, area, finding, action, route):
        flags.append({"severity": sev, "area": area, "finding": finding,
                      "action": action, "route_to": route})

    # 1) invalid / bot traffic inflating GA4
    if ga.get("available"):
        for c in ga.get("channels", []):
            if c["sessions"] >= 1000 and c["engagement_pct"] < 5.0:
                add("high", "data-health",
                    f"GA4 channel '{c['channel']}' = {c['sessions']:,} sessions at "
                    f"{c['engagement_pct']}% engagement — almost certainly bot/invalid traffic "
                    f"inflating every GA4 total.",
                    "Add a GA4 data filter (or identify the source) and treat aggregates as untrustworthy until excluded.",
                    "ga4-config")
                break
    # 2) conversions not configured
    if ga.get("available") and leads.get("available"):
        ga_conv = ga["summary"].get("conversions", 0)
        if ga_conv == 0 and leads["total"] > 0:
            add("high", "measurement",
                f"GA4 shows 0 conversions but Supabase captured {leads['total']} real leads — "
                f"the sign-up event isn't marked a GA4 Key event.",
                "Fire a `sign_up` event on the briefing + screening forms and mark it a Key event, so GA4 + channel + Meta CPL become real.",
                "instrument-conversion")
    # 3) paid traffic not converting (message-match / CRO leak)
    for r in snap.get("efficiency", []):
        if r["feature"] in ("—", "— organic —"):
            continue
        if r["clicks"] >= 50 and r["real_leads"] == 0:
            add("high", "conversion",
                f"Paid feature '{r['feature']}' spent ${r['spend']} over {r['clicks']} clicks "
                f"with 0 real leads — the leak is entirely post-click (landing/message-match/form).",
                "Tighten ad→landing message-match + reduce form friction; re-check the impact_list/curiosity gap pacing.",
                "nis-ad-image / CRO")
    # 4) organic impressions not earning clicks (SEO title/meta)
    if gsc.get("available"):
        s = gsc["summary"]
        if s.get("impressions", 0) >= 1000 and s.get("ctr", 0) < 2.0:
            add("medium", "seo",
                f"Search Console: {int(s['impressions']):,} impressions at {s.get('ctr',0):.2f}% CTR "
                f"(avg pos {s.get('position',0):.1f}) — real demand, few clicks.",
                "Rewrite titles/meta on original-angle pages that rank p1-2 (see gsc.opportunities); skip syndicated-headline queries you can't win.",
                "seo-content")
    # 5) cost efficiency spread
    priced = [r for r in snap.get("efficiency", []) if r["cost_per_lead"] is not None]
    if len(priced) >= 2:
        best = min(priced, key=lambda r: r["cost_per_lead"])
        worst = max(priced, key=lambda r: r["cost_per_lead"])
        if worst["cost_per_lead"] > best["cost_per_lead"] * 1.5:
            add("medium", "budget",
                f"Cost/lead spread: '{best['feature']}' ${best['cost_per_lead']} vs "
                f"'{worst['feature']}' ${worst['cost_per_lead']}.",
                "Shift budget toward the cheaper-per-lead feature; test a new creative variant on the worse one.",
                "meta_ads / nis-ad-image")
    return flags


# ---- render + write -------------------------------------------------------
def to_markdown(s: dict) -> str:
    L = [f"# Performance snapshot — {s['since']} → today ({s['window_days']}d)",
         f"_generated {s['generated_at']}_", ""]
    plats = ", ".join(f"{k}{'' if v['available'] else ' ✗'}" for k, v in s["platforms"].items())
    L += [f"**Platforms:** {plats}", ""]

    f = s.get("funnel", {})
    L += ["## Funnel"]
    if "paid" in f:
        L.append(f"- **Paid:** {f['paid']['impressions']:,} impr → {f['paid']['clicks']:,} clicks "
                 f"({f['paid']['ctr']}% CTR) · ${f['paid']['spend']:,} spend")
    if "organic_search" in f:
        L.append(f"- **Organic search:** {f['organic_search']['impressions']:,} impr → "
                 f"{f['organic_search']['clicks']:,} clicks ({f['organic_search']['ctr']}% CTR)")
    if "ga4_sessions" in f:
        L.append(f"- **GA4 sessions:** {f['ga4_sessions']:,} (⚠ may include bot traffic — see flags)")
    if "real_leads" in f:
        cpl = f.get("blended_cost_per_lead")
        L.append(f"- **Real leads (Supabase truth):** {f['real_leads']}"
                 + (f" · blended ${cpl}/lead" if cpl else " · no paid leads yet"))
    L.append("")

    if s.get("efficiency"):
        L += ["## Cost per real lead — by feature", "",
              "| feature | spend | clicks | CTR% | real leads | $/lead | land CVR% |",
              "|---|--:|--:|--:|--:|--:|--:|"]
        for r in s["efficiency"]:
            L.append(f"| {r['feature']} | {r['spend']} | {r['clicks']} | {r['ctr']} | "
                     f"{r['real_leads']} | {r['cost_per_lead'] if r['cost_per_lead'] is not None else '—'} | {r['landing_cvr']} |")
        L.append("")

    L += ["## Action flags (routed)", ""]
    if not s["health_flags"]:
        L.append("_No flags — clean run._")
    for fl in s["health_flags"]:
        L += [f"### [{fl['severity'].upper()}] {fl['area']} → `{fl['route_to']}`",
              f"- **Finding:** {fl['finding']}",
              f"- **Do:** {fl['action']}", ""]
    return "\n".join(L)


def write(snapshot: dict, when: str | None = None) -> pathlib.Path:
    day = when or snapshot["generated_at"][:10]
    d = _OUT / day
    d.mkdir(parents=True, exist_ok=True)
    (d / "snapshot.json").write_text(json.dumps(snapshot, indent=2))
    (d / "snapshot.md").write_text(to_markdown(snapshot))
    return d
