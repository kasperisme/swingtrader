from src import technical, logging
from datetime import datetime, timedelta
import pandas as pd
import time

tech = technical.technical()
logger = logging.logger


index = "NYSE"
index = "CPH"
index = "INDICES"
index = "SPX"
index = ["NYSE", "NASDAQ"]

# getting all tickers from SPX
if index == "SPX":
    df_tickers = tech.get_sp500_tickers()
elif index == "INDICES":
    df_tickers = tech.get_indices_tickers()
elif type(index) == list:
    df_col = []
    for i in index:
        df = tech.get_exhange_tickers(i)
        df_col.append(df)
    df_tickers = pd.concat(df_col, axis=0)
else:
    # getting all tickers from CPH
    df_tickers = tech.get_exhange_tickers(index)


tickers = df_tickers["symbol"].to_list()

# get the fast quotes for all tickers
df_quote = tech.get_quote_prices(tickers)
df_quote = df_quote.sort_values("symbol")

# initializing the RS rating for the tickers
# constructing it for entire SPX
df_rs = tech.get_change_prices(tickers)
df_quote = df_quote.merge(df_rs, on="symbol", how="left")

# construct a mask for the screener
# only getting the passed tickers
mask = (df_quote["SCREENER"] == 1) & (df_quote["RS"] >= 70)
ls_symbol = df_quote[mask]["symbol"].tolist()

# get the last 90 days of data
period = 90
strf = "%Y-%m-%d"

today = datetime.today()
startdate = today - timedelta(days=period)

ls_trend_template = []

logger.info("Screening for Minervini trend template")
logger.info(" - Total tickers: " + str(len(tickers)))
logger.info(" - Total screened tickers: " + str(len(ls_symbol)))
logger.info(" - Start date: " + startdate.strftime(strf))
logger.info(" - End date: " + today.strftime(strf))

for symbol in ls_symbol:
    logger.info("Screening for: " + symbol)
    try:
        df_data, trend_template_dict = tech.get_screening(
            symbol,
            startdate=startdate.strftime(strf),
            enddate=today.strftime(strf),
        )

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
        logger.error(f"Error in screening: {symbol}")
# save the trend template to excel
df_trend_template = pd.DataFrame(ls_trend_template)

df_trend_template = df_trend_template.merge(
    df_tickers, left_on="ticker", right_on="symbol", how="left"
)

df_rs = df_rs.merge(df_tickers, left_on="symbol", right_on="symbol", how="left")

df_quote = df_quote.merge(df_tickers, left_on="symbol", right_on="symbol", how="left")

with pd.ExcelWriter(f"./output/{index}_trend_template.xlsx") as writer:
    df_trend_template.to_excel(writer, sheet_name="trend_template")
    df_rs.to_excel(writer, sheet_name="rs_rating")
    df_quote.to_excel(writer, sheet_name="quote")
