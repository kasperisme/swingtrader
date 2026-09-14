"""yfinance as the fallback for the FMP reads the priced-in pipeline needs.

FMP stays primary. Its target rows carry the analyst's name and the headline
(which `vote.py` uses to match a firm to its question on the call), and it is the
only source here for earnings-call transcripts and segment revenue. yfinance has
none of those. What it does have is the rest of a reconstruction: a live price,
annual statements, the TTM valuation block, and per-firm price targets with the
date each was published. When FMP's plan runs out of bandwidth that is enough to
produce a valid row, where before the pass produced nothing.

Every function returns rows in the shape of the FMP endpoint it stands in for,
so a call site falls back with `fmp_rows or yfin.<endpoint>(ticker)` and its
parsing does not fork. Every function returns [] rather than raising, and
yfinance is imported lazily so a venv without it just has no fallback.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from functools import lru_cache

log = logging.getLogger(__name__)


@lru_cache(maxsize=64)
def _ticker(symbol: str):
    import yfinance as yf
    return yf.Ticker(symbol)


@lru_cache(maxsize=64)
def _info(symbol: str) -> dict:
    try:
        return dict(_ticker(symbol).info or {})
    except Exception as exc:                                  # noqa: BLE001
        log.debug("yfinance info unavailable for %s: %s", symbol, exc)
        return {}


def _num(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else f                              # NaN -> None


def _statement(symbol: str, attr: str, fields: dict[str, str],
               limit: int) -> list[dict]:
    """Annual statement columns (newest first) as FMP-style dicts."""
    try:
        df = getattr(_ticker(symbol), attr)
    except Exception as exc:                                  # noqa: BLE001
        log.debug("yfinance %s unavailable for %s: %s", attr, symbol, exc)
        return []
    if df is None or df.empty:
        return []
    out = []
    for col in list(df.columns)[:limit]:
        row = {"date": str(col)[:10], "calendarYear": str(col)[:4]}
        for fmp_key, yf_key in fields.items():
            row[fmp_key] = _num(df.at[yf_key, col]) if yf_key in df.index else None
        out.append(row)
    return out


# ------------------------------------------------------------ endpoints ---
def profile(symbol: str) -> list[dict]:
    """Stands in for `/v3/profile/{symbol}`."""
    i = _info(symbol)
    price = _num(i.get("currentPrice") or i.get("regularMarketPrice"))
    if not price:
        return []
    return [{"symbol": symbol, "price": price,
             "companyName": i.get("longName") or i.get("shortName") or symbol,
             "industry": i.get("industry") or "", "sector": i.get("sector") or "",
             "description": i.get("longBusinessSummary") or "",
             "mktCap": _num(i.get("marketCap"))}]


def income_statement(symbol: str, limit: int = 2) -> list[dict]:
    """Stands in for `/v3/income-statement/{symbol}?period=annual`."""
    return _statement(symbol, "income_stmt", {
        "revenue": "Total Revenue", "grossProfit": "Gross Profit",
        "operatingIncome": "Operating Income", "ebitda": "EBITDA"}, limit)


def cash_flow_statement(symbol: str, limit: int = 1) -> list[dict]:
    """Stands in for `/v3/cash-flow-statement/{symbol}?period=annual`.

    The statement's Free Cash Flow row, not `info["freeCashflow"]`: the latter
    is Yahoo's levered FCF, which for MSFT reads $16.5bn against ~$67bn
    operating-less-capex, and would wreck the reverse DCF's margin.
    """
    return _statement(symbol, "cashflow", {"freeCashFlow": "Free Cash Flow"}, limit)


def key_metrics_ttm(symbol: str) -> list[dict]:
    """Stands in for `/v3/key-metrics-ttm/{symbol}`."""
    i = _info(symbol)
    if not i.get("enterpriseValue"):
        return []
    cf = cash_flow_statement(symbol)
    fcf = cf[0].get("freeCashFlow") if cf else None
    mcap = _num(i.get("marketCap"))
    return [{"enterpriseValueTTM": _num(i.get("enterpriseValue")),
             "peRatioTTM": _num(i.get("trailingPE")),
             "evToSalesTTM": _num(i.get("enterpriseToRevenue")),
             "enterpriseValueOverEBITDATTM": _num(i.get("enterpriseToEbitda")),
             "freeCashFlowYieldTTM": (fcf / mcap) if (fcf and mcap) else None}]


def enterprise_values(symbol: str) -> list[dict]:
    """Stands in for `/v3/enterprise-values/{symbol}?limit=1`."""
    i = _info(symbol)
    if not i.get("enterpriseValue"):
        return []
    return [{"enterpriseValue": _num(i.get("enterpriseValue")),
             "marketCapitalization": _num(i.get("marketCap")),
             "addTotalDebt": _num(i.get("totalDebt")),
             "minusCashAndCashEquivalents": _num(i.get("totalCash"))}]


def price_targets(symbol: str, as_of: date | None = None,
                  window_days: int = 120) -> list[dict]:
    """Stands in for `/v4/price-target?symbol=`: one row per firm, newest first.

    Built from Yahoo's upgrades/downgrades feed, which records the target
    alongside each rating action. Two differences from FMP, both deliberate:

    * **Latest target per firm only.** The feed logs every action, so Stifel
      appears at $450 in July and $530 in September. The July number is a model
      Stifel has withdrawn; counting both would put one firm in the vote twice,
      once for a view it no longer holds.
    * **No analyst name or headline.** The feed does not carry them, so
      `vote.py` cannot match these firms to questions on the call.

    `priceWhenPosted` is the close on the day the target was published.
    """
    try:
        ud = _ticker(symbol).upgrades_downgrades
    except Exception as exc:                                  # noqa: BLE001
        log.debug("yfinance targets unavailable for %s: %s", symbol, exc)
        return []
    if ud is None or ud.empty or "currentPriceTarget" not in ud.columns:
        return []
    cutoff = as_of or date.today()
    ud = ud.sort_index(ascending=False)
    rows, seen = [], set()
    for ts, r in ud.iterrows():
        d = ts.date()
        if d > cutoff:
            continue
        if (cutoff - d).days > window_days:
            break
        tgt, firm = _num(r.get("currentPriceTarget")), r.get("Firm")
        if not tgt or tgt <= 0 or not firm or firm in seen:
            continue
        seen.add(firm)
        rows.append({"symbol": symbol, "publishedDate": d.isoformat(),
                     "analystCompany": firm, "analystName": "",
                     "priceTarget": tgt, "adjPriceTarget": tgt,
                     "newsTitle": "", "newsURL": "",
                     "priceWhenPosted": None})
    if rows:
        _attach_price_when_posted(symbol, rows)
    return rows


def _attach_price_when_posted(symbol: str, rows: list[dict]) -> None:
    first = min(date.fromisoformat(r["publishedDate"]) for r in rows)
    try:
        hist = _ticker(symbol).history(start=first - timedelta(days=7),
                                       auto_adjust=False)
    except Exception as exc:                                  # noqa: BLE001
        log.debug("yfinance history unavailable for %s: %s", symbol, exc)
        return
    if hist is None or hist.empty:
        return
    closes = {ts.date(): float(c) for ts, c in hist["Close"].items()}
    days = sorted(closes)
    for r in rows:
        d = date.fromisoformat(r["publishedDate"])
        on_or_before = [x for x in days if x <= d]
        if on_or_before:
            r["priceWhenPosted"] = closes[on_or_before[-1]]
