#!/usr/bin/env python3
"""
Run the same Minervini / fundamentals pipeline as ibd_screener.py, but only for
tickers you list (real FMP data, fewer API calls than full NYSE+NASDAQ).

Examples (from repo root, with .env APIKEY set):
  python scripts/subset_ibd_screener.py AAPL MSFT NVDA
  python scripts/subset_ibd_screener.py --no-prefilter AXON DUOL
  python scripts/subset_ibd_screener.py --tickers-file ./input/my_tickers.txt

Writes to DuckDB (source=ibd_screener_subset). Optional --excel and per-symbol CSVs.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pandas as pd
from dotenv import load_dotenv

load_dotenv(dotenv_path=_ROOT / ".env")

from src import fundamentals, logging, technical
from src.db import persist_market_wide_scan

logger = logging.logger


def _parse_tickers_file(path: Path) -> list[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    out: list[str] = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        sym = line.split(",")[0].strip().upper()
        if sym:
            out.append(sym)
    return out


def _build_ticker_universe(tech: technical.technical, symbols: list[str]) -> pd.DataFrame:
    base = pd.DataFrame({"symbol": symbols})
    prof = tech.fmp.profile(symbols)
    if prof.empty:
        base["sector"] = "N/A"
        base["subSector"] = "N/A"
        return base
    prof = prof.copy()
    if "industry" in prof.columns and "subSector" not in prof.columns:
        prof["subSector"] = prof["industry"]
    merged = base.merge(prof, on="symbol", how="left", suffixes=("", "_p"))
    for col in ("sector", "subSector"):
        if col not in merged.columns:
            merged[col] = "N/A"
        else:
            merged[col] = merged[col].fillna("N/A")
    return merged


def main() -> None:
    parser = argparse.ArgumentParser(description="Subset IBD-style screener (real FMP).")
    parser.add_argument(
        "tickers",
        nargs="*",
        help="Ticker symbols (e.g. AAPL MSFT). Use --tickers-file if many.",
    )
    parser.add_argument(
        "--tickers-file",
        type=Path,
        default=None,
        help="One symbol per line (commas optional: SYMBOL,…). Lines starting with # ignored.",
    )
    parser.add_argument(
        "--min-rs",
        type=float,
        default=80.0,
        help="Minimum RS score after pre-screen (same spirit as ibd_screener RS > 80).",
    )
    parser.add_argument(
        "--no-prefilter",
        action="store_true",
        help="Run deep screening on all listed tickers with valid quotes (skip SCREENER+RS gate).",
    )
    parser.add_argument(
        "--period-days",
        type=int,
        default=365,
        help="Lookback for daily chart / Minervini checks.",
    )
    parser.add_argument(
        "--excel",
        action="store_true",
        help="Also write ./output/IBD_subset_trend_template.xlsx",
    )
    parser.add_argument(
        "--save-charts",
        action="store_true",
        help="Write per-symbol chart.csv / trend_template.csv / fundamentals.csv under output/screening/",
    )
    args = parser.parse_args()

    symbols: list[str] = []
    if args.tickers_file is not None:
        symbols.extend(_parse_tickers_file(args.tickers_file))
    symbols.extend(t.upper().strip() for t in args.tickers if t.strip())
    # de-dupe, preserve order
    seen: set[str] = set()
    uniq: list[str] = []
    for s in symbols:
        if s not in seen:
            seen.add(s)
            uniq.append(s)
    symbols = uniq

    if not symbols:
        logger.error("No tickers: pass symbols on the command line or use --tickers-file.")
        sys.exit(2)

    tech = technical.technical()
    fund = fundamentals.Fundamentals()

    df_tickers = _build_ticker_universe(tech, symbols)

    df_quote = tech.get_quote_prices(symbols)
    df_quote = df_quote.sort_values("symbol")
    df_rs = tech.get_change_prices(symbols)
    df_quote = df_quote.merge(df_rs, on="symbol", how="left")

    if args.no_prefilter:
        valid = set(df_quote["symbol"].astype(str).str.upper())
        ls_symbol = [s for s in symbols if s in valid]
    else:
        mask = (df_quote["SCREENER"] == 1) & (df_quote["RS"] > args.min_rs)
        ls_symbol = df_quote[mask]["symbol"].tolist()

    strf = "%Y-%m-%d"
    now = datetime.now()
    today = datetime.today()
    startdate = today - timedelta(days=args.period_days)

    logger.info("Subset screening (real FMP)")
    logger.info(" - Requested symbols: %s", len(symbols))
    logger.info(" - After pre-screen: %s", len(ls_symbol))
    logger.info(" - Start date: %s", startdate.strftime(strf))
    logger.info(" - End date: %s", today.strftime(strf))

    if not ls_symbol:
        logger.warning(
            "No symbols passed the pre-screen. Use --no-prefilter to screen all listed names anyway."
        )

    ls_trend_template: list = []

    for symbol in ls_symbol:
        logger.info("Screening for: %s", symbol)
        try:
            df_data, trend_template_dict, error = tech.get_screening(
                symbol,
                startdate=startdate.strftime(strf),
                enddate=today.strftime(strf),
            )
            if error or trend_template_dict is None:
                logger.error("Screening failed for %s", symbol)
                continue

            df_fund = fund.get_earnings_data(symbol)

            trend_template_dict["increasing_eps"] = (
                df_fund["eps_sma_direction"].iloc[-1] == 1
            )
            trend_template_dict["beat_estimate"] = (
                df_fund.tail(3)["beat_estimate"].sum() == 3
            )

            trend_template_dict["PASSED_FUNDAMENTALS"] = (
                trend_template_dict["increasing_eps"]
                and trend_template_dict["beat_estimate"]
            )

            if args.save_charts:
                output_dir = f"./output/screening/{now}/{symbol}"
                os.makedirs(output_dir, exist_ok=True)
                df_data.to_csv(f"{output_dir}/chart.csv")
                pd.DataFrame([trend_template_dict]).to_csv(
                    f"{output_dir}/trend_template.csv", index=False
                )
                df_fund.to_csv(f"{output_dir}/fundamentals.csv")

            try:
                row = df_tickers[df_tickers["symbol"] == symbol].iloc[0]
                trend_template_dict["sector"] = row.get("sector", "N/A")
                trend_template_dict["subSector"] = row.get(
                    "subSector", row.get("industry", "N/A")
                )
            except Exception:
                trend_template_dict["sector"] = "N/A"
                trend_template_dict["subSector"] = "N/A"

            ls_trend_template.append(trend_template_dict)
        except Exception as e:
            logger.error("Error in screening: %s %s", symbol, e)

    df_trend_template = pd.DataFrame(ls_trend_template)
    if not df_trend_template.empty:
        df_trend_template = df_trend_template.merge(
            df_tickers, left_on="ticker", right_on="symbol", how="left"
        )

    df_rs = df_rs.merge(df_tickers, on="symbol", how="left")
    df_quote = df_quote.merge(df_tickers, on="symbol", how="left")

    if args.excel:
        out_xlsx = "./output/IBD_subset_trend_template.xlsx"
        os.makedirs("./output", exist_ok=True)
        with pd.ExcelWriter(out_xlsx) as writer:
            df_trend_template.to_excel(writer, sheet_name="trend_template")
            df_rs.to_excel(writer, sheet_name="rs_rating")
            df_quote.to_excel(writer, sheet_name="quote")
        logger.info("Wrote %s", out_xlsx)

    try:
        rid = persist_market_wide_scan(
            today.date(),
            "ibd_screener_subset",
            df_trend_template,
            df_rs,
            df_quote,
        )
        logger.info("DuckDB scan saved (run_id=%s, source=ibd_screener_subset)", rid)
    except Exception as e:
        logger.warning("DuckDB persist failed: %s", e)


if __name__ == "__main__":
    main()
