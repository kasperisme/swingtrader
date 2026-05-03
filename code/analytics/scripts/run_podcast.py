#!/usr/bin/env python3
"""
Entry point for the daily podcast pipeline.

Usage:
    python scripts/run_podcast.py                # run with live data fetcher
    python scripts/run_podcast.py --mock         # run with mock data (testing)
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


MOCK_DATA = {
    "date": "2026-05-03",
    "regime": {"status": "Bull Confirmed", "days_in_regime": 14},
    "breadth": {"pct_above_50ma": 62.3, "pct_above_200ma": 54.8},
    "vix": {"current": 18.4, "change_pct": -3.2, "direction": "down"},
    "top_news": {
        "ticker": "NVDA",
        "impact_score": 8.7,
        "headline": "NVIDIA announces next-generation Blackwell Ultra chips ahead of schedule",
        "factor_summary": "Supply chain acceleration + AI infrastructure demand surge",
    },
    "watchlist": [
        {"ticker": "NVDA", "rs_rank": 97, "stage": 2, "pct_from_pivot": 1.2, "setup_type": "VCP"},
        {"ticker": "META", "rs_rank": 91, "stage": 2, "pct_from_pivot": 3.5, "setup_type": "Flat base"},
        {"ticker": "MSTR", "rs_rank": 88, "stage": 2, "pct_from_pivot": -1.4, "setup_type": "Consolidation"},
        {"ticker": "PLTR", "rs_rank": 85, "stage": 2, "pct_from_pivot": 5.1, "setup_type": "Cup with handle"},
        {"ticker": "APP", "rs_rank": 82, "stage": 2, "pct_from_pivot": 2.0, "setup_type": "VCP"},
    ],
    "earnings": {"ticker": "AMZN", "surprise_pct": 12.4},
    "insider": {"ticker": "TSLA", "description": "CEO purchased 500,000 shares at $248"},
}


async def _live_data_fetcher() -> dict:
    """Placeholder — wire up to your actual data pipeline."""
    raise NotImplementedError(
        "Live data fetcher not implemented. "
        "Pass --mock for testing or implement this function."
    )


async def main() -> None:
    parser = argparse.ArgumentParser(description="Run the daily podcast pipeline")
    parser.add_argument("--mock", action="store_true", help="Use mock market data")
    args = parser.parse_args()

    from services.podcast.scheduler_hook import run_daily_podcast

    if args.mock:
        print("Running with mock data...")
        await run_daily_podcast(lambda: MOCK_DATA)
    else:
        await run_daily_podcast(_live_data_fetcher)


if __name__ == "__main__":
    asyncio.run(main())
