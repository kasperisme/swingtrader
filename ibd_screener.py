from src import (
    technical,
    logging,
    fundamentals,
)
from src.db import persist_market_wide_scan, update_scan_job_progress
from datetime import datetime, timedelta
import pandas as pd
import os
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))

_JOB_ID = int(os.environ.get("SWINGTRADER_JOB_ID", 0))


def _progress(msg: str) -> None:
    if _JOB_ID:
        try:
            update_scan_job_progress(_JOB_ID, msg)
        except Exception:
            pass


tech = technical.technical()
fund = fundamentals.Fundamentals()
logger = logging.logger

index = ["NYSE", "NASDAQ"]

_progress("Step 1/4: Fetching NYSE/NASDAQ tickers…")
df_col = []
for i in index:
    df = tech.get_exhange_tickers(i)
    df_col.append(df)

df_tickers = pd.concat(df_col, axis=0)

df_tickers = df_tickers.dropna(subset=["symbol"])


tickers = df_tickers["symbol"].to_list()

_progress("Step 2/4: Fetching quotes and computing RS ratings…")
# get the fast quotes for all tickers
df_quote = tech.get_quote_prices(tickers)
df_quote = df_quote.sort_values("symbol")

# initializing the RS rating for the tickers
# constructing it for entire SPX
df_rs = tech.get_change_prices(tickers)
df_quote = df_quote.merge(df_rs, on="symbol", how="left")

# construct a mask for the screener
# only getting the passed tickers
mask = (df_quote["SCREENER"] == 1) & (df_quote["RS"] > 80)
ls_symbol = df_quote[mask]["symbol"].tolist()

# get the last 90 days of data
period = 365
strf = "%Y-%m-%d"

now = datetime.now()
today = datetime.today()
startdate = today - timedelta(days=period)

ls_trend_template = []
_total_to_screen = len(ls_symbol)

logger.info("Screening for Minervini trend template")
logger.info(" - Total tickers: " + str(len(tickers)))
logger.info(" - Total screened tickers: " + str(len(ls_symbol)))
logger.info(" - Start date: " + startdate.strftime(strf))
logger.info(" - End date: " + today.strftime(strf))

for _idx, symbol in enumerate(ls_symbol, 1):
    _progress(f"Step 3/4: Deep screening {symbol} ({_idx}/{_total_to_screen})…")
    logger.info("Screening for: " + symbol)
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

        # save the df_data to output dir
        output_dir = f"./output/screening/{now}/{symbol}"
        os.makedirs(output_dir, exist_ok=True)

        df_data.to_csv(f"{output_dir}/chart.csv")

        # Convert trend_template_dict to DataFrame for saving
        df_trend_template_single = pd.DataFrame([trend_template_dict])
        df_trend_template_single.to_csv(f"{output_dir}/trend_template.csv", index=False)

        df_fund.to_csv(f"{output_dir}/fundamentals.csv")

        try:
            trend_template_dict["sector"] = df_tickers[df_tickers["symbol"] == symbol][
                "sector"
            ].values[0]

            trend_template_dict["subSector"] = df_tickers[
                df_tickers["symbol"] == symbol
            ]["subSector"].values[0]
        except:
            trend_template_dict["sector"] = "N/A"
            trend_template_dict["subSector"] = "N/A"

        ls_trend_template.append(trend_template_dict)
    except Exception as e:
        logger.error(f"Error in screening: {symbol} {e}")
# save the trend template to excel
df_trend_template = pd.DataFrame(ls_trend_template)

df_trend_template = df_trend_template.merge(
    df_tickers, left_on="ticker", right_on="symbol", how="left"
)

df_rs = df_rs.merge(df_tickers, left_on="symbol", right_on="symbol", how="left")

df_quote = df_quote.merge(df_tickers, left_on="symbol", right_on="symbol", how="left")

with pd.ExcelWriter(f"./output/IBD_trend_template.xlsx") as writer:
    df_trend_template.to_excel(writer, sheet_name="trend_template")
    df_rs.to_excel(writer, sheet_name="rs_rating")
    df_quote.to_excel(writer, sheet_name="quote")

_progress("Step 4/4: Saving results to DuckDB and Excel…")
try:
    _rid = persist_market_wide_scan(
        today.date(),
        "ibd_screener",
        df_trend_template,
        df_rs,
        df_quote,
    )
    logger.info("DuckDB scan saved (run_id=%s)", _rid)
except Exception as e:
    logger.warning("DuckDB persist failed: %s", e)

df_trend_template[df_trend_template["Passed"] == True].to_csv(
    columns=["symbol"],
    header=False,
    index=False,
    path_or_buf="./output/IBD_trend_template.txt",
)
