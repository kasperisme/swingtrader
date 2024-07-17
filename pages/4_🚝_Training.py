import streamlit as st
from src.fmp import fmp

fmp = fmp()


st.write("Hello, world!")

df_tickers = fmp.sp500tickers()
tickers = df_tickers["symbol"].to_list()

ticker = st.selectbox("Choose a ticker", tickers)
breakoutsize = st.number_input(
    "Minimum size of breakout [%]", value=10, placeholder="Type a number..."
)

breakoutlength = st.number_input(
    "Length of breakout [days]", value=10, placeholder="Type a number..."
)


df_daily = fmp.daily_chart("AAPL", "2021-01-01", "2021-12-31")

df_daily["changePercent_rolling"] = (
    df_daily["changePercent"].rolling(window=breakoutlength).sum()
)

mask = df_daily["changePercent_rolling"] > breakoutsize

st.dataframe(df_daily[mask], use_container_width=True)
