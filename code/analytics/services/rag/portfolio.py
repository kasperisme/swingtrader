"""
User portfolio retrieval — positions, alerts, screening notes, trading strategy.

Extracted from services/agent/data_queries.py (user-scoped functions).
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

from shared.db import get_supabase_client, _as_json

log = logging.getLogger(__name__)


def _client():
    return get_supabase_client(), "swingtrader"


def get_user_positions(user_id: str) -> list[dict[str, Any]]:
    """Net open position per ticker from user_trades.

    Returns: [{ticker, net_qty, side, avg_cost}].
    net_qty > 0 = long, < 0 = short.
    """
    client, schema = _client()
    res = (
        client.schema(schema)
        .table("user_trades")
        .select("ticker,side,position_side,quantity,price_per_unit")
        .eq("user_id", user_id)
        .execute()
    )

    net_qty: dict[str, float] = defaultdict(float)
    buy_value: dict[str, float] = defaultdict(float)
    buy_qty: dict[str, float] = defaultdict(float)

    for t in (res.data or []):
        ticker = t["ticker"]
        qty = float(t["quantity"])
        side = t["side"]
        pos_side = t["position_side"]
        if side == "buy" and pos_side == "long":
            net_qty[ticker] += qty
        elif side == "sell" and pos_side == "long":
            net_qty[ticker] -= qty
        elif side == "sell" and pos_side == "short":
            net_qty[ticker] += qty
        elif side == "buy" and pos_side == "short":
            net_qty[ticker] -= qty
        if side == "buy":
            buy_value[ticker] += qty * float(t["price_per_unit"])
            buy_qty[ticker] += qty

    out = []
    for ticker in sorted(net_qty):
        nq = net_qty[ticker]
        if nq == 0:
            continue
        avg = round(buy_value[ticker] / buy_qty[ticker], 2) if buy_qty[ticker] else None
        out.append({
            "ticker": ticker,
            "net_qty": nq,
            "side": "long" if nq > 0 else "short",
            "avg_cost": avg,
        })
    return out


def get_user_alerts(user_id: str) -> list[dict[str, Any]]:
    """Active price alerts enriched with latest price and proximity.

    Returns: [{ticker, alert_type, alert_price, direction, notes, latest_price, pct_away}].
    """
    client, schema = _client()
    alert_rows = (
        client.schema(schema)
        .table("user_portfolio_alerts")
        .select("ticker,alert_type,price,direction,notes")
        .eq("user_id", user_id)
        .eq("is_active", True)
        .order("ticker").order("alert_type")
        .execute()
    ).data or []

    if not alert_rows:
        return []

    alert_tickers = list({r["ticker"] for r in alert_rows})
    scan_rows = (
        client.schema(schema)
        .table("user_scan_rows")
        .select("symbol,row_data,scan_date,id")
        .eq("user_id", user_id)
        .in_("symbol", alert_tickers)
        .order("scan_date", desc=True)
        .order("id", desc=True)
        .execute()
    ).data or []

    price_map: dict[str, float] = {}
    for r in scan_rows:
        sym = r["symbol"]
        if sym in price_map:
            continue
        row_data = _as_json(r.get("row_data"), default={})
        close = row_data.get("close")
        if close is not None:
            try:
                price_map[sym] = float(close)
            except (TypeError, ValueError):
                pass

    out = []
    for r in alert_rows:
        ticker = r["ticker"]
        alert_price = float(r["price"])
        latest = price_map.get(ticker)
        pct_away = (
            round((latest - alert_price) / alert_price * 100, 2)
            if latest and alert_price > 0
            else None
        )
        out.append({
            "ticker": ticker,
            "alert_type": r["alert_type"],
            "alert_price": alert_price,
            "direction": r["direction"],
            "notes": r["notes"],
            "latest_price": latest,
            "pct_away": pct_away,
        })
    return out


def get_user_screening_notes(user_id: str) -> list[str]:
    """Active screening tickers from the user's latest scan run."""
    client, schema = _client()
    runs = (
        client.schema(schema)
        .table("user_scan_runs")
        .select("id")
        .eq("user_id", user_id)
        .or_("status.eq.active,status.is.null")
        .order("scan_date", desc=True)
        .order("id", desc=True)
        .limit(1)
        .execute()
    ).data or []

    if not runs:
        return []

    run_id = runs[0]["id"]
    notes = (
        client.schema(schema)
        .table("user_scan_row_notes")
        .select("ticker")
        .eq("user_id", user_id)
        .eq("run_id", run_id)
        .eq("status", "active")
        .execute()
    ).data or []

    return sorted({
        r["ticker"].strip()
        for r in notes
        if r.get("ticker") and r["ticker"].strip()
    })


def get_user_trading_strategy(user_id: str) -> str:
    """Return the user's saved trading strategy text, or empty string if none."""
    client, schema = _client()
    res = (
        client.schema(schema)
        .table("user_trading_strategy")
        .select("strategy")
        .eq("user_id", user_id)
        .maybe_single()
        .execute()
    )
    if res is None or res.data is None:
        return ""
    return res.data.get("strategy") or ""


def get_ticker_chat_history(
    user_id: str,
    ticker: str,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Per-ticker AI workspace chat history for one ticker.

    Reads ``swingtrader.user_ticker_chart_workspace.ai_chat_messages`` and
    returns the most recent ``limit`` turns. Bulk-analysis runs append their
    user + assistant turns to this same array with ``source="bulk_analysis"``,
    so prior bulk-analysis answers are visible here — there is no need for a
    separate bulk-analysis tool.

    Each returned item: ``{role, content, source, created_at}``. Content is
    truncated to 1500 chars to keep the agent's context budget sane.
    """
    sym = (ticker or "").strip().upper()
    if not sym or not user_id:
        return []

    client, schema = _client()
    res = (
        client.schema(schema)
        .table("user_ticker_chart_workspace")
        .select("ai_chat_messages, updated_at")
        .eq("user_id", user_id)
        .eq("ticker", sym)
        .maybe_single()
        .execute()
    )
    if res is None or res.data is None:
        return []

    raw = res.data.get("ai_chat_messages")
    raw = _as_json(raw) if isinstance(raw, str) else raw
    if not isinstance(raw, list):
        return []

    try:
        cap = max(1, int(limit))
    except (TypeError, ValueError):
        cap = 20
    tail = raw[-cap:]

    out: list[dict[str, Any]] = []
    for m in tail:
        if not isinstance(m, dict):
            continue
        content = m.get("content", "")
        if isinstance(content, str) and len(content) > 1500:
            content = content[:1500] + "…"
        out.append({
            "role": m.get("role"),
            "content": content,
            "source": m.get("source"),
            "created_at": m.get("created_at") or m.get("ts"),
        })
    return out
