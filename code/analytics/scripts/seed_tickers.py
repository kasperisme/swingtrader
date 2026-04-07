"""
Seed swingtrader.tickers with all actively-traded NYSE and NASDAQ stocks.

Uses FMP's company-screener endpoint (fmp.exchange_tickers) which returns
symbol, companyName, sector, industry, marketCap, price, volume, beta,
country, exchange, isActivelyTrading.

Usage:
    python scripts/seed_tickers.py
    python scripts/seed_tickers.py --exchanges NYSE          # single exchange
    python scripts/seed_tickers.py --dry-run                 # print counts only
"""

import argparse
import sys
from pathlib import Path
import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from src.fmp import fmp
from src.logging import logger
from src.db import get_supabase_client

EXCHANGES = ["NYSE", "NASDAQ"]


def fetch_tickers(client: fmp, exchanges: list[str]) -> pd.DataFrame:
    frames = []
    for exchange in exchanges:
        logger.info(f"Fetching {exchange} tickers from FMP…")
        df = client.exchange_tickers(exchange)
        df["_exchange_input"] = exchange
        frames.append(df)
        logger.info(f"  {exchange}: {len(df)} rows")
    return pd.concat(frames, axis=0, ignore_index=True)


def normalise(df: pd.DataFrame) -> list[dict]:
    rename = {
        "symbol": "symbol",
        "companyName": "company_name",
        "sector": "sector",
        "industry": "industry",
        "marketCap": "market_cap",
        "price": "price",
        "volume": "volume",
        "beta": "beta",
        "country": "country",
        "exchange": "exchange",
        "isActivelyTrading": "is_actively_trading",
    }
    available = {k: v for k, v in rename.items() if k in df.columns}
    df = df.rename(columns=available)

    keep = list(available.values())
    df = df[[c for c in keep if c in df.columns]].copy()

    # Ensure required columns exist
    if "is_actively_trading" not in df.columns:
        df["is_actively_trading"] = True

    # Normalise exchange to upper-case to match our primary key expectation
    if "exchange" in df.columns:
        df["exchange"] = df["exchange"].str.upper()

    # Coerce numeric types; replace NaN with None for JSON serialisation
    for col in ("market_cap", "volume"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
            df[col] = df[col].apply(lambda x: int(x) if pd.notna(x) else None)

    for col in ("price", "beta"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
            df[col] = df[col].apply(lambda x: float(x) if pd.notna(x) else None)

    # Drop rows with no symbol
    df = df.dropna(subset=["symbol"])

    rows = df.to_dict(orient="records")
    # Ensure any remaining float nan values (e.g. in string columns) become None
    import math
    for row in rows:
        for k, v in row.items():
            if isinstance(v, float) and math.isnan(v):
                row[k] = None
    return rows


def upsert(supabase_client, rows: list[dict], batch_size: int = 500) -> int:
    upserted = 0
    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        # Add updated_at / last_seen_at server-side via on_conflict update
        supabase_client.schema("swingtrader").table("tickers").upsert(
            batch,
            on_conflict="symbol,exchange",
        ).execute()
        upserted += len(batch)
        logger.info(f"  upserted {upserted}/{len(rows)}")
    return upserted


def main():
    parser = argparse.ArgumentParser(description="Seed swingtrader.tickers from FMP")
    parser.add_argument(
        "--exchanges",
        nargs="+",
        default=EXCHANGES,
        help="Exchanges to pull (default: NYSE NASDAQ)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and print stats without writing to Supabase",
    )
    args = parser.parse_args()

    fmp_client = fmp()
    df = fetch_tickers(fmp_client, args.exchanges)

    rows = normalise(df)
    logger.info(f"Total normalised rows: {len(rows)}")

    if args.dry_run:
        print(f"Dry-run: would upsert {len(rows)} rows")
        print(pd.DataFrame(rows).head(10).to_string(index=False))
        return

    sb = get_supabase_client()

    total = upsert(sb, rows)
    logger.info(f"Done. {total} rows upserted into swingtrader.tickers.")


if __name__ == "__main__":
    main()
