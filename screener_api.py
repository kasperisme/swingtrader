"""
FastAPI wrapper for the IBD screener.

n8n calls POST /run-screener with an optional ibd_file_path body param.
The endpoint runs the full Minervini + fundamentals screening pipeline and
returns JSON that n8n can forward to Slack and Google Sheets.

Run locally:
    uvicorn screener_api:app --host 0.0.0.0 --port 8000

Environment variables required:
    APIKEY  – Financial Modeling Prep API key
"""

import os
from datetime import datetime, timedelta

import pandas as pd
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from src import fundamentals, logging, technical

app = FastAPI(title="IBD Screener API")

logger = logging.logger


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class ScreenerRequest(BaseModel):
    ibd_file_path: str = "./input/IBD Data Tables.xlsx"
    lookback_days: int = 365


class StockResult(BaseModel):
    symbol: str
    sector: str | None
    subSector: str | None
    # Minervini trend-template flags
    PriceOverSMA150And200: bool
    SMA150AboveSMA200: bool
    SMA50AboveSMA150And200: bool
    SMA200Slope: bool
    PriceAbove25Percent52WeekLow: bool
    PriceWithin25Percent52WeekHigh: bool
    RSOver70: bool
    Passed: bool
    # Fundamental flags
    increasing_eps: bool
    beat_estimate: bool
    PASSED_FUNDAMENTALS: bool


class ScreenerResponse(BaseModel):
    run_date: str
    total_ibd_tickers: int
    pre_screened_count: int
    passed_technical: int
    passed_both: int
    passed_stocks: list[StockResult]


# ---------------------------------------------------------------------------
# Core screener logic (extracted from ibd_screener.py)
# ---------------------------------------------------------------------------

def run_screener(ibd_file_path: str, lookback_days: int) -> ScreenerResponse:
    tech = technical.technical()
    fund = fundamentals.Fundamentals()

    # 1. Exchange tickers
    index = ["NYSE", "NASDAQ"]
    df_col = [tech.get_exhange_tickers(i) for i in index]
    df_tickers = pd.concat(df_col, axis=0)

    # 2. IBD RS ratings
    df_ibd = pd.read_excel(ibd_file_path, skiprows=11)
    df_ibd = df_ibd.dropna(subset=["RS Rating"])

    # 3. Merge IBD data with exchange tickers
    df_tickers = df_ibd.merge(df_tickers, left_on="Symbol", right_on="symbol", how="left")
    df_tickers["symbol"] = df_tickers["Symbol"]
    df_tickers = df_tickers.dropna(subset=["Symbol"])
    tickers = df_tickers["symbol"].tolist()

    # 4. Quote prices + pre-screener flags
    df_quote = tech.get_quote_prices(tickers)
    df_quote = df_quote.sort_values("symbol")

    # 5. Relative-strength scores
    df_rs = tech.get_change_prices(tickers)
    df_quote = df_quote.merge(df_rs, on="symbol", how="left")

    # 6. Pre-screener mask
    ls_symbol = df_quote[df_quote["SCREENER"] == 1]["symbol"].tolist()

    # 7. Date range
    today = datetime.today()
    startdate = today - timedelta(days=lookback_days)
    strf = "%Y-%m-%d"

    logger.info(f"IBD screener | total={len(tickers)} | pre-screened={len(ls_symbol)}")

    # 8. Full Minervini + fundamentals screening
    ls_results: list[StockResult] = []

    for symbol in ls_symbol:
        logger.info(f"Screening {symbol}")
        try:
            _df_data, ttd = tech.get_screening(
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
                sector = row.get("sector", "N/A")
                sub_sector = row.get("subSector", "N/A")
            except Exception:
                sector, sub_sector = "N/A", "N/A"

            ls_results.append(
                StockResult(
                    symbol=symbol,
                    sector=sector,
                    subSector=sub_sector,
                    PriceOverSMA150And200=bool(ttd["PriceOverSMA150And200"]),
                    SMA150AboveSMA200=bool(ttd["SMA150AboveSMA200"]),
                    SMA50AboveSMA150And200=bool(ttd["SMA50AboveSMA150And200"]),
                    SMA200Slope=bool(ttd["SMA200Slope"]),
                    PriceAbove25Percent52WeekLow=bool(ttd["PriceAbove25Percent52WeekLow"]),
                    PriceWithin25Percent52WeekHigh=bool(ttd["PriceWithin25Percent52WeekHigh"]),
                    RSOver70=bool(ttd["RSOver70"]),
                    Passed=bool(ttd["Passed"]),
                    increasing_eps=ttd["increasing_eps"],
                    beat_estimate=ttd["beat_estimate"],
                    PASSED_FUNDAMENTALS=ttd["PASSED_FUNDAMENTALS"],
                )
            )
        except Exception as e:
            logger.error(f"Error screening {symbol}: {e}")

    passed_technical = [s for s in ls_results if s.Passed]
    passed_both = [s for s in ls_results if s.Passed and s.PASSED_FUNDAMENTALS]

    return ScreenerResponse(
        run_date=today.strftime(strf),
        total_ibd_tickers=len(tickers),
        pre_screened_count=len(ls_symbol),
        passed_technical=len(passed_technical),
        passed_both=len(passed_both),
        passed_stocks=passed_both,
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/run-screener", response_model=ScreenerResponse)
def run_screener_endpoint(req: ScreenerRequest):
    if not os.path.exists(req.ibd_file_path):
        raise HTTPException(
            status_code=400,
            detail=f"IBD file not found: {req.ibd_file_path}",
        )
    try:
        return run_screener(req.ibd_file_path, req.lookback_days)
    except Exception as e:
        logger.error(f"Screener failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
