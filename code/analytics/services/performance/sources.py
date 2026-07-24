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
            "form_funnel": ga4.form_funnel(days),
        }
    return _safe(go)


def onsite_block(days: int) -> dict[str, Any]:
    """On-site / CRO funnel from PostHog: pageviews → form viewed → submitted →
    subscribed, plus server-side confirmed subscribes (truth) and the high-intent
    download signal. Makes 'where do people drop on the site' a first-class metric."""
    def go():
        from services.posthog_analytics import funnels as pf
        import requests
        pid = pf._project_id()
        base = pf._base(pid)

        def hog(q: str):
            r = requests.post(f"{base}/query/", headers=pf._H,
                              json={"query": {"kind": "HogQLQuery", "query": q}}, timeout=60)
            r.raise_for_status()
            return r.json().get("results", [])

        events = ("$pageview", "lead_form_viewed", "lead_form_submitted", "lead_form_error",
                  "lead_subscribed", "briefing_subscribed", "screening_email_subscribed",
                  "early_access_signup", "market_screening_downloaded")
        inlist = ",".join(f"'{e}'" for e in events)
        rows = hog(f"""
            SELECT event, count() AS c, count(DISTINCT person_id) AS people
            FROM events
            WHERE event IN ({inlist}) AND timestamp > now() - INTERVAL {int(days)} DAY
            GROUP BY event""")
        ev = {r[0]: {"events": int(r[1]), "people": int(r[2])} for r in rows}

        def c(name: str) -> int:
            return ev.get(name, {}).get("events", 0)

        funnel = {"form_viewed": c("lead_form_viewed"), "form_submitted": c("lead_form_submitted"),
                  "form_error": c("lead_form_error"), "subscribed_client": c("lead_subscribed")}
        instrumented = funnel["form_viewed"] > 0 or funnel["form_submitted"] > 0
        # abandonment reasons — only meaningful once the client funnel is capturing
        errors = []
        if funnel["form_error"]:
            errors = [{"reason": str(r[0]), "count": int(r[1])} for r in hog(
                f"""SELECT properties.reason, count() FROM events WHERE event='lead_form_error'
                    AND timestamp > now() - INTERVAL {int(days)} DAY GROUP BY 1 ORDER BY 2 DESC LIMIT 8""")]
        return {
            "pageviews": c("$pageview"),
            "form_funnel": funnel,
            "form_errors": errors,
            "client_funnel_instrumented": instrumented,
            "confirmed_subscribes": c("briefing_subscribed") + c("screening_email_subscribed"),
            "early_access_signups": c("early_access_signup"),
            "downloads": {"events": c("market_screening_downloaded"),
                          "people": ev.get("market_screening_downloaded", {}).get("people", 0)},
            "project_id": pid,
            "dashboard": pf.DASHBOARD_NAME,
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
    """Meta Ads: paid spend/clicks/impressions/leads by feature — STATUS-AWARE.

    `by_feature`/`totals` reflect **ACTIVE ads only** (the live picture), so retired/paused
    campaigns in the window don't pollute cost-per-lead (they blended in before and misled
    the analysis). Paused spend is reported separately; `with_issues` surfaces Meta-flagged
    ads (disapproved / limited delivery)."""
    def go():
        from services.meta_ads import cli as m
        from services.meta_ads import client as c
        ads = c.paginate(c.get(f"{c.account()}/ads",
                               {"fields": "id,name,effective_status,configured_status,creative{url_tags}",
                                "limit": 200}))
        info = {a["id"]: (c.utm_from_url_tags((a.get("creative") or {}).get("url_tags")).get("utm_content", "—"),
                          a.get("effective_status", "UNKNOWN"), a.get("configured_status", "UNKNOWN"))
                for a in ads}
        insights = m._ad_insights(since)
        by: dict[str, dict] = {}
        tot = {"impressions": 0.0, "clicks": 0.0, "spend": 0.0}
        status_spend: dict[str, float] = {}
        with_issues: list[dict] = []
        active_ads = 0
        for r in insights:
            uc, st, cfg = info.get(r.get("ad_id"), ("—", "UNKNOWN", "UNKNOWN"))
            sp = m._num(r.get("spend"))
            status_spend[st] = status_spend.get(st, 0.0) + sp
            # Only a *blocking* issue: you want it live (configured ACTIVE) but Meta won't
            # deliver it. A paused+rejected ad isn't hurting anything, so don't alarm on it.
            if ("ISSUE" in st or "DISAPPROV" in st) and cfg == "ACTIVE":
                with_issues.append({"ad_id": r.get("ad_id"), "ad_name": r.get("ad_name"),
                                    "feature": uc, "status": st, "configured_status": cfg,
                                    "spend": round(sp, 2), "clicks": int(m._num(r.get("clicks")))})
            if st != "ACTIVE":
                continue                                     # live picture only
            active_ads += 1
            g = by.setdefault(uc, {"feature": uc, "spend": 0.0, "clicks": 0.0,
                                   "impressions": 0.0, "meta_leads": 0.0})
            g["spend"] += sp; g["clicks"] += m._num(r.get("clicks"))
            g["impressions"] += m._num(r.get("impressions")); g["meta_leads"] += m._leads(r.get("actions"))
            tot["spend"] += sp; tot["clicks"] += m._num(r.get("clicks"))
            tot["impressions"] += m._num(r.get("impressions"))
        return {"totals": tot, "by_feature": list(by.values()), "scope": "active_only",
                "currency": c.account_currency(),
                "ad_count": len(insights), "active_ad_count": active_ads,
                "status_spend": {k: round(v, 2) for k, v in sorted(status_spend.items(), key=lambda x: -x[1])},
                "paused_spend": round(sum(v for k, v in status_spend.items() if k != "ACTIVE"), 2),
                "with_issues": with_issues}
    return _safe(go)


def leads_block(since: str) -> dict[str, Any]:
    """The conversion truth: real email/Telegram sign-ups from Supabase, by utm_content."""
    def go():
        from services.meta_ads import cli as m
        db = m._db_leads_by_utm(since)
        return {"total": int(sum(db.values())), "by_feature": {k: int(v) for k, v in db.items()}}
    return _safe(go)


def email_block(days: int) -> dict[str, Any]:
    """Email effectiveness from Resend (`GET /emails`, `last_event` per email).

    Aggregates delivery / bounce (always) + open / click (once tracking is on) by
    lead-magnet **tag** (`type`). last_event is the LATEST event, so we treat the
    funnel as nested: delivered ⊇ opened ⊇ clicked. `tracking_on` is inferred from
    whether any open/click events exist yet."""
    def go():
        import datetime as _d
        import os
        import pathlib
        from collections import defaultdict

        import requests
        from dotenv import load_dotenv
        for p in pathlib.Path(__file__).resolve().parents:
            if (p / ".env").exists():
                load_dotenv(p / ".env"); break
        key = os.environ.get("RESEND_API_KEY", "")
        if not key:
            raise RuntimeError("RESEND_API_KEY not set")
        H = {"Authorization": f"Bearer {key}"}
        since = (_d.date.today() - _d.timedelta(days=days)).isoformat()

        rows, after, pages = [], None, 0
        while pages < 20:                                  # ≤2000 emails, newest-first
            params = {"limit": 100, **({"after": after} if after else {})}
            r = requests.get("https://api.resend.com/emails", headers=H, params=params, timeout=30)
            r.raise_for_status()
            body = r.json(); data = body.get("data", [])
            rows += data; pages += 1
            if not body.get("has_more") or not data:
                break
            if (data[-1].get("created_at", "")[:10] or "9") < since:   # paged past window
                break
            after = data[-1].get("id")

        def frm(e):
            f = e.get("from", "")
            return ",".join(f) if isinstance(f, list) else str(f)

        ours = [e for e in rows
                if "newsimpactscreener.com" in frm(e) and e.get("created_at", "")[:10] >= since]

        def magnet_of(e):
            # tags first (only on the detail endpoint); the LIST endpoint omits tags,
            # so fall back to the subject — which is unambiguous per lead magnet.
            for t in (e.get("tags") or []):
                if t.get("name") == "type":
                    return t.get("value")
            s = (e.get("subject") or "").lower()
            if "briefing" in s:
                return "news_briefing"
            if "new result" in s:
                return "market_screening_results"
            if "coming your way" in s or "you're in" in s:
                return "screening_confirmation"
            if "welcome" in s:
                return "signup_welcome"
            return "untagged"

        DELIV, OPEN = {"delivered", "opened", "clicked"}, {"opened", "clicked"}
        agg = defaultdict(lambda: dict(sent=0, delivered=0, opened=0, clicked=0, bounced=0))
        for e in ours:
            le = e.get("last_event"); g = agg[magnet_of(e)]; g["sent"] += 1
            g["delivered"] += le in DELIV
            g["opened"] += le in OPEN
            g["clicked"] += le == "clicked"
            g["bounced"] += le == "bounced"

        def rates(g):
            s, d = g["sent"], g["delivered"]
            return {**g,
                    "delivery_rate": round(d / s * 100, 1) if s else 0.0,
                    "bounce_rate": round(g["bounced"] / s * 100, 1) if s else 0.0,
                    "open_rate": round(g["opened"] / d * 100, 1) if d else 0.0,
                    "click_rate": round(g["clicked"] / d * 100, 1) if d else 0.0}

        tot = dict(sent=len(ours),
                   delivered=sum(v["delivered"] for v in agg.values()),
                   opened=sum(v["opened"] for v in agg.values()),
                   clicked=sum(v["clicked"] for v in agg.values()),
                   bounced=sum(v["bounced"] for v in agg.values()))
        return {"window_days": days, "totals": rates(tot),
                "by_magnet": {k: rates(v) for k, v in sorted(agg.items(), key=lambda x: -x[1]["sent"])},
                "tracking_on": (tot["opened"] > 0 or tot["clicked"] > 0)}
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
