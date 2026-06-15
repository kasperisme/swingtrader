#!/usr/bin/env python3
"""
calibrate_cli.py — slow clock for the pairs layer (run weekly via cron).

Walks the news-derived candidate pairs (ticker_pair_candidates_v), pulls
adjusted daily closes once per ticker, fits each pair (hedge ratio,
Engle-Granger p-value, OU half-life, rolling spread mean/std) and upserts the
calibration into swingtrader.ticker_pair_stats.

By default it (re)calibrates pairs with no stats row or whose calibration is
older than --stale-days, so newly-added graph edges automatically get a
cointegration test on the next run — that is the "catch it before it's crowded"
window.

Usage:
    # Recalibrate everything stale (default cron invocation)
    python -m services.pairs.calibrate_cli

    # Force a full recalibration of all candidates
    python -m services.pairs.calibrate_cli --all

    # Tighter candidate filter / smaller window / cap the run
    python -m services.pairs.calibrate_cli --min-article-count 3 --window-days 180 --max-pairs 500

    # Inspect a single pair without writing (dry run)
    python -m services.pairs.calibrate_cli --pair KO PEP --no-persist

Schedule (example — register with your cron/scheduler):
    Weekly:  0 6 * * 1  cd code/analytics && .venv/bin/python -m services.pairs.calibrate_cli
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(dotenv_path=_ROOT / ".env")
sys.path.insert(0, str(_ROOT))

from services.pairs.candidates import CandidatePair, fetch_candidate_pairs  # noqa: E402
from services.pairs.cointegration import compute_pair_stats  # noqa: E402
from services.pairs.prices import fetch_daily_closes  # noqa: E402
from services.pairs.store import (  # noqa: E402
    fetch_calibration_freshness,
    upsert_pair_calibration,
)
from services.screener.fmp import fmp as FMPClient  # noqa: E402

log = logging.getLogger("pairs.calibrate")


def _is_stale(calibrated_at: str | None, stale_days: int) -> bool:
    if not calibrated_at:
        return True
    try:
        ts = datetime.fromisoformat(str(calibrated_at).replace("Z", "+00:00"))
    except ValueError:
        return True
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts < datetime.now(timezone.utc) - timedelta(days=stale_days)


def _select_pairs(
    candidates: list[CandidatePair],
    recalibrate_all: bool,
    stale_days: int,
) -> list[CandidatePair]:
    if recalibrate_all:
        return candidates
    freshness = fetch_calibration_freshness()
    selected: list[CandidatePair] = []
    for c in candidates:
        key = (c.ticker_a, c.ticker_b) if c.ticker_a < c.ticker_b else (c.ticker_b, c.ticker_a)
        if _is_stale(freshness.get(key), stale_days):
            selected.append(c)
    return selected


def run(
    *,
    min_article_count: int,
    min_strength: float,
    window_days: int,
    stale_days: int,
    recalibrate_all: bool,
    max_pairs: int | None,
    persist: bool,
    single_pair: tuple[str, str] | None,
) -> None:
    fmp = FMPClient()

    if single_pair:
        a, b = single_pair[0].upper(), single_pair[1].upper()
        candidates = [CandidatePair(min(a, b), max(a, b), 0, 0, [])]
    else:
        candidates = fetch_candidate_pairs(
            min_article_count=min_article_count,
            min_strength=min_strength,
        )
        log.info("Loaded %d candidate pairs from the graph", len(candidates))
        candidates = _select_pairs(candidates, recalibrate_all, stale_days)
        log.info(
            "%d pairs need (re)calibration (stale_days=%d, all=%s)",
            len(candidates),
            stale_days,
            recalibrate_all,
        )

    if max_pairs is not None:
        candidates = candidates[:max_pairs]

    if not candidates:
        log.info("Nothing to calibrate.")
        return

    # Pull each ticker's history exactly once.
    universe = sorted({t for c in candidates for t in (c.ticker_a, c.ticker_b)})
    log.info("Fetching daily closes for %d tickers", len(universe))
    closes = fetch_daily_closes(fmp, universe, window_days)

    fitted = cointegrated = skipped = 0
    for c in candidates:
        sa = closes.get(c.ticker_a)
        sb = closes.get(c.ticker_b)
        if sa is None or sb is None:
            skipped += 1
            continue
        stats = compute_pair_stats(sa, sb, window_days=window_days)
        if stats is None:
            skipped += 1
            continue
        fitted += 1
        is_coint = stats.coint_pvalue is not None and stats.coint_pvalue < 0.05
        if is_coint:
            cointegrated += 1
        flag = "COINT" if is_coint else "     "
        hl = f"{stats.half_life_days:.1f}d" if stats.half_life_days else "  n/a"
        log.info(
            "%s %s/%s  beta=%+.3f  p=%s  half-life=%s  n=%d",
            flag,
            c.ticker_a,
            c.ticker_b,
            stats.hedge_ratio,
            f"{stats.coint_pvalue:.3f}" if stats.coint_pvalue is not None else " n/a ",
            hl,
            stats.n_obs,
        )
        if persist:
            upsert_pair_calibration(
                c.ticker_a,
                c.ticker_b,
                hedge_ratio=stats.hedge_ratio,
                coint_pvalue=stats.coint_pvalue,
                half_life_days=stats.half_life_days,
                spread_mean=stats.spread_mean,
                spread_std=stats.spread_std,
                window_days=stats.window_days,
                n_obs=stats.n_obs,
            )

    log.info(
        "Done. fitted=%d cointegrated=%d skipped=%d persisted=%s",
        fitted,
        cointegrated,
        skipped,
        persist,
    )


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    p = argparse.ArgumentParser(description="Calibrate cointegration stats for graph pairs.")
    p.add_argument("--min-article-count", type=int, default=2,
                   help="Min article evidence for a candidate pair (default: 2)")
    p.add_argument("--min-strength", type=float, default=0.0,
                   help="Min peak edge strength for a candidate pair (default: 0.0)")
    p.add_argument("--window-days", type=int, default=252,
                   help="Calibration lookback in trading days (default: 252)")
    p.add_argument("--stale-days", type=int, default=7,
                   help="Recalibrate pairs older than this many days (default: 7)")
    p.add_argument("--all", dest="recalibrate_all", action="store_true",
                   help="Recalibrate every candidate, ignoring freshness")
    p.add_argument("--max-pairs", type=int, default=None,
                   help="Cap the number of pairs processed this run")
    p.add_argument("--no-persist", dest="persist", action="store_false",
                   help="Dry run — fit and print without writing to the DB")
    p.add_argument("--pair", nargs=2, metavar=("A", "B"), default=None,
                   help="Calibrate a single explicit pair (bypasses the graph)")
    args = p.parse_args()

    run(
        min_article_count=args.min_article_count,
        min_strength=args.min_strength,
        window_days=args.window_days,
        stale_days=args.stale_days,
        recalibrate_all=args.recalibrate_all,
        max_pairs=args.max_pairs,
        persist=args.persist,
        single_pair=tuple(args.pair) if args.pair else None,
    )


if __name__ == "__main__":
    main()
