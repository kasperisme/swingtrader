"""
CLI entry point for the company vector builder.

Usage:
    # Individual tickers
    python -m news_impact.build_vectors_cli --tickers AAPL MSFT NVDA JPM XOM

    # From a file (one ticker per line)
    python -m news_impact.build_vectors_cli --file tickers.txt

    # Entire exchange — fetches all active, non-ETF/fund tickers via FMP screener
    python -m news_impact.build_vectors_cli --exchange NASDAQ
    python -m news_impact.build_vectors_cli --exchange NYSE NASDAQ

    # Exchange with filters to keep only liquid large-caps
    python -m news_impact.build_vectors_cli --exchange NASDAQ --min-mktcap 1e9 --min-price 5

    # Show compact dimension table for each ticker after building
    python -m news_impact.build_vectors_cli --tickers AAPL MSFT --show

    # Force fresh data (bypass disk cache)
    python -m news_impact.build_vectors_cli --tickers AAPL --no-cache
"""

import argparse
import asyncio
import os
import pathlib
import sys

import requests
from dotenv import load_dotenv

load_dotenv(pathlib.Path(__file__).parent.parent / ".env")

from news_impact.company_vector import build_vectors, CompanyVector


# ---------------------------------------------------------------------------
# Exchange ticker fetching
# ---------------------------------------------------------------------------

def _fetch_exchange_tickers(
    exchanges: list[str],
    min_mktcap: float | None,
    min_price: float | None,
) -> list[str]:
    """
    Fetch all active non-ETF/fund tickers for the given exchanges via the
    FMP company screener, then apply optional market-cap and price filters.
    Returns a deduplicated, sorted list of ticker symbols.
    """
    import pandas as pd

    apikey = os.environ.get("APIKEY")
    if not apikey:
        print("Error: APIKEY not set in .env", file=sys.stderr)
        sys.exit(1)

    frames: list[pd.DataFrame] = []
    for exchange in exchanges:
        url = (
            f"https://financialmodelingprep.com/stable/company-screener"
            f"?exchange={exchange}&isEtf=false&isFund=false&isActivelyTrading=true&limit=10000"
        )
        print(f"Fetching {exchange} tickers from FMP screener…")
        r = requests.get(url, params={"apikey": apikey}, timeout=30)
        if r.status_code != 200:
            print(f"Error: FMP screener returned {r.status_code} for {exchange}", file=sys.stderr)
            sys.exit(1)
        data = r.json()
        if not data:
            print(f"Warning: no tickers returned for {exchange}")
            continue
        frames.append(pd.json_normalize(data))

    if not frames:
        print("Error: no tickers fetched from any exchange", file=sys.stderr)
        sys.exit(1)

    df = pd.concat(frames, ignore_index=True).drop_duplicates(subset="symbol")

    total_before = len(df)

    if min_mktcap is not None and "marketCap" in df.columns:
        df = df[pd.to_numeric(df["marketCap"], errors="coerce").fillna(0) >= min_mktcap]

    if min_price is not None and "price" in df.columns:
        df = df[pd.to_numeric(df["price"], errors="coerce").fillna(0) >= min_price]

    tickers = sorted(df["symbol"].dropna().str.upper().unique().tolist())
    print(f"  {total_before} tickers fetched → {len(tickers)} after filters")
    return tickers


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

_CLUSTER_SHORT = {
    "MACRO_SENSITIVITY":    "MACRO",
    "SECTOR_ROTATION":      "SECTOR",
    "BUSINESS_MODEL":       "BUSINESS",
    "FINANCIAL_STRUCTURE":  "FINANCIAL",
    "GROWTH_PROFILE":       "GROWTH",
    "VALUATION_POSITIONING":"VALUATION",
    "GEOGRAPHY_TRADE":      "GEOGRAPHY",
    "MARKET_BEHAVIOUR":     "MARKET",
}

_DISPLAY_KEYS: dict[str, list[tuple[str, str]]] = {
    "GROWTH_PROFILE": [
        ("revenue_growth_rate",      "rev_growth"),
        ("eps_growth_rate",          "eps_growth"),
        ("eps_acceleration",         "acceleration"),
    ],
    "VALUATION_POSITIONING": [
        ("valuation_multiple",       "multiple"),
        ("factor_value",             "value"),
        ("price_momentum",           "momentum"),
    ],
    "FINANCIAL_STRUCTURE": [
        ("debt_burden",              "debt"),
        ("financial_health",         "health"),
        ("earnings_quality",         "quality"),
    ],
    "MACRO_SENSITIVITY": [
        ("interest_rate_sensitivity","rate_sens"),
        ("dollar_sensitivity",       "dollar"),
        ("inflation_sensitivity",    "inflation"),
    ],
    "SECTOR_ROTATION": [
        ("sector_technology",        "tech"),
        ("sector_financials",        "finl"),
        ("sector_healthcare",        "hlth"),
        ("sector_energy",            "enrg"),
    ],
    "BUSINESS_MODEL": [
        ("revenue_recurring",        "recurring"),
        ("pricing_power",            "pricing"),
        ("capex_intensity",          "capex"),
    ],
    "GEOGRAPHY_TRADE": [
        ("china_revenue_exposure",   "china"),
        ("domestic_revenue_concentration", "domestic"),
        ("tariff_sensitivity",       "tariff"),
    ],
    "MARKET_BEHAVIOUR": [
        ("institutional_appeal",     "inst_appeal"),
        ("institutional_ownership_change", "inst_chg"),
    ],
}


