"""
Live data fetcher for the podcast pipeline.

Assembles the dict that feeds the script-generation prompt. Each section is
independent — a failure or missing source for one field never blocks the others.
The fetcher logs what was filled vs. what fell back so the operator can see at
a glance which sources are healthy.

Sources:
  - top_news       → services.rag.get_top_articles + fetch_tickers_for_articles
  - watchlist      → latest user_scan_runs row + user_scan_rows.row_data
  - vix            → FMP /api/v3/quote/^VIX
  - earnings       → FMP earnings calendar (today)
  - regime/breadth → user_scan_runs.market_json (latest), else defaults
  - insider        → not yet sourced; field omitted until we wire FMP insider
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date
from typing import Any

from shared.db import get_supabase_client, _as_json

log = logging.getLogger(__name__)


# ── individual sections ────────────────────────────────────────────────────

def _fetch_top_news() -> dict | None:
    """Highest-impact article from the last 14h, with associated ticker.

    impact_score is rescaled from raw magnitude into a 0-10 scale by clipping
    at a typical max of ~5 (most articles fall under 3).
    """
    try:
        from services.rag import get_top_articles, fetch_tickers_for_articles
    except Exception as exc:
        log.warning("top_news skipped — RAG import failed: %s", exc)
        return None

    try:
        articles = get_top_articles(hours=14, limit=5)
    except Exception as exc:
        log.warning("top_news skipped — get_top_articles failed: %s", exc)
        return None

    if not articles:
        log.info("top_news skipped — no articles in last 14h")
        return None

    top = articles[0]
    tickers_map = fetch_tickers_for_articles([top["id"]])
    tickers = tickers_map.get(top["id"], [])
    ticker = tickers[0] if tickers else "MARKET"

    magnitude = float(top.get("magnitude") or 0.0)
    impact_score = round(min(magnitude / 5.0 * 10.0, 10.0), 1)

    top_dims = top.get("top_dimensions") or []
    factor_summary = ", ".join(str(d) for d in top_dims[:3]) or "Multi-factor impact"

    return {
        "ticker": ticker,
        "impact_score": impact_score,
        "headline": top.get("title") or "",
        "factor_summary": factor_summary,
    }


def _fetch_watchlist() -> list[dict]:
    """Top setups from the latest market-wide scan run.

    Pulls scan rows ordered by RS rank (descending) and maps each row's
    `row_data` JSON into the watchlist contract. Falls back to an empty list.
    """
    try:
        client = get_supabase_client()
        runs = (
            client.schema("swingtrader")
            .table("user_scan_runs")
            .select("id")
            .or_("status.eq.active,status.is.null")
            .order("scan_date", desc=True)
            .order("id", desc=True)
            .limit(1)
            .execute()
        ).data or []
        if not runs:
            log.info("watchlist skipped — no scan runs found")
            return []

        run_id = runs[0]["id"]
        rows = (
            client.schema("swingtrader")
            .table("user_scan_rows")
            .select("symbol, row_data")
            .eq("run_id", run_id)
            .limit(200)
            .execute()
        ).data or []
    except Exception as exc:
        log.warning("watchlist skipped — DB query failed: %s", exc)
        return []

    watchlist: list[dict] = []
    for r in rows:
        rd = _as_json(r.get("row_data"), default={}) or {}
        rs = rd.get("rs_rank") or rd.get("rsRank") or rd.get("rs")
        try:
            rs_num = float(rs) if rs is not None else None
        except (TypeError, ValueError):
            rs_num = None
        if rs_num is None:
            continue
        watchlist.append({
            "ticker": r["symbol"],
            "rs_rank": int(rs_num),
            "stage": rd.get("stage") or 2,
            "pct_from_pivot": float(rd.get("pct_from_pivot") or rd.get("pctFromPivot") or 0.0),
            "setup_type": rd.get("setup_type") or rd.get("setupType") or "Base",
        })

    watchlist.sort(key=lambda x: x["rs_rank"], reverse=True)
    return watchlist[:5]


def _fetch_vix() -> dict | None:
    """VIX current value + day-over-day change from FMP."""
    try:
        from services.rag.market import FMPClient
        df = FMPClient.quote_price(["^VIX"])
    except Exception as exc:
        log.warning("vix skipped — FMP fetch failed: %s", exc)
        return None

    if df is None or df.empty:
        log.warning("vix skipped — empty FMP response")
        return None

    row = df.iloc[0]
    current = float(row.get("price") or 0.0)
    change_pct = float(row.get("changesPercentage") or 0.0)
    if not current:
        return None

    return {
        "current": round(current, 2),
        "change_pct": round(change_pct, 2),
        "direction": "down" if change_pct < 0 else "up",
    }


def _fetch_insider() -> dict | None:
    """Most notable recent insider transaction (highest dollar value).

    Pulls the latest cross-market insider feed and picks the row with the
    largest `securitiesTransacted * price`, formatting it for the prompt.
    Buys are tagged "purchased", sales "sold". Returns None on any failure.
    """
    try:
        from services.rag.market import FMPClient
        df = FMPClient.insider_trading_latest(limit=50)
    except Exception as exc:
        log.warning("insider skipped — FMP fetch failed: %s", exc)
        return None

    if df is None or df.empty:
        log.info("insider skipped — empty FMP response")
        return None

    needed = {"symbol", "transactionType", "securitiesTransacted", "price", "reportingName"}
    if not needed.issubset(df.columns):
        log.warning("insider skipped — FMP response missing fields %s", needed - set(df.columns))
        return None

    df = df.copy()
    df["securitiesTransacted"] = df["securitiesTransacted"].fillna(0).astype(float)
    df["price"] = df["price"].fillna(0).astype(float)
    df["dollar_value"] = (df["securitiesTransacted"] * df["price"]).abs()

    df = df[df["dollar_value"] > 0]
    if df.empty:
        return None

    top = df.sort_values("dollar_value", ascending=False).iloc[0]
    txn_type = str(top["transactionType"] or "").upper()
    action = "purchased" if txn_type.startswith("P") else "sold" if txn_type.startswith("S") else "transacted"
    shares = int(top["securitiesTransacted"])
    price = float(top["price"])
    role = str(top.get("typeOfOwner") or "Insider").split(",")[0].strip() or "Insider"
    name = str(top["reportingName"] or "").strip() or "An insider"

    return {
        "ticker": top["symbol"],
        "description": f"{role} {name} {action} {shares:,} shares at ${price:,.2f}",
    }


def _fetch_earnings() -> dict | None:
    """Today's biggest earnings surprise from the FMP calendar."""
    try:
        from services.rag.market import FMPClient
        today = str(date.today())
        df = FMPClient.earnings_calendar_range(today, today)
    except Exception as exc:
        log.warning("earnings skipped — FMP calendar failed: %s", exc)
        return None

    if df is None or df.empty:
        log.info("earnings skipped — no earnings reported today")
        return None

    if "epsActual" in df.columns and "epsEstimated" in df.columns:
        df = df.dropna(subset=["epsActual", "epsEstimated"])
        if df.empty:
            return None
        df = df.assign(surprise_pct=(
            (df["epsActual"] - df["epsEstimated"]).abs() /
            df["epsEstimated"].abs().replace(0, 1) * 100.0
        ))
        top = df.sort_values("surprise_pct", ascending=False).iloc[0]
        return {
            "ticker": top["symbol"],
            "surprise_pct": round(float(top["surprise_pct"]), 1),
        }
    return None


