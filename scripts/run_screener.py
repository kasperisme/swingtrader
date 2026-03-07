"""
IBD Minervini screener – outputs JSON to stdout so n8n can read it
via the Execute Command node.

Exit codes:
  0  success  – JSON result printed to stdout
  1  fatal    – could not build ticker list / pre-screener step failed;
                error JSON printed to stdout so n8n can surface it

Per-ticker errors are non-fatal: the loop continues and each failure is
recorded in the 'errors' list inside the result JSON.

Usage:
    python scripts/run_screener.py --ibd-file "./input/IBD Data Tables.xlsx"
    python scripts/run_screener.py --ibd-file "./input/IBD Data Tables.xlsx" --lookback-days 365

All logging goes to stderr so it does not pollute the JSON output.
"""

import argparse
import json
import sys
import traceback
from datetime import datetime, timedelta

import pandas as pd

sys.path.insert(0, ".")

from src import fundamentals, logging, technical

logger = logging.logger


def screen(ibd_file_path: str, lookback_days: int) -> dict:
    errors = []

    # ------------------------------------------------------------------
    # Fatal section – if anything here fails the whole run is worthless
    # ------------------------------------------------------------------
    try:
        tech = technical.technical()
        fund = fundamentals.Fundamentals()

        df_col = [tech.get_exhange_tickers(i) for i in ["NYSE", "NASDAQ"]]
        df_tickers = pd.concat(df_col, axis=0)

        df_ibd = pd.read_excel(ibd_file_path, skiprows=11)
        df_ibd = df_ibd.dropna(subset=["RS Rating"])

        df_tickers = df_ibd.merge(
            df_tickers, left_on="Symbol", right_on="symbol", how="left"
        )
        df_tickers["symbol"] = df_tickers["Symbol"]
        df_tickers = df_tickers.dropna(subset=["Symbol"])
        tickers = df_tickers["symbol"].tolist()

        df_quote = tech.get_quote_prices(tickers)
        df_quote = df_quote.sort_values("symbol")

        df_rs = tech.get_change_prices(tickers)
        df_quote = df_quote.merge(df_rs, on="symbol", how="left")

        ls_symbol = df_quote[df_quote["SCREENER"] == 1]["symbol"].tolist()

    except Exception as e:
        # Print error JSON so n8n can read it, then exit 1
        print(json.dumps({
            "fatal": True,
            "message": str(e),
            "traceback": traceback.format_exc(),
        }))
        sys.exit(1)

    # ------------------------------------------------------------------
    # Per-ticker section – failures are recorded but do not stop the run
    # ------------------------------------------------------------------
    today = datetime.today()
    startdate = today - timedelta(days=lookback_days)
    strf = "%Y-%m-%d"

    logger.info(f"total={len(tickers)} pre-screened={len(ls_symbol)}")

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
            errors.append({"symbol": symbol, "error": str(e)})

    return {
        "fatal": False,
        "run_date": today.strftime(strf),
        "total_ibd_tickers": len(tickers),
        "pre_screened_count": len(ls_symbol),
        "passed_count": len(passed_stocks),
        "error_count": len(errors),
        "errors": errors,
        "passed_stocks": passed_stocks,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--ibd-file", default="./input/IBD Data Tables.xlsx")
    parser.add_argument("--lookback-days", type=int, default=365)
    args = parser.parse_args()

    result = screen(args.ibd_file, args.lookback_days)
    print(json.dumps(result))
