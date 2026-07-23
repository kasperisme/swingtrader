"""discover.py — list the GA4 properties and Search Console sites the service
account can already see, so you can fill GA4_PROPERTY_ID / GSC_SITE_URL without
hunting through the consoles. Read-only.
"""

from __future__ import annotations

from typing import Any

from . import client as gc


def ga4_properties() -> list[dict[str, Any]]:
    """Every GA4 property the service account has been granted access to."""
    from google.analytics.admin_v1beta import AnalyticsAdminServiceClient
    admin = AnalyticsAdminServiceClient(credentials=gc._credentials())
    out = []
    for acct in admin.list_account_summaries():
        for p in acct.property_summaries:
            out.append({
                "property_id": p.property.split("/")[-1],   # the numeric id for GA4_PROPERTY_ID
                "property_name": p.display_name,
                "account": acct.display_name,
            })
    return out


def gsc_sites() -> list[dict[str, Any]]:
    """Every Search Console site the service account can read."""
    resp = gc.gsc_client().sites().list().execute()
    return [{"site_url": s.get("siteUrl"), "permission": s.get("permissionLevel")}
            for s in resp.get("siteEntry", [])]