def _fetch_regime_and_breadth() -> tuple[dict, dict]:
    """Read regime + breadth from the latest scan run's market_json if persisted,
    otherwise return neutral defaults so the script template still renders."""
    regime_default = {"status": "Mixed", "days_in_regime": 0}
    breadth_default = {"pct_above_50ma": 50.0, "pct_above_200ma": 50.0}

    try:
        client = get_supabase_client()
        runs = (
            client.schema("swingtrader")
            .table("user_scan_runs")
            .select("market_json")
            .order("scan_date", desc=True)
            .order("id", desc=True)
            .limit(1)
            .execute()
        ).data or []
    except Exception as exc:
        log.warning("regime/breadth fell back to defaults — DB query failed: %s", exc)
        return regime_default, breadth_default

    if not runs:
        log.info("regime/breadth fell back to defaults — no scan runs found")
        return regime_default, breadth_default

    market = _as_json(runs[0].get("market_json"), default={}) or {}
    regime = {
        "status": market.get("regime_status") or regime_default["status"],
        "days_in_regime": int(market.get("days_in_regime") or 0),
    }
    breadth = {
        "pct_above_50ma": float(
            market.get("pct_above_50ma") or breadth_default["pct_above_50ma"]
        ),
        "pct_above_200ma": float(
            market.get("pct_above_200ma") or breadth_default["pct_above_200ma"]
        ),
    }
    return regime, breadth


# ── public entrypoint ─────────────────────────────────────────────────────

async def fetch_live_data() -> dict:
    """Assemble the full data dict for the podcast script generator.

    Each section is fetched in a thread so the FMP/Supabase calls don't block
    the event loop. Failures fall back to defaults or omission, never raise.
    """
    log.info("Fetching live podcast data")

    top_news, watchlist, vix, earnings, insider, regime_breadth = await asyncio.gather(
        asyncio.to_thread(_fetch_top_news),
        asyncio.to_thread(_fetch_watchlist),
        asyncio.to_thread(_fetch_vix),
        asyncio.to_thread(_fetch_earnings),
        asyncio.to_thread(_fetch_insider),
        asyncio.to_thread(_fetch_regime_and_breadth),
    )
    regime, breadth = regime_breadth

    data: dict[str, Any] = {
        "date": str(date.today()),
        "regime": regime,
        "breadth": breadth,
        "vix": vix or {"current": 0, "change_pct": 0, "direction": "flat"},
        "watchlist": watchlist,
    }
    if top_news:
        data["top_news"] = top_news
    if earnings:
        data["earnings"] = earnings
    if insider:
        data["insider"] = insider

    log.info(
        "Live data assembled — top_news=%s, watchlist=%d, vix=%s, "
        "earnings=%s, insider=%s, regime=%s (%.1f%%/%.1f%% above 50/200MA)",
        bool(top_news), len(watchlist),
        vix["current"] if vix else "missing",
        earnings["ticker"] if earnings else "none",
        insider["ticker"] if insider else "none",
        regime["status"],
        breadth["pct_above_50ma"], breadth["pct_above_200ma"],
    )
    return data
