"""search_console.py — Search Console Search Analytics queries (read-only).

The organic-search picture GA4 can't give: the actual queries you rank for, and
impressions / clicks / CTR / average position per query and per page. The
`opportunities()` view surfaces the actionable SEO wins.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any

from . import client as gc


def _date_range(days: int) -> tuple[str, str]:
    # GSC data lags ~2-3 days; end a couple days back so rows aren't half-empty.
    end = _dt.date.today() - _dt.timedelta(days=2)
    start = end - _dt.timedelta(days=days)
    return start.isoformat(), end.isoformat()


def _query(dimensions: list[str], days: int, limit: int = 100,
           filters: list[dict] | None = None) -> list[dict[str, Any]]:
    start, end = _date_range(days)
    body: dict[str, Any] = {
        "startDate": start, "endDate": end,
        "dimensions": dimensions, "rowLimit": limit,
    }
    if filters:
        body["dimensionFilterGroups"] = [{"filters": filters}]
    resp = gc.gsc_client().searchanalytics().query(siteUrl=gc.site_url(), body=body).execute()
    out = []
    for r in resp.get("rows", []):
        row = {dim: key for dim, key in zip(dimensions, r.get("keys", []))}
        row["clicks"] = r.get("clicks", 0.0)
        row["impressions"] = r.get("impressions", 0.0)
        row["ctr"] = r.get("ctr", 0.0) * 100          # → percent
        row["position"] = r.get("position", 0.0)
        out.append(row)
    return out


def summary(days: int = 28) -> dict[str, Any]:
    rows = _query([], days, limit=1)
    if rows:
        return rows[0]
    # no-dimension query returns a single totals row under keys=[]; fall back to aggregation
    q = _query(["query"], days, limit=25000)
    tot_c = sum(r["clicks"] for r in q)
    tot_i = sum(r["impressions"] for r in q)
    return {"clicks": tot_c, "impressions": tot_i,
            "ctr": (tot_c / tot_i * 100) if tot_i else 0.0,
            "position": (sum(r["position"] for r in q) / len(q)) if q else 0.0}


def queries(days: int = 28, limit: int = 50) -> list[dict[str, Any]]:
    return _query(["query"], days, limit=limit)


def pages(days: int = 28, limit: int = 50) -> list[dict[str, Any]]:
    return _query(["page"], days, limit=limit)


def opportunities(days: int = 28, min_impressions: float = 100.0,
                  limit: int = 30) -> list[dict[str, Any]]:
    """Striking-distance SEO wins: queries with real demand (impressions ≥ N),
    ranking on page 1-2 (position 4-20), but bleeding clicks to weak CTR. These are
    the pages where a title/meta rewrite moves the needle fastest."""
    rows = _query(["query", "page"], days, limit=25000)
    opps = [r for r in rows
            if r["impressions"] >= min_impressions and 4.0 <= r["position"] <= 20.0]
    # rank by lost-click potential: impressions × how far CTR sits below a rough par
    for r in opps:
        par = 0.30 if r["position"] <= 10 else 0.12         # crude CTR-by-position par
        r["lost_clicks_est"] = round(max(0.0, par - r["ctr"] / 100) * r["impressions"], 1)
    opps.sort(key=lambda r: -r["lost_clicks_est"])
    return opps[:limit]
