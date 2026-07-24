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
        "onsite": sources.onsite_block(days),
        "email": sources.email_block(days),
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
    cur = (meta.get("currency") or "") if meta.get("available") else ""

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
                f"Paid feature '{r['feature']}' spent {r['spend']} {cur} over {r['clicks']} clicks "
                f"with 0 real leads — the leak is entirely post-click (landing/message-match/form).",
                "Tighten ad→landing message-match + reduce form friction; re-check the impact_list/curiosity gap pacing.",
                "nis-ad-image / CRO")
    # 3b) Meta ads with delivery issues (disapproved / limited)
    if meta.get("available") and meta.get("with_issues"):
        mi = meta["with_issues"]
        names = ", ".join(f"{x['ad_name']} ({x['feature']})" for x in mi[:3])
        add("high", "delivery",
            f"{len(mi)} live Meta ad(s) flagged WITH_ISSUES/disapproved — limited or halted delivery: {names}.",
            "Open Ads Manager → the flagged ad → fix the policy/asset issue or replace the creative to restore delivery.",
            "meta_ads")
    # 3c) transparency: the window blends paused/retired spend (efficiency is ACTIVE-only)
    if meta.get("available"):
        ps = meta.get("paused_spend", 0.0)
        window_total = ps + meta["totals"]["spend"]
        if ps and window_total and ps / window_total > 0.15:
            add("info", "data-health",
                f"{ps:.0f} {cur} of the window's paid spend is paused/retired ads — the efficiency "
                f"below is ACTIVE-only (live), not the raw all-ads window blend.",
                "None needed — this is the correct live view; don't compare it against a raw window total.",
                "none")
    # 3d) on-site funnel measurability + friction
    o = snap.get("onsite", {})
    if o.get("available"):
        ff = o.get("form_funnel", {})
        if not o.get("client_funnel_instrumented") and o.get("confirmed_subscribes", 0) > 0:
            add("high", "measurement",
                f"On-site form funnel isn't capturing (lead_form_viewed/submitted = 0) though "
                f"{o['confirmed_subscribes']} subscribes confirmed server-side — you can't see WHERE "
                f"visitors drop between landing and the form.",
                "Verify the just-deployed lead_form_* client events actually fire (or fix them); "
                "until then every CRO change is blind.",
                "instrument-funnel")
        elif ff.get("form_viewed", 0) >= 30:
            vs = ff["form_submitted"] / ff["form_viewed"] * 100 if ff["form_viewed"] else 0
            if vs < 30:
                add("high", "conversion",
                    f"Form view→submit is {vs:.0f}% ({ff['form_submitted']}/{ff['form_viewed']}) — "
                    f"heavy abandonment at the form itself.",
                    "Cut fields, restate the offer/value at the form, reduce required inputs; "
                    "read the top abandonment reasons.",
                    "CRO")
        ga = snap.get("ga4", {})
        g = ga.get("form_funnel", {}) if ga.get("available") else {}
        if g.get("form_start", 0) >= 20 and g.get("form_submit", 0) <= 1:
            add("info", "measurement",
                f"GA4 form_start={g['form_start']} but form_submit={g.get('form_submit', 0)} — GA4 "
                f"isn't detecting the React form submit (not real abandonment).",
                "Rely on the sign_up event + PostHog funnel + Supabase leads, not GA4 auto form_submit.",
                "none")
    # 3e) email deliverability + engagement
    em = snap.get("email", {})
    if em.get("available"):
        t = em["totals"]
        if t["sent"] >= 20 and t["bounce_rate"] > 3.0:
            add("high", "deliverability",
                f"Email bounce rate {t['bounce_rate']}% ({t['bounced']}/{t['sent']}) — hurts sender reputation.",
                "Remove hard-bounced addresses, verify SPF/DKIM/DMARC, and validate emails at capture.",
                "email")
        if not em["tracking_on"] and t["sent"] >= 10:
            add("info", "measurement",
                "Resend open/click tracking has no events yet — engagement (open/click) is unmeasured; "
                "only deliverability is available.",
                "Confirm click+open tracking is enabled on the domain; it populates on the next sends.",
                "email-config")
        elif em["tracking_on"] and t["delivered"] >= 30 and t["click_rate"] < 1.5:
            add("medium", "email",
                f"Email click rate {t['click_rate']}% on {t['delivered']} delivered — low engagement with the CTAs.",
                "Test subject lines + a single clear CTA; the cross-sell/upgrade blocks may be too buried.",
                "email-content")
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
                f"Cost/lead spread: '{best['feature']}' {best['cost_per_lead']} {cur} vs "
                f"'{worst['feature']}' {worst['cost_per_lead']} {cur}.",
                "Shift budget toward the cheaper-per-lead feature; test a new creative variant on the worse one.",
                "meta_ads / nis-ad-image")
    return flags


