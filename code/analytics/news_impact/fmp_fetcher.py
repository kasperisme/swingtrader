"""
Async FMP data fetcher for company embedding system.

Fetches all raw data needed to compute dimension vectors for a single ticker.
Uses httpx.AsyncClient with a 0.25s inter-request delay to respect FMP rate limits.
Never raises on partial data failure — missing endpoints return None with a warning.
"""

import asyncio
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime

import httpx

logger = logging.getLogger(__name__)

_DELAY = 0.6          # seconds between request dispatches (global, shared across all concurrent fetchers)
_MAX_RETRIES = 3      # max retries on 429
_RETRY_DELAYS = (10.0, 30.0, 60.0)  # wait times between 429 retries

# FMP stable Stock News Feed — latest headlines/snippets/URLs per symbol (market-wide).
# https://financialmodelingprep.com/stable/news/stock-latest?page=0&limit=20&from=...&to=...
_FMP_NEWS_STOCK_LATEST = "news/stock-latest"
# Symbol-filtered search (use when caller passes tickers; not the same path as stock-latest).
# https://financialmodelingprep.com/stable/news/stock?symbols=AAPL
_FMP_NEWS_STOCK_BY_SYMBOL = "news/stock"
# General News API — cross-market headlines (symbol often null).
# https://financialmodelingprep.com/stable/news/general-latest?page=0&limit=20&from=...&to=...
_FMP_NEWS_GENERAL_LATEST = "news/general-latest"

# Module-level lock — ensures at most one FMP request is dispatched every _DELAY seconds
# regardless of how many tickers are being fetched concurrently.
_rate_lock: asyncio.Lock | None = None


def _get_rate_lock() -> asyncio.Lock:
    global _rate_lock
    if _rate_lock is None:
        _rate_lock = asyncio.Lock()
    return _rate_lock


@dataclass
class RawCompanyData:
    ticker: str
    income: list[dict]        # income-statement  (up to 5 quarters)
    balance: list[dict]       # balance-sheet-statement (up to 2 quarters)
    cashflow: list[dict]      # cash-flow-statement (up to 4 quarters)
    metrics: dict             # key-metrics (most recent period)
    ratios: dict              # ratios (most recent period)
    quote: dict               # real-time quote
    profile: dict             # company profile
    institutional: list[dict] # institutional-ownership (up to 2 periods)
    estimates: dict           # analyst-estimates (most recent)
    fetched_at: datetime = field(default_factory=datetime.utcnow)


