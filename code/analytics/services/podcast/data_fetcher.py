"""
Live data fetcher for the podcast pipeline.

Assembles the dict that feeds the script-generation prompt. Each section is
independent — a failure or missing source for one field never blocks the others.
The fetcher logs what was filled vs. what fell back so the operator can see at
a glance which sources are healthy.

Sources:
  - top_news       → services.rag.get_top_articles + fetch_tickers_for_articles
  - watchlist      → live FMP pre-screen (NYSE+NASDAQ, SCREENER==1 & RS>80)
  - vix            → FMP /api/v3/quote/^VIX
  - earnings       → FMP earnings calendar (yesterday → tomorrow)
  - regime         → FMP daily chart on ^SPX + QQQ (SMA alignment, distribution
                       days, OBV) via services.screener.technical
  - breadth        → % of NYSE+NASDAQ quotes with price > priceAvg50 / 200 (FMP)
  - insider        → not yet sourced; field omitted until we wire FMP insider
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

from shared.db import get_supabase_client, _as_json

log = logging.getLogger(__name__)


# ── session context ────────────────────────────────────────────────────────


def session_meta(today_iso: str) -> dict[str, str]:
    """Build {weekday, session_context} from an ISO date.

    LLMs hallucinate weekdays from raw dates ("2026-05-05" → "Monday"); we pass
    these strings explicitly so the script never mis-states what day it is.
    The session_context phrase orients the listener relative to the prior
    trading session (Mon open vs. mid-week vs. weekend recap).
    """
    d = date.fromisoformat(today_iso)
    weekday = d.strftime("%A")
    if weekday == "Monday":
        ctx = "Monday's open — first read after the weekend"
    elif weekday in ("Saturday", "Sunday"):
        ctx = f"{weekday} recap — markets last traded Friday"
    else:
        prior = (d - timedelta(days=1)).strftime("%A")
        ctx = f"{weekday}'s session — coming off {prior}'s close"
    return {"weekday": weekday, "session_context": ctx}


# ── individual sections ────────────────────────────────────────────────────


def _fetch_news_24h_stats() -> tuple[int, int]:
    """Return (article_count, unique_publisher_count) for news_articles in last 24h.

    Used by the HOOK act to ground Hans's "I have read N articles from M
    sources" line in live numbers. Falls back to (0, 0) on any failure.

    Two queries:
      1. HEAD with count='exact' → accurate article total (cheap, no payload).
      2. Paginated select on `publisher` → unique publisher set. PostgREST
         caps page size at 1000 server-side, so we walk pages via .range()
         until we've covered the article total.

    The `source` column holds full URLs; `publisher` is the clean name
    ("CNBC", "WSJ", "The Motley Fool"). Publishers are folded
    case-insensitively to merge trivial dupes.
    """
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    since_iso = since.isoformat()
    log.info("Querying Supabase for news_24h stats since %s", since_iso)
    try:
        client = get_supabase_client()

        head = (
            client.schema("swingtrader")
            .table("news_articles")
            .select("id", count="exact", head=True)
            .gte("published_at", since_iso)
            .execute()
        )
        article_count = int(getattr(head, "count", 0) or 0)

        publishers: set[str] = set()
        page = 1000
        offset = 0
        pages_fetched = 0
        while offset < max(article_count, 1):
            res = (
                client.schema("swingtrader")
                .table("news_articles")
                .select("publisher")
                .gte("published_at", since_iso)
                .range(offset, offset + page - 1)
                .execute()
            )
            rows = res.data or []
            pages_fetched += 1
            if not rows:
                break
            for r in rows:
                p = (r.get("publisher") or "").strip().lower()
                if p:
                    publishers.add(p)
            if len(rows) < page:
                break
            offset += page

        source_count = len(publishers)
        log.info(
            "news_24h stats fetched: %d articles, %d unique publishers (paginated %d page(s))",
            article_count,
            source_count,
            pages_fetched,
        )
        return article_count, source_count
    except Exception as exc:
        log.warning(
            "news_24h stats fell back to 0/0 — DB query failed: %s: %s",
            type(exc).__name__,
            exc,
        )
        return 0, 0


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


_market_universe_cache: dict | None = None


def _market_universe() -> dict | None:
    """Pull NYSE+NASDAQ quotes + RS once per run; reused by watchlist + breadth.

    Returns a dict with `df_quote` (quotes merged with RS) and `df_tickers`,
    or None if the FMP fetch fails. Cached process-wide because the same
    podcast run calls both the watchlist and breadth fetchers.
    """
    global _market_universe_cache
    if _market_universe_cache is not None:
        return _market_universe_cache

    try:
        from services.screener.technical import technical
        import pandas as pd

        tech = technical()
        df_col = [tech.get_exhange_tickers(ex) for ex in ("NYSE", "NASDAQ")]
        df_tickers = pd.concat(df_col, axis=0).dropna(subset=["symbol"])
        tickers = df_tickers["symbol"].tolist()

        df_quote = tech.get_quote_prices(tickers).sort_values("symbol")
        df_rs = tech.get_change_prices(tickers)
        df_quote = df_quote.merge(df_rs, on="symbol", how="left")
    except Exception as exc:
        log.warning("market universe fetch failed: %s", exc)
        return None

    _market_universe_cache = {"df_quote": df_quote, "df_tickers": df_tickers}
    return _market_universe_cache


def _fetch_watchlist() -> list[dict]:
    """Top setups from a live NYSE+NASDAQ pre-screen.

    Mirrors the initial filter + RS definition from `ibd_screener.py`:
      1. Pull NYSE + NASDAQ tickers from FMP.
      2. Build the SCREENER flag from quote data (price > SMA200,
         SMA50 > SMA200, price > 1.25 * yearLow, price within 25% of yearHigh).
      3. Compute weighted RS (3M*2 + 6M + 1Y) → RS percentile + IBD-style
         RS_Rank (1–99).
      4. Keep rows with SCREENER == 1 and RS > 80; sort by RS desc, take top 5.

    Returns an empty list on any failure.
    """
    universe = _market_universe()
    if universe is None:
        return []

    df_quote = universe["df_quote"]
    mask = (df_quote["SCREENER"] == 1) & (df_quote["RS"] > 80)
    df_pass = df_quote[mask].sort_values("RS", ascending=False).head(5)

    if df_pass.empty:
        log.info("watchlist empty — no tickers passed SCREENER==1 & RS>80")
        return []

    watchlist: list[dict] = []
    for row in df_pass.itertuples(index=False):
        price = float(getattr(row, "price", 0.0) or 0.0)
        year_high = float(getattr(row, "yearHigh", 0.0) or 0.0)
        pct_from_pivot = ((price / year_high) - 1.0) * 100.0 if year_high else 0.0

        rs_rank_val = getattr(row, "RS_Rank", None)
        if rs_rank_val is None:
            rs_rank_val = getattr(row, "RS", 0)

        watchlist.append(
            {
                "ticker": row.symbol,
                "rs_rank": int(round(float(rs_rank_val))),
                "stage": 2,
                "pct_from_pivot": round(pct_from_pivot, 2),
                "setup_type": "Trend leader",
            }
        )

    return watchlist


def _fetch_vix() -> dict | None:
    """VIX current value + day-over-day change from FMP."""
    try:
        from services.rag.market import FMPClient

        df = FMPClient().quote_price(["^VIX"])
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

        df = FMPClient().insider_trading_latest(limit=50)
    except Exception as exc:
        log.warning("insider skipped — FMP fetch failed: %s", exc)
        return None

    if df is None or df.empty:
        log.info("insider skipped — empty FMP response")
        return None

    needed = {
        "symbol",
        "transactionType",
        "securitiesTransacted",
        "price",
        "reportingName",
    }
    if not needed.issubset(df.columns):
        log.warning(
            "insider skipped — FMP response missing fields %s", needed - set(df.columns)
        )
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
    action = (
        "purchased"
        if txn_type.startswith("P")
        else "sold" if txn_type.startswith("S") else "transacted"
    )
    shares = int(top["securitiesTransacted"])
    price = float(top["price"])
    role = str(top.get("typeOfOwner") or "Insider").split(",")[0].strip() or "Insider"
    name = str(top["reportingName"] or "").strip() or "An insider"

    return {
        "ticker": top["symbol"],
        "description": f"{role} {name} {action} {shares:,} shares at ${price:,.2f}",
    }


def _fetch_earnings() -> dict | None:
    """Biggest earnings surprise from the FMP calendar across yesterday → tomorrow.

    Widened from a same-day window so the podcast still has something to talk
    about pre-open (yesterday's after-hours prints) and so tomorrow's marquee
    names get a forward-looking mention even when today is quiet. Only rows
    with `epsActual` populated are eligible for the "surprise" pick — if the
    biggest hit is a not-yet-reported tomorrow row, we skip rather than
    fabricate a surprise number.
    """
    try:
        from services.rag.market import FMPClient

        today = date.today()
        start = str(today - timedelta(days=1))
        end = str(today + timedelta(days=1))
        df = FMPClient().earnings_calendar_range(start, end)
    except Exception as exc:
        log.warning("earnings skipped — FMP calendar failed: %s", exc)
        return None

    if df is None or df.empty:
        log.info("earnings skipped — no earnings in window %s → %s", start, end)
        return None

    if "epsActual" in df.columns and "epsEstimated" in df.columns:
        df = df.dropna(subset=["epsActual", "epsEstimated"])
        if df.empty:
            log.info("earnings skipped — no reported prints in %s → %s", start, end)
            return None
        df = df.assign(
            surprise_pct=(
                (df["epsActual"] - df["epsEstimated"]).abs()
                / df["epsEstimated"].abs().replace(0, 1)
                * 100.0
            )
        )
        top = df.sort_values("surprise_pct", ascending=False).iloc[0]
        return {
            "ticker": top["symbol"],
            "surprise_pct": round(float(top["surprise_pct"]), 1),
        }
    return None


_REGIME_LABELS = {
    "uptrend": "Bull Confirmed",
    "uptrend_under_pressure": "Uptrend Under Pressure",
    "correction": "Correction",
    "downtrend": "Downtrend",
    "qqq_lagging": "Mixed (QQQ Lagging)",
}


def _days_in_current_regime(spx_df, condition: str) -> int:
    """Count trailing sessions consistent with the current regime.

    Cheap proxy: walks SPX history from the tail and counts consecutive rows
    where `close > SMA200` matches the current regime (uptrend states require
    above the 200-day, correction/downtrend require at/below). Returns 0 if
    SMA200 hasn't built up yet.
    """
    try:
        df = spx_df.copy()
        df["SMA200"] = df["close"].rolling(window=200).mean()
        df = df.dropna(subset=["SMA200"])
        if df.empty:
            return 0
        bullish = condition in ("uptrend", "uptrend_under_pressure")
        streak = 0
        for close, sma200 in zip(
            reversed(df["close"].tolist()), reversed(df["SMA200"].tolist())
        ):
            row_bullish = close > sma200
            if row_bullish == bullish:
                streak += 1
            else:
                break
        return streak
    except Exception:
        return 0


def _fetch_regime_and_breadth() -> tuple[dict, dict]:
    """Compute regime + breadth from FMP data.

    Regime: SPX + QQQ daily charts via `technical.get_market_direction()` —
    SMA alignment (21>50>150>200), distribution-day count, OBV trend. The
    overall `condition` string is mapped to a human-readable status. Days in
    regime is a trailing streak of `close > SMA200` (matching the current
    bullish/bearish stance) on the SPX series.

    Breadth: `pct_above_50ma` / `pct_above_200ma` computed across the cached
    NYSE+NASDAQ quote universe — `priceAvg50` / `priceAvg200` are FMP fields.
    Stocks with missing or non-positive averages are dropped before the ratio.

    Returns neutral defaults on failure so the template still renders.
    """
    regime_default = {"status": "Mixed", "days_in_regime": 0}
    breadth_default = {"pct_above_50ma": 50.0, "pct_above_200ma": 50.0}

    # Regime via SPX + QQQ
    try:
        from services.screener.technical import technical

        tech = technical()
        direction = tech.get_market_direction(lookback_days=365)
        condition = direction.get("condition") or "mixed"
        status = _REGIME_LABELS.get(condition, condition.replace("_", " ").title())
        days_in_regime = _days_in_current_regime(tech.spx_df, condition) \
            if getattr(tech, "spx_df", None) is not None else 0
        regime = {"status": status, "days_in_regime": days_in_regime}
    except Exception as exc:
        log.warning("regime fell back to default — FMP fetch failed: %s", exc)
        regime = regime_default

    # Breadth from cached NYSE+NASDAQ universe
    try:
        universe = _market_universe()
        if universe is None:
            raise RuntimeError("market universe unavailable")
        df = universe["df_quote"]
        df50 = df[(df["priceAvg50"].notna()) & (df["priceAvg50"] > 0)]
        df200 = df[(df["priceAvg200"].notna()) & (df["priceAvg200"] > 0)]
        pct_50 = float((df50["price"] > df50["priceAvg50"]).mean() * 100.0) \
            if not df50.empty else breadth_default["pct_above_50ma"]
        pct_200 = float((df200["price"] > df200["priceAvg200"]).mean() * 100.0) \
            if not df200.empty else breadth_default["pct_above_200ma"]
        breadth = {
            "pct_above_50ma": round(pct_50, 1),
            "pct_above_200ma": round(pct_200, 1),
        }
    except Exception as exc:
        log.warning("breadth fell back to default — universe unavailable: %s", exc)
        breadth = breadth_default

    return regime, breadth


# ── public entrypoint ─────────────────────────────────────────────────────


async def fetch_live_data() -> dict:
    """Assemble the full data dict for the podcast script generator.

    Each section is fetched in a thread so the FMP/Supabase calls don't block
    the event loop. Failures fall back to defaults or omission, never raise.
    """
    log.info("Fetching live podcast data")

    top_news, watchlist, vix, earnings, insider, regime_breadth, news_stats = (
        await asyncio.gather(
            asyncio.to_thread(_fetch_top_news),
            asyncio.to_thread(_fetch_watchlist),
            asyncio.to_thread(_fetch_vix),
            asyncio.to_thread(_fetch_earnings),
            asyncio.to_thread(_fetch_insider),
            asyncio.to_thread(_fetch_regime_and_breadth),
            asyncio.to_thread(_fetch_news_24h_stats),
        )
    )
    regime, breadth = regime_breadth
    articles_24h, sources_24h = news_stats

    today_iso = str(date.today())
    data: dict[str, Any] = {
        "date": today_iso,
        **session_meta(today_iso),
        "regime": regime,
        "breadth": breadth,
        "vix": vix or {"current": 0, "change_pct": 0, "direction": "flat"},
        "watchlist": watchlist,
        "articles_24h": articles_24h,
        "sources_24h": sources_24h,
    }
    if top_news:
        data["top_news"] = top_news
    if earnings:
        data["earnings"] = earnings
    if insider:
        data["insider"] = insider

    log.info(
        "Live data assembled — top_news=%s, watchlist=%d, vix=%s, "
        "earnings=%s, insider=%s, regime=%s (%.1f%%/%.1f%% above 50/200MA), "
        "articles_24h=%d, sources_24h=%d",
        bool(top_news),
        len(watchlist),
        vix["current"] if vix else "missing",
        earnings["ticker"] if earnings else "none",
        insider["ticker"] if insider else "none",
        regime["status"],
        breadth["pct_above_50ma"],
        breadth["pct_above_200ma"],
        articles_24h,
        sources_24h,
    )
    return data
