"""
Persistence for swingtrader.ticker_pair_stats.

Two write paths, matching the two clocks:
  - upsert_pair_calibration  — slow clock (calibrate_cli)
  - update_pair_zscore       — fast clock (zscore_cli)

Reads:
  - fetch_calibration_freshness  — decide which candidates need recalibration
  - fetch_calibrated_pairs       — pairs ready for a live z-score refresh
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Any, Optional

from shared.db import get_supabase_client

log = logging.getLogger(__name__)

_SCHEMA = "swingtrader"


def _norm_pair(a: str, b: str) -> tuple[str, str]:
    """Order-normalize a pair so ticker_a < ticker_b (matches the table CHECK)."""
    a = (a or "").upper().strip()
    b = (b or "").upper().strip()
    return (a, b) if a < b else (b, a)


def _clean_float(v: Any) -> Optional[float]:
    """Coerce to a JSON/Postgres-safe float (NaN/inf -> None)."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if (math.isnan(f) or math.isinf(f)) else f


def upsert_pair_calibration(
    ticker_a: str,
    ticker_b: str,
    *,
    hedge_ratio: Optional[float],
    coint_pvalue: Optional[float],
    half_life_days: Optional[float],
    spread_mean: Optional[float],
    spread_std: Optional[float],
    window_days: int,
    n_obs: int,
) -> None:
    """Insert or replace the calibration columns for a pair.

    The hedge ratio is orientation-sensitive (it is computed for A on B). We
    normalize the orientation so the regression in calibrate_cli is run with
    A=ticker_a, B=ticker_b, i.e. the same order stored here.
    """
    a, b = _norm_pair(ticker_a, ticker_b)
    row = {
        "ticker_a": a,
        "ticker_b": b,
        "hedge_ratio": _clean_float(hedge_ratio),
        "coint_pvalue": _clean_float(coint_pvalue),
        "half_life_days": _clean_float(half_life_days),
        "spread_mean": _clean_float(spread_mean),
        "spread_std": _clean_float(spread_std),
        "window_days": int(window_days),
        "n_obs": int(n_obs),
        "calibrated_at": datetime.now(timezone.utc).isoformat(),
    }
    (
        get_supabase_client()
        .schema(_SCHEMA)
        .table("ticker_pair_stats")
        .upsert(row, on_conflict="ticker_a,ticker_b")
        .execute()
    )


def update_pair_zscore(
    ticker_a: str,
    ticker_b: str,
    *,
    current_price_a: Optional[float],
    current_price_b: Optional[float],
    current_spread: Optional[float],
    current_zscore: Optional[float],
) -> None:
    """Update only the live-signal columns for an already-calibrated pair."""
    a, b = _norm_pair(ticker_a, ticker_b)
    patch = {
        "current_price_a": _clean_float(current_price_a),
        "current_price_b": _clean_float(current_price_b),
        "current_spread": _clean_float(current_spread),
        "current_zscore": _clean_float(current_zscore),
        "zscore_at": datetime.now(timezone.utc).isoformat(),
    }
    (
        get_supabase_client()
        .schema(_SCHEMA)
        .table("ticker_pair_stats")
        .update(patch)
        .eq("ticker_a", a)
        .eq("ticker_b", b)
        .execute()
    )


def fetch_calibration_freshness() -> dict[tuple[str, str], Optional[str]]:
    """Return {(ticker_a, ticker_b): calibrated_at_iso_or_None} for all rows.

    Used by calibrate_cli to skip pairs calibrated within the staleness window.
    """
    out: dict[tuple[str, str], Optional[str]] = {}
    client = get_supabase_client()
    page_size = 1000
    offset = 0
    while True:
        res = (
            client.schema(_SCHEMA)
            .table("ticker_pair_stats")
            .select("ticker_a, ticker_b, calibrated_at")
            .range(offset, offset + page_size - 1)
            .execute()
        )
        batch = res.data or []
        for row in batch:
            key = _norm_pair(row.get("ticker_a", ""), row.get("ticker_b", ""))
            out[key] = row.get("calibrated_at")
        if len(batch) < page_size:
            break
        offset += page_size
    return out


def fetch_calibrated_pairs() -> list[dict[str, Any]]:
    """Pairs with a usable calibration, ready for a live z-score refresh.

    Returns rows with hedge_ratio / spread_mean / spread_std present.
    """
    out: list[dict[str, Any]] = []
    client = get_supabase_client()
    page_size = 1000
    offset = 0
    while True:
        res = (
            client.schema(_SCHEMA)
            .table("ticker_pair_stats")
            .select(
                "ticker_a, ticker_b, hedge_ratio, spread_mean, spread_std, "
                "coint_pvalue, is_cointegrated, half_life_days"
            )
            .not_.is_("hedge_ratio", "null")
            .not_.is_("spread_std", "null")
            .range(offset, offset + page_size - 1)
            .execute()
        )
        batch = res.data or []
        out.extend(batch)
        if len(batch) < page_size:
            break
        offset += page_size
    return out
