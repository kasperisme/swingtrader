"""
IBD Minervini screener – outputs JSON to stdout so n8n can read it
via the Execute Command node.

Screening pipeline (in order):
  1. Market direction gate    — SPX SMA alignment + distribution-day count
  2. Liquidity filter         — min price $15, min avg-volume 400 k shares
  3. IBD RS rating merge      — universe = IBD watchlist only
  4. Pre-screener             — basic SMA + 52-week range flags (fast, batch)
  5. Minervini trend template — full 7-condition check per ticker
  6. Volume metrics           — up/down vol ratio, vol-ratio today, ADR%
  7. RS line                  — is RS line at a 52-week high?
  8. Buy-point check          — within 5% of pivot, or extended?
  9. O'Neil fundamentals      — EPS growth ≥25%, revenue ≥20%, beat 3Q
 10. Sector leadership        — sector in top 40% today?

Exit codes:
  0  – success (JSON result to stdout; passed_stocks may be empty)
  1  – fatal error before the per-ticker loop (error JSON to stdout)

All log output goes to stderr so it does not pollute the JSON on stdout.
"""

import argparse
import json
import os
import sys
import traceback
from datetime import datetime, timedelta

import pandas as pd

sys.path.insert(0, ".")

from src import fundamentals, logging, technical
from src.db import persist_screener_json_result, update_scan_job_progress

_JOB_ID = int(os.environ.get("SWINGTRADER_JOB_ID", 0))


def _progress(msg: str) -> None:
    if _JOB_ID:
        try:
            update_scan_job_progress(_JOB_ID, msg)
        except Exception:
            pass

logger = logging.logger

# ------------------------------------------------------------------
# Thresholds (easy to adjust)
# ------------------------------------------------------------------
MIN_PRICE = 15.0          # O'Neil minimum stock price
MIN_AVG_VOL = 400_000     # O'Neil minimum average daily volume


