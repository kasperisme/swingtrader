"""
Upload screening runs to the newsimpactscreener.com HTTP API (/api/v1/screenings).

Environment:
  SWINGTRADER_API_BASE_URL  — origin (default: https://www.newsimpactscreener.com)
  SWINGTRADER_API_KEY       — Bearer token (must include scope screenings:write) [required]

Uses the same row shape as direct Supabase inserts (see db.records_for_screening_api_rows).
"""

from __future__ import annotations

import json
import logging
import os
from datetime import date
from typing import Any, Optional

import requests

from shared.db import records_for_screening_api_rows

log = logging.getLogger(__name__)

_MAX_ROWS_PER_REQUEST = 500


def persist_market_wide_scan_via_api(
    scan_date: date,
    source: str,
    trend_template: Any,
    rs_rating: Any,
    quote: Any,
    market_json: Optional[Any] = None,
) -> int:
    """
    POST /api/v1/screenings/runs then batched POST .../rows for trend_template,
    rs_rating, and quote datasets.
    """
    base = (
        os.environ.get("SWINGTRADER_API_BASE_URL", "https://www.newsimpactscreener.com")
        .strip()
        .rstrip("/")
    )
    api_key = os.environ.get("SWINGTRADER_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "SWINGTRADER_API_KEY must be set (Bearer token with screenings:write scope)"
        )

    session = requests.Session()
    session.headers.update(
        {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
    )

    run_body: dict[str, Any] = {
        "scan_date": scan_date.isoformat(),
        "source": source,
    }
    if market_json is not None:
        if isinstance(market_json, str):
            run_body["market_json"] = json.loads(market_json) if market_json.strip() else {}
        else:
            run_body["market_json"] = market_json

    url_runs = f"{base}/api/v1/screenings/runs"
    resp = session.post(url_runs, json=run_body, timeout=120)
    if not resp.ok:
        raise RuntimeError(f"API create run failed {resp.status_code}: {resp.text[:2000]}")
    run_id = int(resp.json()["data"]["id"])

    def upload_dataset(name: str, df: Any) -> None:
        items = records_for_screening_api_rows(df, name)
        if not items:
            return
        url_rows = f"{base}/api/v1/screenings/runs/{run_id}/rows"
        for i in range(0, len(items), _MAX_ROWS_PER_REQUEST):
            chunk = items[i : i + _MAX_ROWS_PER_REQUEST]
            r2 = session.post(url_rows, json={"rows": chunk}, timeout=600)
            if not r2.ok:
                raise RuntimeError(
                    f"API append rows failed {r2.status_code} ({name}): {r2.text[:2000]}"
                )

    upload_dataset("trend_template", trend_template)
    upload_dataset("rs_rating", rs_rating)
    upload_dataset("quote", quote)

    log.info("Screening API upload complete run_id=%s", run_id)
    return run_id
