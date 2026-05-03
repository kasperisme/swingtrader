#!/usr/bin/env python3
"""
Entry point for the daily podcast pipeline.

Usage:
    python scripts/run_podcast.py                  # full pipeline, live data
    python scripts/run_podcast.py --mock           # full pipeline, mock data
    python scripts/run_podcast.py --welcome-only   # render JUST the welcome scene
    python scripts/run_podcast.py --mock --script-only   # generate script JSON, no TTS
    python scripts/run_podcast.py --mock --no-publish    # full local render, skip RSS/R2/Telegram
    python scripts/run_podcast.py --mock --no-telegram   # skip Telegram approval gate
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


def _configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


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
    """Assemble live podcast data via services.podcast.data_fetcher.

    Pulls top_news + watchlist from RAG / Supabase, VIX + earnings from FMP,
    and regime/breadth from the latest screener run. Each section falls back
    independently — never raises on partial source failures.
    """
    from services.podcast.data_fetcher import fetch_live_data
    return await fetch_live_data()


async def main() -> None:
    parser = argparse.ArgumentParser(description="Run the daily podcast pipeline")
    parser.add_argument("--mock", action="store_true", help="Use mock market data")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable DEBUG logging")

    test_modes = parser.add_argument_group("test modes (mutually exclusive with full run)")
    test_modes.add_argument(
        "--welcome-only", action="store_true",
        help="Render only the deterministic welcome scene (no LLM, no data, no publish)",
    )
    test_modes.add_argument(
        "--script-only", action="store_true",
        help="Generate script JSON and stop (no TTS, no publish, no API spend on ElevenLabs)",
    )

    skips = parser.add_argument_group("skip flags")
    skips.add_argument("--no-publish", action="store_true", help="Skip RSS / R2 upload / Telegram notification")
    skips.add_argument("--no-telegram", action="store_true", help="Skip the Telegram approval gate")

    args = parser.parse_args()
    _configure_logging(args.verbose)
    log = logging.getLogger(__name__)

    from services.podcast.scheduler_hook import run_daily_podcast, run_welcome_only

    if args.welcome_only:
        log.info("Test mode: welcome-only")
        path = await run_welcome_only()
        log.info("Welcome render complete: %s", path)
        return

    if args.mock:
        log.info("Running with mock data")
        fetcher = lambda: MOCK_DATA  # noqa: E731
    else:
        fetcher = _live_data_fetcher

    await run_daily_podcast(
        fetcher,
        script_only=args.script_only,
        skip_approval=args.no_telegram,
        skip_publish=args.no_publish,
    )


if __name__ == "__main__":
    asyncio.run(main())
