import streamlit as st
from src.fmp import fmp
from src import technical
import plotly.express as px

fmp = fmp()
technical = technical.technical()

df_tickers = technical.get_tickers()

tickers = df_tickers["symbol"].to_list()
df_quote = technical.get_quote_prices(tickers)

df_change = fmp.change_price(tickers)

df_stocks = df_quote.merge(df_change, on="symbol")

cols = [
    {"period": "3M", "weight": 2},
    {"period": "6M", "weight": 1},
    {"period": "1Y", "weight": 1},
]

df_stocks["Weighted_score"] = 0
for col in cols:
    period = col["period"]
    df_stocks[f"{period}_RANK"] = df_stocks[f"{period}"].rank(ascending=True)
    df_stocks["Weighted_score"] += df_stocks[f"{period}_RANK"] * col["weight"]

st.plotly_chart(
    px.histogram(
        df_stocks,
        x="Weighted_score",
    )
)

maxscore = len(df_stocks["symbol"]) * sum([i["weight"] for i in cols])

df_stocks["RS"] = df_stocks["Weighted_score"] / maxscore

st.plotly_chart(
    px.histogram(
        df_stocks,
        x="RANK",
    )
)

st.dataframe(df_stocks.sort_values("Weighted_score", ascending=False))
