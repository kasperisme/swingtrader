"""
Company vector builder — orchestrates FMPFetcher → DimensionCalculator → rank_normalise
into a single clean interface.

Caches each vector to disk as JSON keyed by {ticker}_{YYYY-MM-DD}.json.
Cache expires after 24 hours.
"""

import asyncio
import json
import logging
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from news_impact.fmp_fetcher import FMPFetcher, RawCompanyData
from news_impact.dimension_calculator import DimensionCalculator
from news_impact.normaliser import rank_normalise
from src.db import get_supabase_client, ensure_schema, upsert_company_vector, load_company_vectors

logger = logging.getLogger(__name__)

_CACHE_DIR = Path(__file__).parent / "cache"
_CACHE_TTL = timedelta(hours=24)
_MAX_CONCURRENT = 5  # semaphore limit for concurrent FMP fetches


@dataclass
class CompanyVector:
    ticker: str
    dimensions: dict[str, float]          # dimension_key → 0-1 rank score
    raw: dict[str, Optional[float]]       # pre-normalisation values
    metadata: dict                         # name, sector, industry, market_cap
    fetched_at: datetime

    def to_json(self) -> dict:
        d = asdict(self)
        d["fetched_at"] = self.fetched_at.isoformat()
        return d

    @classmethod
    def from_json(cls, data: dict) -> "CompanyVector":
        data["fetched_at"] = datetime.fromisoformat(data["fetched_at"])
        return cls(**data)


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

def _cache_path(ticker: str, date: str) -> Path:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return _CACHE_DIR / f"{ticker}_{date}.json"


def _load_cached(ticker: str) -> Optional[CompanyVector]:
    """Check DB first, then fall back to disk cache."""
    today = datetime.now(timezone.utc).date()

    # Try DB
    try:
        client = get_supabase_client()
        ensure_schema()
        rows = load_company_vectors(client, tickers=[ticker])
        if rows:
            r = rows[0]
            fetched_at = r["fetched_at"]
            if isinstance(fetched_at, str):
                fetched_at = datetime.fromisoformat(fetched_at)
            age = datetime.now(timezone.utc) - fetched_at.replace(tzinfo=timezone.utc)
            if age <= _CACHE_TTL:
                return CompanyVector(
                    ticker=ticker,
                    dimensions=r["dimensions"],
                    raw=r["raw"],
                    metadata=r["metadata"],
                    fetched_at=fetched_at,
                )
            logger.debug("[cache] DB vector for %s expired (%.1fh)", ticker, age.total_seconds() / 3600)
    except Exception as exc:
        logger.warning("[cache] DB load failed for %s: %s", ticker, exc)

    # Fall back to disk
    path = _cache_path(ticker, today.strftime("%Y-%m-%d"))
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        cv = CompanyVector.from_json(data)
        age = datetime.now(timezone.utc) - cv.fetched_at.replace(tzinfo=timezone.utc)
        if age > _CACHE_TTL:
            logger.debug("[cache] disk vector for %s expired (%.1fh)", ticker, age.total_seconds() / 3600)
            return None
        return cv
    except Exception as exc:
        logger.warning("[cache] disk load failed for %s: %s", path, exc)
        return None


def _save_cache(cv: CompanyVector) -> None:
    date = cv.fetched_at.strftime("%Y-%m-%d")
    path = _cache_path(cv.ticker, date)
    try:
        path.write_text(json.dumps(cv.to_json(), indent=2))
    except Exception as exc:
        logger.warning("[cache] failed to write %s: %s", path, exc)


# ---------------------------------------------------------------------------
# Core orchestration
# ---------------------------------------------------------------------------

async def _fetch_and_calculate(
    ticker: str,
    fetcher: FMPFetcher,
    calc: DimensionCalculator,
    sem: asyncio.Semaphore,
    use_cache: bool,
) -> tuple[str, Optional[RawCompanyData], Optional[dict]]:
    """
    Returns (ticker, raw_data, raw_dims) or (ticker, None, None) on failure.
    raw_dims values may contain None for missing dimensions.
    """
    if use_cache:
        cached = _load_cached(ticker)
        if cached:
            logger.debug("[build_vectors] %s loaded from cache", ticker)
            # Return sentinel so caller knows it came from cache
            return ticker, None, cached  # type: ignore[return-value]

    async with sem:
        try:
            raw = await fetcher.fetch_all(ticker)
        except Exception as exc:
            logger.error("[build_vectors] fetch failed for %s: %s", ticker, exc)
            return ticker, None, None

    try:
        raw_dims = calc.calculate(raw)
    except Exception as exc:
        logger.error("[build_vectors] dimension calc failed for %s: %s", ticker, exc)
        return ticker, raw, None

    return ticker, raw, raw_dims


