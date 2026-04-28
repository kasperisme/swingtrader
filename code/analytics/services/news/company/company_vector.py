"""
Company vector builder — orchestrates FMPFetcher → DimensionCalculator → rank_normalise
into a single clean interface.

Caches each vector to disk as JSON keyed by {ticker}_{YYYY-MM-DD}.json and persists to
Supabase after each batch so interrupted runs lose at most one batch of work.

Cache expires after 24 hours. On restart with use_cache=True, tickers already in
Supabase are loaded from there and skipped, resuming where the run left off.
"""

import asyncio
import logging
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from typing import Optional

from services.news.company.fmp_fetcher import FMPFetcher, RawCompanyData
from services.news.company.dimension_calculator import DimensionCalculator
from services.news.company.normaliser import rank_normalise
from shared.db import get_supabase_client, upsert_company_vector, load_company_vectors

logger = logging.getLogger(__name__)

_CACHE_TTL = timedelta(hours=24)
_MAX_CONCURRENT = 5  # semaphore limit for concurrent FMP fetches


@dataclass
class CompanyVector:
    ticker: str
    dimensions: dict[str, float]        # dimension_key → 0-1 rank score
    raw: dict[str, Optional[float]]     # pre-normalisation values
    metadata: dict                       # name, sector, industry, market_cap
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

def _load_cached(ticker: str) -> Optional[CompanyVector]:
    """Load from Supabase DB cache if present and within TTL."""
    try:
        client = get_supabase_client()
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
    return None


def _persist_batch(vectors: list[CompanyVector]) -> None:
    """Upsert a list of CompanyVectors to Supabase in one client session."""
    if not vectors:
        return
    client = get_supabase_client()
    for cv in vectors:
        try:
            upsert_company_vector(
                client,
                ticker=cv.ticker,
                vector_date=cv.fetched_at.date(),
                dimensions=cv.dimensions,
                raw=cv.raw,
                metadata=cv.metadata,
                fetched_at=cv.fetched_at,
            )
        except Exception as exc:
            logger.warning("[build_vectors] DB persist failed for %s: %s", cv.ticker, exc)


# ---------------------------------------------------------------------------
# Core orchestration
# ---------------------------------------------------------------------------

