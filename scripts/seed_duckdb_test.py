#!/usr/bin/env python3
"""
Insert a minimal fake screening run into DuckDB for testing (Hans / MCP / SQL).

Usage (from repo root):
  python scripts/seed_duckdb_test.py

Optional:
  HANS_DUCKDB_PATH=/path/to/file.duckdb python scripts/seed_duckdb_test.py
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import date
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent


def _load_db():
    path = _ROOT / "src" / "db.py"
    spec = importlib.util.spec_from_file_location("swingtrader_db", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> None:
    sys.path.insert(0, str(_ROOT))
    db = _load_db()

    today = date.today()

    # Fake market-wide style outputs (same shape as ibd_screener / screener)
    df_tt = pd.DataFrame(
        [
            {
                "ticker": "TEST1",
                "symbol": "TEST1",
                "Passed": True,
                "RSOver70": True,
                "sector": "Technology",
                "subSector": "Software",
            },
            {
                "ticker": "TEST2",
                "symbol": "TEST2",
                "Passed": False,
                "RSOver70": True,
                "sector": "Healthcare",
                "subSector": "Biotech",
            },
        ]
    )
    df_rs = pd.DataFrame(
        [
            {"symbol": "TEST1", "RS": 88.5, "3M": 12.0, "6M": 15.0, "1Y": 20.0},
            {"symbol": "TEST2", "RS": 72.0, "3M": 5.0, "6M": 8.0, "1Y": 10.0},
        ]
    )
    df_quote = pd.DataFrame(
        [
            {
                "symbol": "TEST1",
                "price": 100.0,
                "avgVolume": 500_000,
                "SCREENER": 1,
            },
            {
                "symbol": "TEST2",
                "price": 50.0,
                "avgVolume": 600_000,
                "SCREENER": 1,
            },
        ]
    )

    run_id = db.persist_market_wide_scan(
        today,
        "test_seed",
        df_tt,
        df_rs,
        df_quote,
    )
    print(f"OK: persist_market_wide_scan run_id={run_id} scan_date={today}")
    print(f"DB file: {db.default_db_path()}")

    # Optional: one run_screener-shaped row (full JSON in scan_runs + passed_stocks rows)
    fake_result = {
        "fatal": False,
        "run_date": today.isoformat(),
        "market": {
            "condition": "confirmed_uptrend",
            "is_confirmed_uptrend": True,
            "distribution_days": 2,
        },
        "total_ibd_tickers": 2,
        "total_after_liquidity": 2,
        "pre_screened_count": 2,
        "passed_count": 1,
        "error_count": 0,
        "errors": [],
        "passed_stocks": [
            {
                "symbol": "TEST1",
                "sector": "Technology",
                "within_buy_range": True,
                "extension_pct": 0.02,
            }
        ],
    }
    rid2 = db.persist_screener_json_result(fake_result, source="run_screener")
    print(f"OK: persist_screener_json_result run_id={rid2}")


if __name__ == "__main__":
    main()
