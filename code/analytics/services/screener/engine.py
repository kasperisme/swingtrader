"""
IBD full market screen — NYSE + NASDAQ, Minervini trend template.

Can be launched two ways:
  1. Via MCP job_runner (recommended):
       SWINGTRADER_JOB_ID is set in the environment; job lifecycle is managed
       by job_runner.py (create → pid → finish).
  2. Directly:
       python ibd_screener.py
       A scan_job row is created here so the run appears in Supabase.

Persistence:
  scan_jobs (Supabase) — status / progress / exit_code throughout the run

  Screening results — via newsimpactscreener.com HTTP API:
    POST /api/v1/screenings/runs then .../rows
    Requires SWINGTRADER_API_KEY (Bearer; screenings:write scope).
    SWINGTRADER_API_BASE_URL defaults to https://www.newsimpactscreener.com.
"""

import os
import sys
import traceback
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parent
load_dotenv(dotenv_path=_ROOT / ".env")

# Must import db before anything that might fail so we can report errors.
from shared.db import (
    create_scan_job,
    finish_scan_job,
    update_scan_job_pid,
    update_scan_job_progress,
)
from services.screener.api_client import persist_market_wide_scan_via_api
from services.screener import technical, fundamentals
from shared import logging

logger = logging.logger


# ---------------------------------------------------------------------------
# Market-wide aggregates → market_json on each scan run.
# Consumed by the podcast pipeline (services/podcast/data_fetcher.py) and any
# other downstream that needs regime + breadth without re-running the screener.
# ---------------------------------------------------------------------------

def _build_market_json(df_trend_template, eligible_count: int) -> dict:
    """Aggregate the per-stock SMA flags into market-wide regime + breadth.

    Inputs are the merged trend-template dataframe (one row per screened stock),
    with boolean columns 'price_above_sma50', 'price_above_sma200',
    'sma_aligned', 'sma50_rising'. Stocks missing those flags fall out of the
    breadth denominator.

    Regime classification (mirrors per-stock logic in technical.py):
      Bull Confirmed     — >55% above 200MA AND >50% above 50MA
      Bull Uptrend       — >50% above 200MA
      Distribution       — <30% above 50MA
      Bear               — <30% above 200MA
      Mixed              — anything else
    """
    pct_50 = _pct_true(df_trend_template, "price_above_sma50")
    pct_200 = _pct_true(df_trend_template, "price_above_sma200")
    pct_aligned = _pct_true(df_trend_template, "sma_aligned")

    if pct_200 >= 55 and pct_50 >= 50:
        regime = "Bull Confirmed"
    elif pct_200 >= 50:
        regime = "Bull Uptrend"
    elif pct_200 < 30:
        regime = "Bear"
    elif pct_50 < 30:
        regime = "Distribution"
    else:
        regime = "Mixed"

    return {
        "regime_status": regime,
        "days_in_regime": 0,  # filled in by the persistence layer if it has prior runs
        "pct_above_50ma": round(pct_50, 1),
        "pct_above_200ma": round(pct_200, 1),
        "pct_sma_aligned": round(pct_aligned, 1),
        "eligible_count": int(eligible_count),
        "screened_count": int(len(df_trend_template)),
    }


def _pct_true(df, column: str) -> float:
    if column not in df.columns or len(df) == 0:
        return 0.0
    series = df[column].dropna()
    if len(series) == 0:
        return 0.0
    return float(series.astype(bool).sum()) / float(len(series)) * 100.0


# ---------------------------------------------------------------------------
# Job lifecycle helpers
# ---------------------------------------------------------------------------

_JOB_ID: int = int(os.environ.get("SWINGTRADER_JOB_ID", 0))
_OWN_JOB: bool = False  # True when this script created the job itself


def _init_job() -> None:
    """Create a scan_job row if we were not launched by job_runner."""
    global _JOB_ID, _OWN_JOB
    if _JOB_ID:
        return  # job_runner already owns the lifecycle
    _JOB_ID = create_scan_job(
        scan_source="ibd_screener",
        script_rel="ibd_screener.py",
        args=[],
        stdout_log="",
        stderr_log="",
    )
    update_scan_job_pid(_JOB_ID, os.getpid())
    _OWN_JOB = True
    logger.info("Created scan_job id=%s (direct run)", _JOB_ID)


def _progress(msg: str) -> None:
    if not _JOB_ID:
        return
    try:
        update_scan_job_progress(_JOB_ID, msg)
        logger.info("[job %s] %s", _JOB_ID, msg)
    except Exception:
        pass


def _finish(exit_code: int, error: str | None = None) -> None:
    """Mark the job finished — only if this script owns it."""
    if not _OWN_JOB or not _JOB_ID:
        return
    try:
        finish_scan_job(_JOB_ID, exit_code, error_message=error)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Screener logic
# ---------------------------------------------------------------------------