def _fmt_mktcap(val) -> str:
    if val is None:
        return "N/A"
    try:
        v = float(val)
    except (TypeError, ValueError):
        return "N/A"
    if v >= 1e12:
        return f"${v/1e12:.1f}T"
    if v >= 1e9:
        return f"${v/1e9:.1f}B"
    if v >= 1e6:
        return f"${v/1e6:.1f}M"
    return f"${v:.0f}"


def _print_vector(cv: CompanyVector) -> None:
    width = 55
    sep = "━" * width
    name   = cv.metadata.get("name", cv.ticker)
    sector = cv.metadata.get("sector", "")
    mktcap = _fmt_mktcap(cv.metadata.get("market_cap"))

    print(f"\n{sep}")
    print(f"{cv.ticker}  {name}  |  {sector}  |  {mktcap}")
    print(sep)

    dims = cv.dimensions
    for cluster_name, pairs in _DISPLAY_KEYS.items():
        label = _CLUSTER_SHORT.get(cluster_name, cluster_name)
        parts = []
        for key, short in pairs:
            score = dims.get(key)
            parts.append(f"{short}: {score:.2f}" if score is not None else f"{short}: n/a")
        print(f"{label:<12} {'  '.join(parts)}")

    print()


# ---------------------------------------------------------------------------
# Argument parsing & main
# ---------------------------------------------------------------------------

def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m news_impact.build_vectors_cli",
        description="Build rank-normalised company embedding vectors.",
    )

    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--tickers", nargs="+", metavar="TICKER",
        help="Space-separated list of ticker symbols",
    )
    source.add_argument(
        "--file", metavar="PATH",
        help="Text file with one ticker per line",
    )
    source.add_argument(
        "--exchange", nargs="+", metavar="EXCHANGE",
        help="Fetch all active tickers from one or more exchanges (e.g. NASDAQ NYSE)",
    )
    source.add_argument(
        "--from-db", action="store_true",
        help="Refresh all tickers that already have a vector in Supabase",
    )

    parser.add_argument(
        "--min-mktcap", type=float, default=None, metavar="DOLLARS",
        help="Skip tickers with market cap below this value (e.g. 1e9 for $1B). Exchange mode only.",
    )
    parser.add_argument(
        "--min-price", type=float, default=None, metavar="DOLLARS",
        help="Skip tickers priced below this value (e.g. 5). Exchange mode only.",
    )
    parser.add_argument(
        "--batch-size", type=int, default=100, metavar="N",
        help="Tickers per batch — vectors are persisted to Supabase after each batch "
             "so interrupted runs lose at most one batch of work (default: 100)",
    )
    parser.add_argument(
        "--show", action="store_true",
        help="Print a compact dimension table for each ticker after building",
    )
    parser.add_argument(
        "--no-cache", dest="no_cache", action="store_true",
        help="Bypass disk/DB cache and fetch fresh data from FMP",
    )
    return parser.parse_args(argv)


def _load_tickers_from_file(path: str) -> list[str]:
    p = pathlib.Path(path)
    if not p.exists():
        print(f"Error: file not found: {path}", file=sys.stderr)
        sys.exit(1)
    tickers = [
        line.strip().upper()
        for line in p.read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]
    if not tickers:
        print(f"Error: no tickers found in {path}", file=sys.stderr)
        sys.exit(1)
    return tickers


def _fetch_tickers_from_db() -> list[str]:
    """Return the distinct set of tickers that already have a vector in Supabase."""
    import pathlib as _pl
    _root = _pl.Path(__file__).resolve().parent.parent
    import importlib.util as _ilu
    _spec = _ilu.spec_from_file_location("swingtrader_db", _root / "src" / "db.py")
    _mod = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)

    client = _mod.get_supabase_client()
    _mod.ensure_schema()
    schema = _mod.get_schema()

    res = (
        client.schema(schema).table("company_vectors")
        .select("ticker")
        .execute()
    )
    tickers = sorted({row["ticker"] for row in (res.data or []) if row.get("ticker")})
    if not tickers:
        print("No tickers found in Supabase company_vectors table.", file=sys.stderr)
        sys.exit(1)
    print(f"Found {len(tickers)} ticker(s) in Supabase to refresh.")
    return tickers


async def _main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)

    if args.tickers:
        tickers = [t.upper() for t in args.tickers]
    elif args.file:
        tickers = _load_tickers_from_file(args.file)
    elif args.from_db:
        tickers = _fetch_tickers_from_db()
    else:
        tickers = _fetch_exchange_tickers(
            [e.upper() for e in args.exchange],
            min_mktcap=args.min_mktcap,
            min_price=args.min_price,
        )

    if not tickers:
        print("No tickers to process.", file=sys.stderr)
        sys.exit(1)

    print(f"\nBuilding vectors for {len(tickers)} ticker(s)…\n")
    vectors = await build_vectors(tickers, use_cache=not args.no_cache, batch_size=args.batch_size)

    if args.show:
        for cv in sorted(vectors, key=lambda x: x.ticker):
            _print_vector(cv)


def main(argv: list[str] | None = None) -> None:
    asyncio.run(_main(argv))


if __name__ == "__main__":
    main()
