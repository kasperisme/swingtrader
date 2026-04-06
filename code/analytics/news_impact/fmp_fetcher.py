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

_DELAY = 0.25  # seconds between requests


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
        Single async GET.  Returns parsed JSON or None on any failure.
        A 0.25s sleep is applied before every request.
        Pass base_url to override the stable base (e.g. for v3 endpoints).
        """
        await asyncio.sleep(_DELAY)
        url = f"{base_url or self.base_url}/{endpoint.lstrip('/')}"
        params = {**params, "apikey": self.api_key}
        try:
            r = await client.get(url, params=params, timeout=30.0)
            if r.status_code in (404, 204):
                logger.warning("[FMPFetcher] %s → %s %s (no data)", endpoint, r.status_code, params.get("symbol", ""))
                return None
            r.raise_for_status()
            data = r.json()
            if not data:
                logger.warning("[FMPFetcher] %s returned empty body for %s", endpoint, params.get("symbol", ""))
                return None
            return data
        except Exception as exc:
            logger.warning("[FMPFetcher] %s failed for %s: %s", endpoint, params.get("symbol", ""), exc)
            return None

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
    ) -> list[dict]:
        """
        Fetch latest stock news from FMP.

        Parameters
        ----------
        tickers : filter to these symbols (passed as comma-joined 'tickers' param).
                  None = market-wide latest news.
        limit   : max articles to return (FMP max per page: 50).
        page    : pagination offset.

        Returns
        -------
        List of dicts with keys: symbol, publishedDate, publisher, title,
        site, text, url.  Empty list on failure.
        """
        params: dict = {"page": page, "limit": limit}
        if tickers:
            params["tickers"] = ",".join(tickers)

        async with httpx.AsyncClient() as client:
            data = await self._get(client, "news/stock-latest", params)

        if not isinstance(data, list):
            logger.warning("[FMPFetcher] fetch_stock_news returned unexpected type: %s", type(data))
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