# ---- render + write -------------------------------------------------------
def to_markdown(s: dict) -> str:
    cur = (s.get("meta_ads") or {}).get("currency") or ""      # e.g. DKK — never assume USD
    L = [f"# Performance snapshot — {s['since']} → today ({s['window_days']}d)",
         f"_generated {s['generated_at']}_", ""]
    plats = ", ".join(f"{k}{'' if v['available'] else ' ✗'}" for k, v in s["platforms"].items())
    L += [f"**Platforms:** {plats}", ""]

    f = s.get("funnel", {})
    L += ["## Funnel"]
    if "paid" in f:
        L.append(f"- **Paid:** {f['paid']['impressions']:,} impr → {f['paid']['clicks']:,} clicks "
                 f"({f['paid']['ctr']}% CTR) · {f['paid']['spend']:,.2f} {cur} spend")
    if "organic_search" in f:
        L.append(f"- **Organic search:** {f['organic_search']['impressions']:,} impr → "
                 f"{f['organic_search']['clicks']:,} clicks ({f['organic_search']['ctr']}% CTR)")
    if "ga4_sessions" in f:
        L.append(f"- **GA4 sessions:** {f['ga4_sessions']:,} (⚠ may include bot traffic — see flags)")
    if "real_leads" in f:
        cpl = f.get("blended_cost_per_lead")
        L.append(f"- **Real leads (Supabase truth):** {f['real_leads']}"
                 + (f" · blended {cpl:,.2f} {cur}/lead" if cpl else " · no paid leads yet"))
    m = s.get("meta_ads", {})
    if m.get("available"):
        L.append(f"- _Meta scope: ACTIVE-only — {m.get('active_ad_count', 0)} live ad(s); "
                 f"{m.get('paused_spend', 0):.0f} {cur} paused/retired spend in the window (excluded above)._")
        if m.get("with_issues"):
            L.append(f"- ⚠ **{len(m['with_issues'])} ad(s) WITH_ISSUES:** "
                     + ", ".join(x["ad_name"] for x in m["with_issues"][:3]))
    L.append("")

    o = s.get("onsite", {})
    if o.get("available"):
        L += ["## On-site funnel (CRO)"]
        L.append(f"- PostHog pageviews **{o['pageviews']:,}** · confirmed subscribes (server truth) "
                 f"**{o['confirmed_subscribes']}** · early-access {o['early_access_signups']}")
        ff = o["form_funnel"]
        if o["client_funnel_instrumented"]:
            fv, fsu, fsb = ff["form_viewed"], ff["form_submitted"], ff["subscribed_client"]
            rate = f" (view→submit {fsu / fv * 100:.0f}%)" if fv else ""
            L.append(f"- Form funnel: viewed **{fv}** → submitted **{fsu}** → subscribed **{fsb}**{rate}")
            if o["form_errors"]:
                L.append("- Abandonment reasons: "
                         + ", ".join(f"{e['reason']} ({e['count']})" for e in o["form_errors"][:5]))
        else:
            L.append("- ⚠ **Client form-funnel not capturing yet** (`lead_form_*` = 0) — "
                     "on-site drop-off is invisible until these events flow.")
        dl = o["downloads"]
        L.append(f"- Screening downloads: {dl['events']} by {dl['people']} people")
        ga = s.get("ga4", {})
        if ga.get("available") and ga.get("form_funnel"):
            g = ga["form_funnel"]
            L.append(f"- GA4 form events: form_start {g.get('form_start', 0)} · "
                     f"form_submit {g.get('form_submit', 0)} · sign_up {g.get('sign_up', 0)} "
                     f"_(GA4 misses React submits — trust sign_up + server truth)_")
        L.append("")

    em = s.get("email", {})
    if em.get("available"):
        t = em["totals"]
        track = "open/click ON" if em["tracking_on"] else "open/click OFF (deliverability only)"
        L += ["## Email (Resend)"]
        L.append(f"- {t['sent']} sent · **{t['delivery_rate']}% delivered** · {t['bounce_rate']}% bounced"
                 + (f" · **{t['open_rate']}% open** · **{t['click_rate']}% click**" if em["tracking_on"] else "")
                 + f"  _({track})_")
        for mag, g in list(em["by_magnet"].items())[:5]:
            eng = (f" · open {g['open_rate']}% · click {g['click_rate']}%") if em["tracking_on"] else ""
            L.append(f"  - `{mag}`: {g['sent']} sent · {g['delivery_rate']}% delivered · "
                     f"{g['bounce_rate']}% bounce{eng}")
        L.append("")

    if s.get("efficiency"):
        L += ["## Cost per real lead — by feature", "",
              f"| feature | spend ({cur}) | clicks | CTR% | real leads | {cur}/lead | land CVR% |",
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