class FMPFetcher:
    """
    Async fetcher for all FMP endpoints needed by DimensionCalculator.

    Usage:
        fetcher = FMPFetcher()
        raw = await fetcher.fetch_all("AAPL")
    """

    def __init__(self) -> None:
        # Support both the existing APIKEY convention and the new FMP_API_KEY
        self.api_key = os.environ.get("FMP_API_KEY") or os.environ.get("APIKEY", "")
        base = os.environ.get("FMP_BASE_URL", "https://financialmodelingprep.com/stable/")
        self.base_url = base.rstrip("/")
        self._v3_url = "https://financialmodelingprep.com/api/v3"

    async def _get(
        self,
        client: httpx.AsyncClient,
        endpoint: str,
        params: dict,
        base_url: str | None = None,
    ) -> list | dict | None:
        """
        Single async GET with global rate limiting and 429 retry/backoff.

        A global asyncio.Lock serialises request dispatch so all concurrent
        FMPFetcher calls share one _DELAY-second gap between sends.
        On 429 the request is retried up to _MAX_RETRIES times with
        increasing back-off delays.
        """
        url = f"{base_url or self.base_url}/{endpoint.lstrip('/')}"
        params = {**params, "apikey": self.api_key}
        sym = params.get("symbol", endpoint)

        for attempt in range(_MAX_RETRIES + 1):
            # --- global throttle: wait _DELAY seconds between dispatches ---
            async with _get_rate_lock():
                await asyncio.sleep(_DELAY)
                try:
                    r = await client.get(url, params=params, timeout=30.0)
                except Exception as exc:
                    logger.warning("[FMPFetcher] %s failed for %s: %s", endpoint, sym, exc)
                    return None

            # --- handle response outside the lock ---
            if r.status_code == 429:
                if attempt < _MAX_RETRIES:
                    wait = _RETRY_DELAYS[attempt]
                    logger.warning(
                        "[FMPFetcher] 429 on %s %s — retry %d/%d in %.0fs",
                        endpoint, sym, attempt + 1, _MAX_RETRIES, wait,
                    )
                    await asyncio.sleep(wait)
                    continue
                logger.warning("[FMPFetcher] 429 on %s %s — giving up after %d retries", endpoint, sym, _MAX_RETRIES)
                return None

            if r.status_code in (404, 204):
                logger.warning("[FMPFetcher] %s → %s %s (no data)", endpoint, r.status_code, sym)
                return None

            try:
                r.raise_for_status()
            except Exception as exc:
                logger.warning("[FMPFetcher] %s failed for %s: %s", endpoint, sym, exc)
                return None

            data = r.json()
            if not data:
                logger.warning("[FMPFetcher] %s returned empty body for %s", endpoint, sym)
                return None
            return data

        return None  # exhausted retries

    async def fetch_all(self, ticker: str) -> RawCompanyData:
        """
        Fetch all endpoints sequentially (rate-limit friendly) and return
        a RawCompanyData dataclass.  Fields with missing data are set to
        empty list / empty dict rather than None so callers can safely iterate.
        """
        async with httpx.AsyncClient() as client:
            income_raw      = await self._get(client, "income-statement",       {"symbol": ticker, "period": "quarter", "limit": 5})
            balance_raw     = await self._get(client, "balance-sheet-statement", {"symbol": ticker, "period": "quarter", "limit": 2})
            cashflow_raw    = await self._get(client, "cash-flow-statement",     {"symbol": ticker, "period": "quarter", "limit": 4})
            metrics_raw     = await self._get(client, "key-metrics",            {"symbol": ticker, "limit": 1})
            ratios_raw      = await self._get(client, "ratios",                 {"symbol": ticker, "limit": 1})
            quote_raw       = await self._get(client, "quote",                  {"symbol": ticker})
            profile_raw     = await self._get(client, "profile",                {"symbol": ticker})
            # institutional-holder is v3 only; stable endpoint returns 404
            institutional_raw = await self._get(
                client, f"institutional-holder/{ticker}", {},
                base_url=self._v3_url,
            )
            # analyst-estimates requires period param
            estimates_raw   = await self._get(client, "analyst-estimates",      {"symbol": ticker, "period": "annual", "limit": 1})

        def _as_list(data) -> list[dict]:
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                return [data]
            return []

        def _first(data) -> dict:
            if isinstance(data, list) and data:
                return data[0]
            if isinstance(data, dict):
                return data
            return {}

        return RawCompanyData(
            ticker=ticker,
            income=_as_list(income_raw),
            balance=_as_list(balance_raw),
            cashflow=_as_list(cashflow_raw),
            metrics=_first(metrics_raw),
            ratios=_first(ratios_raw),
            quote=_first(quote_raw),
            profile=_first(profile_raw),
            institutional=_as_list(institutional_raw),
            estimates=_first(estimates_raw),
            fetched_at=datetime.utcnow(),
        )


    async def fetch_stock_news(
        self,
        tickers: list[str] | None = None,
        limit: int = 20,
        page: int = 0,
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> list[dict]:
        """
        Fetch stock news from FMP stable APIs.

        **Market-wide (no tickers)** — Stock News Feed API::

            GET /stable/news/stock-latest?page=0&limit=20&from=YYYY-MM-DD&to=YYYY-MM-DD

        Headlines, snippets, publication URLs, and ticker symbols for recent articles.

        **Ticker-filtered** — Search Stock News API (FMP uses ``symbols``, not stock-latest)::

            GET /stable/news/stock?symbols=AAPL,MSFT&page=0&limit=20&from=...&to=...

        Parameters
        ----------
        tickers   : if set, calls ``news/stock`` with comma-joined ``symbols``;
                    if empty/None, calls ``news/stock-latest`` for the broad feed.
        limit     : max articles per request (FMP max 250; page max 100).
        page      : page index.
        from_date : start date ``YYYY-MM-DD`` (optional).
        to_date   : end date ``YYYY-MM-DD`` (optional).

        Returns
        -------
        List of dicts with keys such as: symbol, publishedDate, publisher, title,
        site, text, url, image. Empty list on failure.
        """
        params: dict[str, str | int] = {"page": page, "limit": limit}
        if from_date:
            params["from"] = from_date
        if to_date:
            params["to"] = to_date

        symbols = [t.strip().upper() for t in (tickers or []) if t and str(t).strip()]

        async with httpx.AsyncClient() as client:
            if symbols:
                params["symbols"] = ",".join(symbols)
                endpoint = _FMP_NEWS_STOCK_BY_SYMBOL
            else:
                endpoint = _FMP_NEWS_STOCK_LATEST
            data = await self._get(client, endpoint, params)

        if not isinstance(data, list):
            logger.warning("[FMPFetcher] fetch_stock_news returned unexpected type: %s", type(data))
            return []
        return data

    async def fetch_general_news(
        self,
        limit: int = 20,
        page: int = 0,
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> list[dict]:
        """
        Fetch latest **general** (non–ticker-scoped) news from FMP.

        Endpoint::

            GET /stable/news/general-latest?page=0&limit=20&from=YYYY-MM-DD&to=YYYY-MM-DD

        Response items match the stock news shape (``symbol`` may be ``null``).
        """
        params: dict[str, str | int] = {"page": page, "limit": limit}
        if from_date:
            params["from"] = from_date
        if to_date:
            params["to"] = to_date

        async with httpx.AsyncClient() as client:
            data = await self._get(client, _FMP_NEWS_GENERAL_LATEST, params)

        if not isinstance(data, list):
            logger.warning("[FMPFetcher] fetch_general_news returned unexpected type: %s", type(data))
            return []
        return data


if __name__ == "__main__":
    import asyncio
    from dotenv import load_dotenv
    import pathlib

    load_dotenv(pathlib.Path(__file__).parent.parent / ".env")

    async def _demo():
        fetcher = FMPFetcher()
        raw = await fetcher.fetch_all("AAPL")
        print(f"Fetched {raw.ticker} at {raw.fetched_at.isoformat()}")
        print(f"  income periods : {len(raw.income)}")
        print(f"  balance periods: {len(raw.balance)}")
        print(f"  cashflow periods:{len(raw.cashflow)}")
        print(f"  metrics keys   : {list(raw.metrics.keys())[:6]}")
        print(f"  quote price    : {raw.quote.get('price')}")
        print(f"  sector         : {raw.profile.get('sector')}")

    asyncio.run(_demo())