def run() -> None:
    _init_job()

    tech = technical.technical()
    fund = fundamentals.Fundamentals()

    index = ["NYSE", "NASDAQ"]
    period = 365
    strf = "%Y-%m-%d"
    now = datetime.now()
    today = datetime.today()
    startdate = today - timedelta(days=period)

    # ------------------------------------------------------------------
    # Step 1 — fetch tickers
    # ------------------------------------------------------------------
    _progress("Step 1/4: Fetching NYSE/NASDAQ tickers…")
    df_col = []
    for i in index:
        df = tech.get_exhange_tickers(i)
        df_col.append(df)

    df_tickers = pd.concat(df_col, axis=0)
    df_tickers = df_tickers.dropna(subset=["symbol"])
    tickers = df_tickers["symbol"].to_list()

    # ------------------------------------------------------------------
    # Step 2 — quotes + RS ratings + pre-screen
    # ------------------------------------------------------------------
    _progress("Step 2/4: Fetching quotes and computing RS ratings…")
    df_quote = tech.get_quote_prices(tickers)
    df_quote = df_quote.sort_values("symbol")

    df_rs = tech.get_change_prices(tickers)
    df_quote = df_quote.merge(df_rs, on="symbol", how="left")

    mask = (df_quote["SCREENER"] == 1) & (df_quote["RS"] > 80)
    ls_symbol = df_quote[mask]["symbol"].tolist()

    logger.info("Total tickers: %d", len(tickers))
    logger.info("After pre-screen + RS>80: %d", len(ls_symbol))
    logger.info(
        "Start date: %s  End date: %s", startdate.strftime(strf), today.strftime(strf)
    )

    # ------------------------------------------------------------------
    # Step 3 — deep per-ticker screening
    # ------------------------------------------------------------------
    ls_trend_template = []
    total = len(ls_symbol)

    for _idx, symbol in enumerate(ls_symbol, 1):
        _progress(f"Step 3/4: Deep screening {symbol} ({_idx}/{total})…")
        logger.info("Screening: %s", symbol)
        try:
            df_data, trend_template_dict, error = tech.get_screening(
                symbol,
                startdate=startdate.strftime(strf),
                enddate=today.strftime(strf),
            )

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

            # Save chart / result CSVs locally
            output_dir = _ROOT / "output" / "screening" / str(now) / symbol
            output_dir.mkdir(parents=True, exist_ok=True)
            df_data.to_csv(output_dir / "chart.csv")
            pd.DataFrame([trend_template_dict]).to_csv(
                output_dir / "trend_template.csv", index=False
            )
            df_fund.to_csv(output_dir / "fundamentals.csv")

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
            logger.error("Error screening %s: %s", symbol, e)

    # ------------------------------------------------------------------
    # Step 4 — persist to Supabase + save Excel
    # ------------------------------------------------------------------
    df_trend_template = pd.DataFrame(ls_trend_template)
    # Drop ticker-metadata columns that were already added per-row in the loop
    # (sector, subSector) to prevent _x/_y suffix collision on merge.
    tickers_for_merge = df_tickers.drop(
        columns=[
            c for c in ("sector", "subSector", "industry") if c in df_tickers.columns
        ],
    )
    df_trend_template = df_trend_template.merge(
        tickers_for_merge, left_on="ticker", right_on="symbol", how="left"
    )

    df_rs_out = df_rs.merge(df_tickers, on="symbol", how="left")
    df_quote_out = df_quote.merge(df_tickers, on="symbol", how="left")

    excel_path = _ROOT / "output" / "IBD_trend_template.xlsx"
    with pd.ExcelWriter(excel_path) as writer:
        df_trend_template.to_excel(writer, sheet_name="trend_template")
        df_rs_out.to_excel(writer, sheet_name="rs_rating")
        df_quote_out.to_excel(writer, sheet_name="quote")

    passed_mask = (
        df_trend_template["Passed"].fillna(False).astype(bool)
        if "Passed" in df_trend_template.columns
        else pd.Series(False, index=df_trend_template.index)
    )
    fundamentals_mask = (
        df_trend_template["PASSED_FUNDAMENTALS"].fillna(False).astype(bool)
        if "PASSED_FUNDAMENTALS" in df_trend_template.columns
        else pd.Series(False, index=df_trend_template.index)
    )
    eligible_mask = passed_mask & fundamentals_mask

    passed_count = int(passed_mask.sum())
    eligible_count = int(eligible_mask.sum())
    eligible_symbols = (
        set(df_trend_template.loc[eligible_mask, "symbol"].dropna().astype(str).tolist())
        if "symbol" in df_trend_template.columns
        else set()
    )

    df_trend_template_api = df_trend_template.loc[eligible_mask].copy()
    df_rs_out_api = (
        df_rs_out[df_rs_out["symbol"].isin(eligible_symbols)].copy()
        if "symbol" in df_rs_out.columns
        else df_rs_out.iloc[0:0].copy()
    )
    df_quote_out_api = (
        df_quote_out[df_quote_out["symbol"].isin(eligible_symbols)].copy()
        if "symbol" in df_quote_out.columns
        else df_quote_out.iloc[0:0].copy()
    )

    _progress(
        "Step 4/4: Saving to Supabase — "
        f"{eligible_count} passed technical+fundamentals / {total} screened…"
    )

    market_json = _build_market_json(df_trend_template, eligible_count)

    try:
        run_id = persist_market_wide_scan_via_api(
            today.date(),
            "ibd_screener",
            df_trend_template_api,
            df_rs_out_api,
            df_quote_out_api,
            market_json=market_json,
        )
        logger.info(
            "Screening results uploaded via API (run_id=%s, regime=%s, breadth_50=%.1f%%, breadth_200=%.1f%%)",
            run_id,
            market_json["regime_status"],
            market_json["pct_above_50ma"],
            market_json["pct_above_200ma"],
        )
    except Exception as e:
        logger.warning("Screening persist via API failed: %s", e)

    # Save passed symbols to text file
    if "symbol" in df_trend_template.columns:
        df_trend_template.loc[eligible_mask].to_csv(
            columns=["symbol"],
            header=False,
            index=False,
            path_or_buf=_ROOT / "output" / "IBD_trend_template.txt",
        )

    _progress(
        "Done — "
        f"{eligible_count} stocks passed technical + fundamentals "
        f"({passed_count} passed technical only)."
    )


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    try:
        run()
        _finish(0)
    except Exception as exc:
        error_msg = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
        logger.error("ibd_screener fatal error: %s", error_msg)
        _progress(f"FAILED: {type(exc).__name__}: {exc}")
        _finish(1, error=error_msg)
        sys.exit(1)
