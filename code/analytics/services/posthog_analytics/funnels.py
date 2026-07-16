"""Create the lead-magnet subscribe funnel dashboard in PostHog (management API).

Builds — idempotently, by name — a "Lead-magnet funnel" dashboard with:
  • the view→submit→subscribe funnel, broken down by magnet
  • the same funnel broken down by feature (utm_content)
  • form-error reasons (where people abandon)
  • confirmed subscriptions by magnet

The events come from the client instrumentation in code/ui (lead_form_viewed /
lead_form_submitted / lead_form_error / lead_subscribed). They only carry data once
the UI is deployed and ad traffic flows — before that the charts are simply empty.

    cd code/analytics
    .venv/bin/python -m services.posthog_analytics.funnels        # create/update the dashboard

Needs POSTHOG_API_KEY (a personal API key with insight/dashboard write) in .env.
POSTHOG_HOST (default https://eu.posthog.com) and POSTHOG_PROJECT_ID (auto-resolved)
are optional overrides.
"""

from __future__ import annotations

import os
from pathlib import Path

import requests
from dotenv import load_dotenv

_ANALYTICS = Path(__file__).resolve().parents[2]
load_dotenv(_ANALYTICS / ".env")

KEY = os.environ.get("POSTHOG_API_KEY", "").strip()
HOST = os.environ.get("POSTHOG_HOST", "https://eu.posthog.com").strip().rstrip("/")
if HOST.endswith("/ingest") or "i.posthog" in HOST:   # ingestion host ≠ app/API host
    HOST = "https://eu.posthog.com"
_H = {"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}

DASHBOARD_NAME = "Lead-magnet funnel"
_DATE = {"date_from": "-30d"}


def _project_id() -> int:
    pid = os.environ.get("POSTHOG_PROJECT_ID", "").strip()
    if pid:
        return int(pid)
    r = requests.get(f"{HOST}/api/projects/", headers=_H, timeout=30)
    r.raise_for_status()
    projs = r.json().get("results", [])
    if not projs:
        raise RuntimeError("no PostHog projects visible to this key")
    return projs[0]["id"]


def _base(pid: int) -> str:
    return f"{HOST}/api/projects/{pid}"


def _find(pid: int, kind: str, name: str) -> dict | None:
    """First existing insight/dashboard whose name matches (idempotency)."""
    r = requests.get(f"{_base(pid)}/{kind}/", headers=_H,
                     params={"search": name, "limit": 100}, timeout=30)
    r.raise_for_status()
    for it in r.json().get("results", []):
        if (it.get("name") or "").strip() == name:
            return it
    return None


def _upsert(pid: int, kind: str, name: str, payload: dict) -> dict:
    existing = _find(pid, kind, name)
    if existing:
        r = requests.patch(f"{_base(pid)}/{kind}/{existing['id']}/", headers=_H, json=payload, timeout=30)
    else:
        r = requests.post(f"{_base(pid)}/{kind}/", headers=_H, json={"name": name, **payload}, timeout=30)
    if r.status_code >= 300:
        raise RuntimeError(f"{kind} '{name}' failed: HTTP {r.status_code} {r.text[:300]}")
    return r.json()


# ── query builders (PostHog query schema) ────────────────────────────────────

def _funnel(breakdown: str) -> dict:
    return {"kind": "InsightVizNode", "source": {
        "kind": "FunnelsQuery",
        "series": [{"kind": "EventsNode", "event": e, "name": e} for e in
                   ("lead_form_viewed", "lead_form_submitted", "lead_subscribed")],
        "breakdownFilter": {"breakdown_type": "event", "breakdown": breakdown},
        "funnelsFilter": {"funnelVizType": "steps"},
        "dateRange": _DATE,
    }}


def _trend(event: str, breakdown: str) -> dict:
    return {"kind": "InsightVizNode", "source": {
        "kind": "TrendsQuery",
        "series": [{"kind": "EventsNode", "event": event, "name": event, "math": "total"}],
        "breakdownFilter": {"breakdown_type": "event", "breakdown": breakdown},
        "dateRange": _DATE,
    }}


INSIGHTS = [
    ("Lead funnel · by magnet",          _funnel("magnet")),
    ("Lead funnel · by feature (utm)",   _funnel("utm_content")),
    ("Form errors · by reason",          _trend("lead_form_error", "reason")),
    ("Subscriptions · by magnet",        _trend("lead_subscribed", "magnet")),
]


def main() -> int:
    if not KEY:
        raise SystemExit("POSTHOG_API_KEY not set in code/analytics/.env")
    pid = _project_id()
    print(f"PostHog project {pid} @ {HOST}\n")

    dash = _upsert(pid, "dashboards", DASHBOARD_NAME,
                   {"description": "Ad → landing → form → subscribe. Segmented by magnet + feature."})
    dash_id = dash["id"]
    print(f"✓ dashboard: {DASHBOARD_NAME}  (id {dash_id})")

    for name, query in INSIGHTS:
        ins = _upsert(pid, "insights", name, {"query": query, "dashboards": [dash_id]})
        print(f"  ✓ insight: {name}  → {HOST}/project/{pid}/insights/{ins.get('short_id')}")

    print(f"\nDashboard → {HOST}/project/{pid}/dashboard/{dash_id}")
    print("(charts are empty until the UI ships the lead_* events + ad traffic flows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
