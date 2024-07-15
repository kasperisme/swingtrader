from src import technical
from datetime import datetime, timedelta
import pandas as pd

tech = technical.technical()

df_tickers = tech.get_tickers()

tickers = df_tickers["symbol"].to_list()
df_quote = tech.get_quote_prices(tickers)

df_quote = df_quote.sort_values("symbol")

mask = df_quote["SCREENER"] == 1

ls_symbol = df_quote[mask]["symbol"].tolist()

period = 365
strf = "%Y-%m-%d"

today = datetime.today()
startdate = today - timedelta(days=period)

ls_trend_template = []
print("Screening for Minervini trend template")
print(" - Total tickers: ", len(ls_symbol))
print(" - Start date: ", startdate.strftime(strf))
print(" - End date: ", today.strftime(strf))

for symbol in ls_symbol:
    print("Screening for: ", symbol)
    try:
        df_data, trend_template_dict = tech.get_screening(
            symbol, startdate=startdate.strftime(strf), enddate=today.strftime(strf)
        )
    except:
        print(f"- No data found for the selected ticker: {symbol}")

    ls_trend_template.append(trend_template_dict)

df_trend_template = pd.DataFrame(ls_trend_template).to_excel(
    "./output/trend_template.xlsx", index=False
)
