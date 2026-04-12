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

  Screening results — either:
    • HTTP API (default when configured): POST /api/v1/screenings/runs + .../rows
      Set SWINGTRADER_API_BASE_URL and SWINGTRADER_API_KEY (Bearer; screenings:write).
    • Else direct Supabase: user_scan_runs + user_scan_rows (same shape as the API).
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
from src.db import (
    create_scan_job,
    ensure_schema,
    finish_scan_job,
    persist_market_wide_scan,
    update_scan_job_pid,
    update_scan_job_progress,
)
from src.screenings_api_client import persist_market_wide_scan_via_api
from src import technical, logging, fundamentals

logger = logging.logger

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
    # Ensure tables exist for direct runs (requires direct DB creds; skip if unavailable).
    try:
        ensure_schema()
    except Exception as e:
        logger.debug("ensure_schema skipped: %s", e)
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
    logger.info("Start date: %s  End date: %s", startdate.strftime(strf), today.strftime(strf))

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
    df_trend_template = df_trend_template.merge(
        df_tickers, left_on="ticker", right_on="symbol", how="left"
    )

    df_rs_out = df_rs.merge(df_tickers, on="symbol", how="left")
    df_quote_out = df_quote.merge(df_tickers, on="symbol", how="left")

    excel_path = _ROOT / "output" / "IBD_trend_template.xlsx"
    with pd.ExcelWriter(excel_path) as writer:
        df_trend_template.to_excel(writer, sheet_name="trend_template")
        df_rs_out.to_excel(writer, sheet_name="rs_rating")
        df_quote_out.to_excel(writer, sheet_name="quote")

    passed_count = int(df_trend_template["Passed"].sum()) if "Passed" in df_trend_template.columns else 0
    _progress(
        f"Step 4/4: Saving to Supabase — {passed_count} passed / {total} screened…"
    )

    try:
        use_api = bool(
            os.environ.get("SWINGTRADER_API_BASE_URL", "").strip()
            and os.environ.get("SWINGTRADER_API_KEY", "").strip()
        )
        if use_api:
            run_id = persist_market_wide_scan_via_api(
                today.date(),
                "ibd_screener",
                df_trend_template,
                df_rs_out,
                df_quote_out,
            )
            logger.info("Screening results uploaded via API (run_id=%s)", run_id)
        else:
            logger.info(
                "SWINGTRADER_API_BASE_URL + SWINGTRADER_API_KEY not set; persisting via Supabase client "
                "(set both to upload through /api/v1/screenings)."
            )
            run_id = persist_market_wide_scan(
                today.date(),
                "ibd_screener",
                df_trend_template,
                df_rs_out,
                df_quote_out,
            )
            logger.info("Supabase scan saved (run_id=%s)", run_id)
    except Exception as e:
        logger.warning("Screening persist (API or Supabase) failed: %s", e)

    # Save passed symbols to text file
    if "Passed" in df_trend_template.columns:
        df_trend_template[df_trend_template["Passed"] == True].to_csv(
            columns=["symbol"],
            header=False,
            index=False,
            path_or_buf=_ROOT / "output" / "IBD_trend_template.txt",
        )

    _progress(f"Done — {passed_count} stocks passed the Minervini trend template.")


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