async def _fetch_and_calculate(
    ticker: str,
    fetcher: FMPFetcher,
    calc: DimensionCalculator,
    sem: asyncio.Semaphore,
    use_cache: bool,
    counter: list[int],   # [done, total] — mutated in-place for progress reporting
) -> tuple[str, Optional[RawCompanyData], Optional[dict]]:
    """
    Returns (ticker, raw_data, raw_dims) or (ticker, None, cached_cv) on cache hit,
    or (ticker, None, None) on failure.
    """
    if use_cache:
        cached = _load_cached(ticker)
        if cached:
            counter[0] += 1
            print(f"    [{counter[0]}/{counter[1]}] {ticker:<8} cached", flush=True)
            return ticker, None, cached  # type: ignore[return-value]

    async with sem:
        try:
            raw = await fetcher.fetch_all(ticker)
        except Exception as exc:
            counter[0] += 1
            print(f"    [{counter[0]}/{counter[1]}] {ticker:<8} FETCH ERROR: {exc}", flush=True)
            return ticker, None, None

    try:
        raw_dims = calc.calculate(raw)
    except Exception as exc:
        counter[0] += 1
        print(f"    [{counter[0]}/{counter[1]}] {ticker:<8} CALC ERROR: {exc}", flush=True)
        return ticker, raw, None

    missing = _count_missing(raw_dims)
    counter[0] += 1
    status = f"ok ({len(missing)} dims missing)" if missing else "ok"
    print(f"    [{counter[0]}/{counter[1]}] {ticker:<8} fetched  {status}", flush=True)
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
    batch_size: int = 100,
) -> list[CompanyVector]:
    """
    Build rank-normalised company vectors for a list of tickers.

    Processes tickers in batches of `batch_size`. Each batch is fetched
    concurrently, rank-normalised within the batch, persisted to Supabase and
    written to disk before the next batch starts — so an interrupted run loses
    at most one batch of work.

    On restart with use_cache=True, tickers already in Supabase (fetched within
    the last 24 hours) are loaded from there and skipped automatically.
    """
    fetcher = FMPFetcher()
    calc    = DimensionCalculator()
    sem     = asyncio.Semaphore(_MAX_CONCURRENT)

    all_vectors:  list[CompanyVector] = []
    total_cached  = 0
    total_fresh   = 0
    total_partial = 0
    total_failed  = 0

    batches = [tickers[i:i + batch_size] for i in range(0, len(tickers), batch_size)]
    n_batches = len(batches)
    print(f"Processing {len(tickers)} tickers in {n_batches} batch(es) of up to {batch_size}", flush=True)

    for batch_idx, batch in enumerate(batches, 1):
        print(f"\nBatch {batch_idx}/{n_batches} — {len(batch)} tickers", flush=True)

        counter = [0, len(batch)]
        tasks = [_fetch_and_calculate(t, fetcher, calc, sem, use_cache, counter) for t in batch]
        results = await asyncio.gather(*tasks)

        cached_vectors: list[CompanyVector]       = []
        fresh_raw:      dict[str, RawCompanyData] = {}
        fresh_dims:     dict[str, dict]           = {}
        failed:         list[str]                 = []
        partial_info:   dict[str, list[str]]      = {}

        for ticker, raw, dims in results:
            if isinstance(dims, CompanyVector):
                cached_vectors.append(dims)
            elif dims is None:
                failed.append(ticker)
            else:
                missing = _count_missing(dims)
                if missing:
                    partial_info[ticker] = missing
                fresh_raw[ticker]  = raw
                fresh_dims[ticker] = dims

        # Rank-normalise fresh tickers within this batch, then persist
        batch_vectors: list[CompanyVector] = list(cached_vectors)

        if fresh_dims:
            print(f"  Normalising {len(fresh_dims)} fresh vectors…", flush=True)
            normalised = rank_normalise(fresh_dims)
            fresh_cvs: list[CompanyVector] = []

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
                fresh_cvs.append(cv)

            print(f"  Persisting {len(fresh_cvs)} vectors to Supabase…", flush=True)
            _persist_batch(fresh_cvs)
            print(f"  Persisted.", flush=True)
            batch_vectors.extend(fresh_cvs)

        all_vectors.extend(batch_vectors)

        total_cached  += len(cached_vectors)
        total_fresh   += len(fresh_dims) - len(partial_info)
        total_partial += len(partial_info)
        total_failed  += len(failed)

        summary = (
            f"  Batch {batch_idx} done — "
            f"cached: {len(cached_vectors)}  "
            f"built: {len(fresh_dims)}  "
            f"failed: {len(failed)}"
        )
        if partial_info:
            summary += f"  partial: {len(partial_info)}"
        print(summary, flush=True)

    # Final summary
    print(f"\nBuilt vectors for {len(tickers)} tickers")
    print(f"  From cache:  {total_cached}")
    print(f"  Built fresh: {total_fresh}")
    if total_partial:
        print(f"  Partial:     {total_partial}")
    print(f"  Failed:      {total_failed}")

    return all_vectors


def normalize_all_vectors(batch_size: int = 200) -> int:
    """
    Re-run rank_normalise over the entire company_vectors universe using
    the stored raw values, then write updated dimensions back to Supabase.

    Does not re-fetch any data from FMP — purely a normalisation pass.
    Returns the number of vectors successfully updated.
    """
    client = get_supabase_client()
    rows = load_company_vectors(client)

    if not rows:
        logger.warning("[normalize_all] No vectors found in DB")
        return 0

    print(f"Loaded {len(rows)} vectors. Running rank_normalise over full universe…", flush=True)
    raw_universe = {r["ticker"]: r["raw"] for r in rows}
    normalised = rank_normalise(raw_universe)

    print(f"Persisting {len(normalised)} updated vectors in batches of {batch_size}…", flush=True)
    updated = 0
    batches = [rows[i:i + batch_size] for i in range(0, len(rows), batch_size)]

    for batch_idx, batch in enumerate(batches, 1):
        print(f"  Batch {batch_idx}/{len(batches)}…", flush=True)
        for r in batch:
            ticker = r["ticker"]
            if ticker not in normalised:
                continue
            try:
                upsert_company_vector(
                    client,
                    ticker=ticker,
                    vector_date=r["vector_date"],
                    dimensions=normalised[ticker],
                    raw=r["raw"],
                    metadata=r["metadata"],
                    fetched_at=r["fetched_at"],
                )
                updated += 1
            except Exception as exc:
                logger.warning("[normalize_all] Failed to persist %s: %s", ticker, exc)

    print(f"Done. Updated {updated}/{len(rows)} vectors.", flush=True)
    return updated


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
