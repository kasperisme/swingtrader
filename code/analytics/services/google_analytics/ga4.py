"""ga4.py — GA4 Data API queries (read-only). Each returns plain list[dict] rows
so the CLI and any downstream (reconcile against Meta/Supabase) can consume them.

Acquisition, landing pages, conversions, geo — the picture Vercel/PostHog don't give.
"""

from __future__ import annotations

from typing import Any

from . import client as gc


def _run(dimensions: list[str], metrics: list[str], days: int,
         order_by_metric: str | None = None, limit: int = 25,
         dimension_filter=None) -> list[dict[str, Any]]:
    from google.analytics.data_v1beta.types import (
        DateRange, Dimension, Metric, OrderBy, RunReportRequest,
    )
    req = RunReportRequest(
        property=f"properties/{gc.property_id()}",
        date_ranges=[DateRange(start_date=f"{days}daysAgo", end_date="today")],
        dimensions=[Dimension(name=d) for d in dimensions],
        metrics=[Metric(name=m) for m in metrics],
        limit=limit,
    )
    if order_by_metric:
        req.order_bys = [OrderBy(metric=OrderBy.MetricOrderBy(metric_name=order_by_metric), desc=True)]
    if dimension_filter is not None:
        req.dimension_filter = dimension_filter
    resp = gc.ga4_client().run_report(req)
    rows = []
    for r in resp.rows:
        row: dict[str, Any] = {}
        for d, v in zip(dimensions, r.dimension_values):
            row[d] = v.value
        for m, v in zip(metrics, r.metric_values):
            try:
                row[m] = float(v.value)
            except (TypeError, ValueError):
                row[m] = v.value
        rows.append(row)
    return rows


def summary(days: int = 28) -> dict[str, Any]:
    rows = _run([], ["sessions", "totalUsers", "newUsers", "screenPageViews",
                     "engagementRate", "conversions"], days, limit=1)
    return rows[0] if rows else {}


def channels(days: int = 28) -> list[dict[str, Any]]:
    """Acquisition by default channel group — organic vs paid vs direct vs referral."""
    return _run(["sessionDefaultChannelGroup"],
                ["sessions", "totalUsers", "engagementRate", "conversions"],
                days, order_by_metric="sessions")


def landing_pages(days: int = 28, limit: int = 25) -> list[dict[str, Any]]:
    """Where sessions start + how they engage/convert — the CRO view."""
    return _run(["landingPagePlusQueryString"],
                ["sessions", "engagementRate", "conversions", "totalUsers"],
                days, order_by_metric="sessions", limit=limit)


def top_pages(days: int = 28, limit: int = 25) -> list[dict[str, Any]]:
    return _run(["pagePath"], ["screenPageViews", "engagementRate", "conversions"],
                days, order_by_metric="screenPageViews", limit=limit)


def conversions(days: int = 28, limit: int = 25) -> list[dict[str, Any]]:
    """Key events / conversions by name."""
    return _run(["eventName"], ["conversions", "eventCount"],
                days, order_by_metric="conversions", limit=limit)


def geo(days: int = 28, limit: int = 15) -> list[dict[str, Any]]:
    return _run(["country"], ["sessions", "conversions", "engagementRate"],
                days, order_by_metric="sessions", limit=limit)


def form_funnel(days: int = 28) -> dict[str, int]:
    """GA4's view of the form step: `form_start` / `form_submit` (auto-tracked) +
    our `sign_up` (custom). NB: GA4's auto `form_submit` often misses React/SPA
    submits — cross-check `sign_up` and the Supabase leads truth."""
    from google.analytics.data_v1beta.types import Filter, FilterExpression
    names = ["form_start", "form_submit", "sign_up", "generate_lead"]
    flt = FilterExpression(filter=Filter(
        field_name="eventName", in_list_filter=Filter.InListFilter(values=names)))
    rows = _run(["eventName"], ["eventCount"], days, dimension_filter=flt, limit=25)
    out = {n: 0 for n in names}
    for r in rows:
        out[r["eventName"]] = int(r.get("eventCount", 0))
    return out