def _extract_metadata(raw: RawCompanyData) -> dict:
    p = raw.profile
    q = raw.quote
    return {
        "name":       p.get("companyName") or p.get("name") or raw.ticker,
        "sector":     p.get("sector", ""),
        "industry":   p.get("industry", ""),
        "market_cap": q.get("marketCap") or p.get("mktCap"),
    }


def _count_missing(raw_dims: dict) -> list[str]:
    return [k for k, v in raw_dims.items() if v is None]


async def build_vectors(
    tickers: list[str],
    use_cache: bool = True,
) -> list[CompanyVector]:
    """
    Build rank-normalised company vectors for a list of tickers.

    Steps:
      1. Fetch raw FMP data (concurrently, max 5 at a time)
      2. Calculate raw dimension values per ticker
      3. Rank-normalise across the full universe in one pass
      4. Cache each vector to disk

    Returns a list of CompanyVector — one per ticker that did not fail entirely.
    Prints a progress summary on completion.
    """
    fetcher = FMPFetcher()
    calc    = DimensionCalculator()
    sem     = asyncio.Semaphore(_MAX_CONCURRENT)

    tasks = [
        _fetch_and_calculate(t, fetcher, calc, sem, use_cache)
        for t in tickers
    ]
    results = await asyncio.gather(*tasks)

    # Separate outcomes
    cached_vectors:  list[CompanyVector]          = []
    fresh_raw:       dict[str, RawCompanyData]    = {}   # ticker → RawCompanyData
    fresh_dims:      dict[str, dict]              = {}   # ticker → raw dims
    failed:          list[str]                    = []
    partial_info:    dict[str, list[str]]         = {}   # ticker → missing keys

    for ticker, raw, dims in results:
        if isinstance(dims, CompanyVector):
            # Came from cache
            cached_vectors.append(dims)
        elif dims is None:
            failed.append(ticker)
        else:
            missing = _count_missing(dims)
            if missing:
                partial_info[ticker] = missing
            fresh_raw[ticker]  = raw
            fresh_dims[ticker] = dims

    # Rank-normalise fresh tickers together (so comparisons are cross-sectional)
    vectors: list[CompanyVector] = list(cached_vectors)

    if fresh_dims:
        normalised = rank_normalise(fresh_dims)
        today = datetime.now(timezone.utc)

        for ticker, ranked in normalised.items():
            raw      = fresh_raw[ticker]
            metadata = _extract_metadata(raw)
            cv = CompanyVector(
                ticker=ticker,
                dimensions=ranked,
                raw=fresh_dims[ticker],
                metadata=metadata,
                fetched_at=raw.fetched_at,
            )
            vectors.append(cv)
            _save_cache(cv)
            # Persist to Supabase
            try:
                client = get_supabase_client()
                ensure_schema()
                upsert_company_vector(
                    client,
                    ticker=ticker,
                    vector_date=raw.fetched_at.date(),
                    dimensions=ranked,
                    raw=fresh_dims[ticker],
                    metadata=metadata,
                    fetched_at=raw.fetched_at,
                )
            except Exception as exc:
                logger.warning("[build_vectors] DB persist failed for %s: %s", ticker, exc)

    # Progress summary
    complete = [t for t in fresh_dims if t not in partial_info]
    partial  = list(partial_info.keys())

    print(f"\nBuilt vectors for {len(tickers)} tickers")
    print(f"  Complete:  {len(complete) + len(cached_vectors)}")
    if partial:
        partial_lines = ", ".join(
            f"{t}: missing {', '.join(partial_info[t][:3])}{'…' if len(partial_info[t]) > 3 else ''}"
            for t in partial
        )
        print(f"  Partial:   {len(partial)}  ({partial_lines})")
    if failed:
        print(f"  Failed:    {len(failed)}  ({', '.join(failed)})")
    else:
        print(f"  Failed:    0")

    return vectors


if __name__ == "__main__":
    import pathlib
    from dotenv import load_dotenv

    load_dotenv(pathlib.Path(__file__).parent.parent / ".env")

    async def _demo():
        vectors = await build_vectors(["AAPL", "MSFT", "JPM"], use_cache=True)
        for cv in vectors:
            print(f"\n{cv.ticker}  {cv.metadata.get('name')}")
            for k, v in cv.dimensions.items():
                print(f"  {k:<40} {v:.3f}")

    asyncio.run(_demo())
