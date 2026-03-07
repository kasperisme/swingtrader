"""
IBD Minervini screener – outputs JSON to stdout so n8n can read it
via the Execute Command node.

Usage:
    python scripts/run_screener.py --ibd-file "./input/IBD Data Tables.xlsx"
    python scripts/run_screener.py --ibd-file "./input/IBD Data Tables.xlsx" --lookback-days 365

n8n reads the last line of stdout and parses it as JSON.
All logging goes to stderr so it doesn't pollute the JSON output.
"""

import argparse
import json
import sys
from datetime import datetime, timedelta

import pandas as pd

# Add project root to path so src.* imports work when n8n calls this script
sys.path.insert(0, ".")

from src import fundamentals, logging, technical

logger = logging.logger


def screen(ibd_file_path: str, lookback_days: int) -> dict:
    tech = technical.technical()
    fund = fundamentals.Fundamentals()

    # 1. Exchange tickers
    df_col = [tech.get_exhange_tickers(i) for i in ["NYSE", "NASDAQ"]]
    df_tickers = pd.concat(df_col, axis=0)

    # 2. IBD data
    df_ibd = pd.read_excel(ibd_file_path, skiprows=11)
    df_ibd = df_ibd.dropna(subset=["RS Rating"])

    # 3. Merge
    df_tickers = df_ibd.merge(df_tickers, left_on="Symbol", right_on="symbol", how="left")
    df_tickers["symbol"] = df_tickers["Symbol"]
    df_tickers = df_tickers.dropna(subset=["Symbol"])
    tickers = df_tickers["symbol"].tolist()

    # 4. Quotes + pre-screener flags
    df_quote = tech.get_quote_prices(tickers)
    df_quote = df_quote.sort_values("symbol")

    # 5. RS scores
    df_rs = tech.get_change_prices(tickers)
    df_quote = df_quote.merge(df_rs, on="symbol", how="left")

    # 6. Pre-screener filter
    ls_symbol = df_quote[df_quote["SCREENER"] == 1]["symbol"].tolist()

    today = datetime.today()
    startdate = today - timedelta(days=lookback_days)
    strf = "%Y-%m-%d"

    logger.info(f"total={len(tickers)} pre-screened={len(ls_symbol)}")

    # 7. Full screening loop
    passed_stocks = []

    for symbol in ls_symbol:
        logger.info(f"Screening {symbol}")
        try:
            _df, ttd = tech.get_screening(
                symbol,
                startdate=startdate.strftime(strf),
                enddate=today.strftime(strf),
            )

            df_fund = fund.get_earnings_data(symbol)
            ttd["increasing_eps"] = bool(df_fund["eps_sma_direction"].iloc[-1] == 1)
            ttd["beat_estimate"] = bool(df_fund.tail(3)["beat_estimate"].sum() == 3)
            ttd["PASSED_FUNDAMENTALS"] = ttd["increasing_eps"] and ttd["beat_estimate"]

            try:
                row = df_tickers[df_tickers["symbol"] == symbol].iloc[0]
                ttd["sector"] = row.get("sector", "N/A")
                ttd["subSector"] = row.get("subSector", "N/A")
            except Exception:
                ttd["sector"] = "N/A"
                ttd["subSector"] = "N/A"

            if ttd["Passed"] and ttd["PASSED_FUNDAMENTALS"]:
                passed_stocks.append({
                    "symbol": symbol,
                    "sector": ttd["sector"],
                    "subSector": ttd["subSector"],
                    "PriceOverSMA150And200": bool(ttd["PriceOverSMA150And200"]),
                    "SMA150AboveSMA200": bool(ttd["SMA150AboveSMA200"]),
                    "SMA50AboveSMA150And200": bool(ttd["SMA50AboveSMA150And200"]),
                    "SMA200Slope": bool(ttd["SMA200Slope"]),
                    "PriceAbove25Percent52WeekLow": bool(ttd["PriceAbove25Percent52WeekLow"]),
                    "PriceWithin25Percent52WeekHigh": bool(ttd["PriceWithin25Percent52WeekHigh"]),
                    "RSOver70": bool(ttd["RSOver70"]),
                    "increasing_eps": ttd["increasing_eps"],
                    "beat_estimate": ttd["beat_estimate"],
                })

        except Exception as e:
            logger.error(f"Error screening {symbol}: {e}")

    return {
        "run_date": today.strftime(strf),
        "total_ibd_tickers": len(tickers),
        "pre_screened_count": len(ls_symbol),
        "passed_count": len(passed_stocks),
        "passed_stocks": passed_stocks,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--ibd-file", default="./input/IBD Data Tables.xlsx")
    parser.add_argument("--lookback-days", type=int, default=365)
    args = parser.parse_args()

    result = screen(args.ibd_file, args.lookback_days)

    # Print JSON to stdout – n8n reads this
    print(json.dumps(result))
