#!/usr/bin/env python3
"""
zscore_cli.py — fast clock for the pairs layer (run daily after close / intraday).

Reads every calibrated pair from swingtrader.ticker_pair_stats, fetches the
latest price for each leg in a single batched quote call, and updates
current_spread + current_zscore using the STORED spread_mean / spread_std. It
never recomputes a mean — that is what keeps look-ahead bias out of the signal
and lets this run every few minutes.

Signal convention (z = (spread - mean) / std, spread = A - hedge*B):
    z > +2  : A rich vs B  -> short A, long B
    z < -2  : A cheap vs B -> long A, short B
    |z| < 0.5 : exit        |z| > 3.5 : stop (diverging, not reverting)

Usage:
    python -m services.pairs.zscore_cli                  # refresh all calibrated pairs
    python -m services.pairs.zscore_cli --only-cointegrated
    python -m services.pairs.zscore_cli --min-abs-z 2.0  # only report actionable pairs
    python -m services.pairs.zscore_cli --no-persist     # dry run

Schedule (example):
    Daily after close:  30 21 * * 1-5  cd code/analytics && .venv/bin/python -m services.pairs.zscore_cli
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(dotenv_path=_ROOT / ".env")
sys.path.insert(0, str(_ROOT))

from services.pairs.cointegration import live_zscore  # noqa: E402
from services.pairs.prices import fetch_latest_quotes  # noqa: E402
from services.pairs.store import fetch_calibrated_pairs, update_pair_zscore  # noqa: E402
from services.screener.fmp import fmp as FMPClient  # noqa: E402

log = logging.getLogger("pairs.zscore")


def run(*, only_cointegrated: bool, min_abs_z: float, persist: bool) -> None:
    pairs = fetch_calibrated_pairs()
    if only_cointegrated:
        pairs = [p for p in pairs if p.get("is_cointegrated")]
    log.info("Loaded %d calibrated pairs", len(pairs))
    if not pairs:
        return

    universe = sorted({
        str(p[k]).upper().strip()
        for p in pairs
        for k in ("ticker_a", "ticker_b")
        if p.get(k)
    })
    quotes = fetch_latest_quotes(FMPClient(), universe)
    log.info("Got quotes for %d/%d tickers", len(quotes), len(universe))

    updated = skipped = 0
    actionable: list[tuple[float, str]] = []
    for p in pairs:
        a, b = p["ticker_a"], p["ticker_b"]
        pa, pb = quotes.get(a), quotes.get(b)
        if pa is None or pb is None:
            skipped += 1
            continue
        res = live_zscore(
            pa, pb,
            hedge_ratio=p.get("hedge_ratio"),
            spread_mean=p.get("spread_mean"),
            spread_std=p.get("spread_std"),
        )
        if res is None:
            skipped += 1
            continue
        spread, z = res
        updated += 1
        if abs(z) >= min_abs_z:
            tag = "COINT" if p.get("is_cointegrated") else "     "
            actionable.append((abs(z), f"{tag} {a}/{b}  z={z:+.2f}  p={_fmt(p.get('coint_pvalue'))}"))
        if persist:
            update_pair_zscore(
                a, b,
                current_price_a=pa,
                current_price_b=pb,
                current_spread=spread,
                current_zscore=z,
            )

    for _, line in sorted(actionable, reverse=True):
        log.info(line)
    log.info(
        "Done. updated=%d skipped=%d actionable(|z|>=%.1f)=%d persisted=%s",
        updated, skipped, min_abs_z, len(actionable), persist,
    )


def _fmt(v) -> str:
    try:
        return f"{float(v):.3f}"
    except (TypeError, ValueError):
        return " n/a "


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    p = argparse.ArgumentParser(description="Refresh live z-scores for calibrated pairs.")
    p.add_argument("--only-cointegrated", action="store_true",
                   help="Only refresh pairs with coint_pvalue < 0.05")
    p.add_argument("--min-abs-z", type=float, default=2.0,
                   help="Report threshold for |z| in the run summary (default: 2.0)")
    p.add_argument("--no-persist", dest="persist", action="store_false",
                   help="Dry run — compute and print without writing to the DB")
    args = p.parse_args()
    run(only_cointegrated=args.only_cointegrated, min_abs_z=args.min_abs_z, persist=args.persist)


if __name__ == "__main__":
    main()