def screen(ibd_file_path: str, lookback_days: int) -> dict:
    errors = []
    strf = "%Y-%m-%d"
    today = datetime.today()
    startdate = today - timedelta(days=lookback_days)

    tech = technical.technical()
    fund = fundamentals.Fundamentals()

    # ==================================================================
    # STEP 1 – Market direction gate
    # All three traders: never fight the general market.
    # ==================================================================
    _progress("Step 1/5: Checking market direction (SPX)…")
    logger.info("Checking market direction (SPX)…")
    market = tech.get_market_direction(lookback_days=lookback_days)
    logger.info(
        f"Market condition: {market['condition']} | "
        f"Distribution days (25-session): {market['distribution_days']}"
    )

    if not market["is_confirmed_uptrend"]:
        logger.info("Market not in confirmed uptrend — skipping stock screening.")
        print(json.dumps({
            "fatal": False,
            "run_date": today.strftime(strf),
            "market": market,
            "message": (
                f"Market in '{market['condition']}' — no new positions recommended. "
                f"Distribution days: {market['distribution_days']}"
            ),
            "total_ibd_tickers": 0,
            "total_after_liquidity": 0,
            "pre_screened_count": 0,
            "passed_count": 0,
            "error_count": 0,
            "errors": [],
            "passed_stocks": [],
        }))
        sys.exit(0)

    # ==================================================================
    # STEP 2 – FMP screener: single call that drops illiquid / foreign /
    #           inactive names before we touch the IBD list at all.
    #           Slightly looser thresholds than our hard limits to avoid
    #           edge cases where FMP's volume field differs from avgVolume.
    # ==================================================================
    _progress("Step 2/5: Running FMP stock screener pre-filter…")
    try:
        logger.info("Running FMP stock screener pre-filter…")
        df_fmp_screen = tech.fmp.stock_screener(
            price_min=MIN_PRICE - 1,
            volume_min=int(MIN_AVG_VOL * 0.75),
        )
        fmp_allowed = set(df_fmp_screen["symbol"].tolist())
        logger.info(f"FMP screener returned {len(fmp_allowed)} symbols")
    except Exception as e:
        logger.warning(f"FMP screener failed ({e}) — continuing without it")
        fmp_allowed = None  # fall back: don't filter on this step

    # ==================================================================
    # STEP 3-5 – Build ticker universe, apply liquidity + pre-screener
    # ==================================================================
    _progress("Step 3/5: Building ticker universe and applying liquidity filter…")
    try:
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

        # Intersect IBD universe with FMP screener result — reduces quote
        # chunk calls before the slow per-ticker loop even starts.
        if fmp_allowed is not None:
            tickers = [t for t in tickers if t in fmp_allowed]
            logger.info(f"After FMP screener intersection: {len(tickers)} tickers")

        # Batch quote fetch — confirms price/volume and computes SMA flags
        df_quote = tech.get_quote_prices(tickers)
        df_quote = df_quote.sort_values("symbol")

        # Liquidity filter: price ≥ $15, avg daily volume ≥ 400 k
        df_quote = df_quote[
            (df_quote["price"] >= MIN_PRICE)
            & (df_quote["avgVolume"] >= MIN_AVG_VOL)
        ]
        tickers_liquid = df_quote["symbol"].tolist()
        logger.info(
            f"IBD universe: {len(df_tickers)} | after FMP+liquidity: {len(tickers_liquid)}"
        )

        df_rs = tech.get_change_prices(tickers_liquid)
        df_quote = df_quote.merge(df_rs, on="symbol", how="left")

        # Pre-screener: SMA stack + 52-week range (4 fast flags)
        ls_symbol = df_quote[df_quote["SCREENER"] == 1]["symbol"].tolist()
        logger.info(f"After pre-screener: {len(ls_symbol)}")

    except Exception as e:
        print(json.dumps({
            "fatal": True,
            "message": str(e),
            "traceback": traceback.format_exc(),
        }))
        sys.exit(1)

    # ==================================================================
    # STEP 5-10 – Per-ticker deep screening
    # ==================================================================
    passed_stocks = []
    sector_cache = {}  # avoid duplicate sector-performance calls
    total_to_screen = len(ls_symbol)

    for _idx, symbol in enumerate(ls_symbol, 1):
        _progress(f"Step 4/5: Deep screening {symbol} ({_idx}/{total_to_screen})…")
        logger.info(f"Screening {symbol}…")
        try:
            # ---- Minervini trend template + volume + RS line + buy point ----
            _df, ttd, screen_error = tech.get_screening(
                symbol,
                startdate=startdate.strftime(strf),
                enddate=today.strftime(strf),
            )

            if screen_error or ttd is None:
                errors.append({"symbol": symbol, "error": "screening data fetch failed"})
                continue

            if not ttd["Passed"]:
                logger.info(f"  {symbol} failed Minervini template")
                continue

            # ---- Sector / sub-sector ----
            # exchange_tickers now uses /stable/company-screener which returns
            # "industry" rather than "subSector" — fall back gracefully.
            try:
                row = df_tickers[df_tickers["symbol"] == symbol].iloc[0]
                ttd["sector"] = row.get("sector", "N/A")
                ttd["subSector"] = row.get("subSector", row.get("industry", "N/A"))
            except Exception:
                ttd["sector"] = "N/A"
                ttd["subSector"] = "N/A"

            # ---- O'Neil fundamentals (EPS ≥25%, rev ≥20%, beat 3Q) ----
            fund_flags = fund.get_fundamental_flags(symbol)
            if fund_flags is None:
                logger.info(f"  {symbol} — fundamental data unavailable, skipping")
                errors.append({"symbol": symbol, "error": "fundamental data unavailable"})
                continue

            if not fund_flags["passes_oneil_fundamentals"]:
                logger.info(
                    f"  {symbol} failed O'Neil fundamentals "
                    f"(EPS YoY: {fund_flags['eps_growth_yoy']}%, "
                    f"Rev YoY: {fund_flags['rev_growth_yoy']}%)"
                )
                continue

            # ---- Sector leadership (cached) ----
            sector = ttd.get("sector", "N/A")
            if sector not in sector_cache:
                sector_cache[sector] = fund.get_sector_leadership(sector)
            sector_info = sector_cache[sector]

            # ---- Institutional ownership (optional — skip if unavailable) ----
            inst_info = {}
            try:
                df_inst = fund.fmp.institutional_ownership_summary(symbol)
                if not df_inst.empty:
                    df_inst = df_inst.sort_values("date")
                    latest_inst = df_inst.iloc[-1]
                    prior_inst = df_inst.iloc[-2] if len(df_inst) >= 2 else None
                    inst_info = {
                        "inst_holders": int(latest_inst.get("investorsHolding", 0)),
                        "inst_holders_increasing": (
                            bool(
                                latest_inst.get("investorsHolding", 0)
                                > prior_inst.get("investorsHolding", 0)
                            )
                            if prior_inst is not None else None
                        ),
                    }
            except Exception:
                pass  # institutional data is supplementary — do not block

            # ---- Assemble result ----
            passed_stocks.append({
                "symbol": symbol,
                "sector": ttd["sector"],
                "subSector": ttd["subSector"],
                # Minervini trend template
                "PriceOverSMA150And200": bool(ttd["PriceOverSMA150And200"]),
                "SMA150AboveSMA200": bool(ttd["SMA150AboveSMA200"]),
                "SMA50AboveSMA150And200": bool(ttd["SMA50AboveSMA150And200"]),
                "SMA200Slope": bool(ttd["SMA200Slope"]),
                "PriceAbove25Percent52WeekLow": bool(ttd["PriceAbove25Percent52WeekLow"]),
                "PriceWithin25Percent52WeekHigh": bool(ttd["PriceWithin25Percent52WeekHigh"]),
                "RSOver70": bool(ttd["RSOver70"]),
                # Volume
                "avg_vol_50d": ttd.get("avg_vol_50d"),
                "vol_ratio_today": ttd.get("vol_ratio_today"),
                "up_down_vol_ratio": ttd.get("up_down_vol_ratio"),
                "accumulation": ttd.get("accumulation"),
                "vol_contracting_in_base": ttd.get("vol_contracting_in_base"),
                # Volatility
                "adr_pct": ttd.get("adr_pct"),
                # RS line
                "rs_line_new_high": ttd.get("rs_line_new_high"),
                "rs_line_value": ttd.get("rs_line_value"),
                # Buy point
                "pivot": ttd.get("pivot"),
                "extension_pct": ttd.get("extension_pct"),
                "within_buy_range": ttd.get("within_buy_range"),
                "extended": ttd.get("extended"),
                # O'Neil fundamentals
                "increasing_eps": fund_flags["increasing_eps"],
                "beat_estimate": fund_flags["beat_estimate"],
                "eps_growth_yoy": fund_flags["eps_growth_yoy"],
                "rev_growth_yoy": fund_flags["rev_growth_yoy"],
                "eps_accelerating": fund_flags["eps_accelerating"],
                "three_yr_annual_eps_25pct": fund_flags["three_yr_annual_eps_25pct"],
                # Sector leadership
                **sector_info,
                # Institutional (may be empty dict if unavailable)
                **inst_info,
            })

        except Exception as e:
            logger.error(f"Error screening {symbol}: {e}")
            errors.append({"symbol": symbol, "error": str(e)})

    _progress(
        f"Step 5/5: Persisting results — {len(passed_stocks)} stocks passed out of {total_to_screen} screened…"
    )
    return {
        "fatal": False,
        "run_date": today.strftime(strf),
        "market": market,
        "total_ibd_tickers": len(tickers),
        "total_after_liquidity": len(tickers_liquid),
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
    try:
        _rid = persist_screener_json_result(result)
        if _rid is not None:
            logger.info("DuckDB scan saved (run_id=%s)", _rid)
    except Exception as e:
        logger.warning("DuckDB persist failed: %s", e)
    print(json.dumps(result))
