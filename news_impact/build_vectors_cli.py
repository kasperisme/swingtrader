"""
CLI entry point for the company vector builder.

Usage:
    python -m news_impact.build_vectors_cli --tickers AAPL MSFT NVDA JPM XOM
    python -m news_impact.build_vectors_cli --file tickers.txt
    python -m news_impact.build_vectors_cli --tickers AAPL MSFT --show
    python -m news_impact.build_vectors_cli --tickers AAPL --no-cache
"""

import argparse
import asyncio
import pathlib
import sys

from dotenv import load_dotenv

load_dotenv(pathlib.Path(__file__).parent.parent / ".env")

from news_impact.company_vector import build_vectors, CompanyVector
from news_impact.dimensions import CLUSTERS


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

# Which dimension keys to show per cluster in the compact table
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
    name    = cv.metadata.get("name", cv.ticker)
    sector  = cv.metadata.get("sector", "")
    mktcap  = _fmt_mktcap(cv.metadata.get("market_cap"))

    print(f"\n{sep}")
    print(f"{cv.ticker}  {name}  |  {sector}  |  {mktcap}")
    print(sep)

    dims = cv.dimensions

    for cluster_name, pairs in _DISPLAY_KEYS.items():
        label = _CLUSTER_SHORT.get(cluster_name, cluster_name)
        parts = []
        for key, short in pairs:
            score = dims.get(key)
            if score is not None:
                parts.append(f"{short}: {score:.2f}")
            else:
                parts.append(f"{short}: n/a")
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
        help="Path to a text file with one ticker per line",
    )
    parser.add_argument(
        "--show", action="store_true",
        help="Print a compact dimension table for each ticker",
    )
    parser.add_argument(
        "--no-cache", dest="no_cache", action="store_true",
        help="Bypass disk cache and fetch fresh data",
    )
    return parser.parse_args(argv)


def _load_tickers_from_file(path: str) -> list[str]:
    p = pathlib.Path(path)
    if not p.exists():
        print(f"Error: file not found: {path}", file=sys.stderr)
        sys.exit(1)
    lines = p.read_text().splitlines()
    tickers = [line.strip().upper() for line in lines if line.strip() and not line.startswith("#")]
    if not tickers:
        print(f"Error: no tickers found in {path}", file=sys.stderr)
        sys.exit(1)
    return tickers


async def _main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)

    if args.tickers:
        tickers = [t.upper() for t in args.tickers]
    else:
        tickers = _load_tickers_from_file(args.file)

    use_cache = not args.no_cache

    vectors = await build_vectors(tickers, use_cache=use_cache)

    if args.show:
        # Sort by ticker for consistent output
        for cv in sorted(vectors, key=lambda x: x.ticker):
            _print_vector(cv)


def main(argv: list[str] | None = None) -> None:
    asyncio.run(_main(argv))


if __name__ == "__main__":
    main()
