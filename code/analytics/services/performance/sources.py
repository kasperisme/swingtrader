"""sources.py — thin, fault-tolerant adapters over every wired platform.

Each returns a normalized block: {"available": bool, ...data...} or
{"available": False, "error": "..."} so one dead/unconfigured platform never
sinks the whole snapshot. The aggregator (snapshot.py) joins these along the
funnel; this file does no interpretation.

Wired platforms: GA4 (Data API), Search Console, Meta Ads, Supabase leads
(conversion truth), PostHog. Vercel Analytics is dashboard-only (no pull API).
"""

from __future__ import annotations

from typing import Any, Callable


def _safe(fn: Callable[[], dict]) -> dict[str, Any]:
    try:
        return {"available": True, **fn()}
    except Exception as e:
        return {"available": False, "error": f"{type(e).__name__}: {str(e)[:180]}"}


def _pct(v) -> float:
    try:
        return round(float(v) * 100, 1)          # GA4 engagementRate ratio → percent
    except (TypeError, ValueError):
        return 0.0


def ga4_block(days: int) -> dict[str, Any]:
    """GA4: acquisition channels, landing pages, key events."""
    def go():
        from services.google_analytics import ga4
        s = ga4.summary(days)
        ch = ga4.channels(days)
        lp = ga4.landing_pages(days, 12)
        cv = ga4.conversions(days, 15)
        return {
            "summary": {
                "sessions": int(s.get("sessions", 0)), "users": int(s.get("totalUsers", 0)),
                "new_users": int(s.get("newUsers", 0)), "views": int(s.get("screenPageViews", 0)),
                "engagement_pct": _pct(s.get("engagementRate")), "conversions": int(s.get("conversions", 0)),
            },
            "channels": [{"channel": c.get("sessionDefaultChannelGroup"), "sessions": int(c.get("sessions", 0)),
                          "users": int(c.get("totalUsers", 0)), "engagement_pct": _pct(c.get("engagementRate")),
                          "conversions": int(c.get("conversions", 0))} for c in ch],
            "landing_pages": [{"page": p.get("landingPagePlusQueryString"), "sessions": int(p.get("sessions", 0)),
                               "engagement_pct": _pct(p.get("engagementRate")),
                               "conversions": int(p.get("conversions", 0))} for p in lp],
            "events": [{"event": e.get("eventName"), "conversions": int(e.get("conversions", 0)),
                        "count": int(e.get("eventCount", 0))} for e in cv],
        }
    return _safe(go)


def gsc_block(days: int) -> dict[str, Any]:
    """Search Console: organic summary, top queries, striking-distance opportunities."""
    def go():
        from services.google_analytics import search_console as sc
        return {
            "summary": sc.summary(days),
            "top_queries": sc.queries(days, 15),
            "opportunities": sc.opportunities(days, 80, 12),
        }
    return _safe(go)


def meta_block(since: str) -> dict[str, Any]:
    """Meta Ads: paid spend / clicks / impressions / Meta-attributed leads, by feature (utm_content)."""
    def go():
        from services.meta_ads import cli as m
        insights = m._ad_insights(since)
        utm = m._ad_utm_map()
        by: dict[str, dict] = {}
        tot = {"impressions": 0.0, "clicks": 0.0, "spend": 0.0}
        for r in insights:
            f = utm.get(r.get("ad_id"), "—")
            g = by.setdefault(f, {"feature": f, "spend": 0.0, "clicks": 0.0,
                                  "impressions": 0.0, "meta_leads": 0.0})
            g["spend"] += m._num(r.get("spend")); g["clicks"] += m._num(r.get("clicks"))
            g["impressions"] += m._num(r.get("impressions")); g["meta_leads"] += m._leads(r.get("actions"))
            for k in tot:
                tot[k] += m._num(r.get("impressions" if k == "impressions" else k))
        return {"totals": tot, "by_feature": list(by.values()), "ad_count": len(insights)}
    return _safe(go)


def leads_block(since: str) -> dict[str, Any]:
    """The conversion truth: real email/Telegram sign-ups from Supabase, by utm_content."""
    def go():
        from services.meta_ads import cli as m
        db = m._db_leads_by_utm(since)
        return {"total": int(sum(db.values())), "by_feature": {k: int(v) for k, v in db.items()}}
    return _safe(go)


def posthog_block() -> dict[str, Any]:
    """PostHog: connectivity + the lead-magnet funnel dashboard (behavioural layer).
    Funnel/heatmap *values* live in the PostHog UI; v1 confirms the wiring + links it."""
    def go():
        from services.posthog_analytics import funnels as pf
        pid = pf._project_id()
        host = __import__("os").environ.get("POSTHOG_HOST", "https://eu.posthog.com").rstrip("/")
        return {"project_id": pid, "dashboard": pf.DASHBOARD_NAME,
                "dashboard_url": f"{host}/project/{pid}/dashboard",
                "note": "funnel drop-off + heatmaps in the PostHog UI (not pulled in v1)"}
    return _safe(go)
