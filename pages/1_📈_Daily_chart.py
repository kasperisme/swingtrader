import streamlit as st
import time
import numpy as np
from datetime import datetime, timedelta

from src import helpers

helper = helpers.helper()

strf = "%Y-%m-%d"
period = 365

today = datetime.today()
startdate = today - timedelta(days=period)


st.set_page_config(page_title="Ticker screener", page_icon="📈")

st.markdown("# Daily chart - 1 year")
st.sidebar.header("Plotting Daily chart - 1 year")

df_tickers = helper.get_tickers()
df_tickers = df_tickers.sort_values("symbol")

df_tickers["label"] = df_tickers["symbol"] + " - " + df_tickers["name"]

label = st.selectbox(
    "How would you like to be contacted?", df_tickers["label"].tolist()
)
if label:
    ticker = label.split(" - ")[0]

    try:
        st.plotly_chart(
            helper.get_complete_graph(
                ticker, startdate=startdate.strftime(strf), enddate=today.strftime(strf)
            ),
        )
    except:
        st.error("No data found for the selected ticker")

    st.sidebar.markdown("## Minervini trend template")
    col01, col02 = st.sidebar.columns(2)

    col01.metric(
        "Price over SMA150 and 200",
        (
            "✅"
            if helper.data["close"].iloc[-1] > helper.data["SMA200"].iloc[-1]
            and helper.data["close"].iloc[-1] > helper.data["SMA150"].iloc[-1]
            else "❌"
        ),
    )

    col02.metric(
        "SMA150 above SMA200",
        (
            "✅"
            if helper.data["SMA150"].iloc[-1] > helper.data["SMA200"].iloc[-1]
            else "❌"
        ),
    )

    col11, col12 = st.sidebar.columns(2)

    col11.metric(
        "SMA50 above SMA150 and 200",
        (
            "✅"
            if helper.data["SMA50"].iloc[-1] > helper.data["SMA200"].iloc[-1]
            and helper.data["SMA50"].iloc[-1] > helper.data["SMA150"].iloc[-1]
            else "❌"
        ),
    )

    col12.metric(
        "SMA200 20 day slope",
        ("✅" if helper.data["SMA200_slope_direction"].tail(20).sum() == 20 else "❌"),
    )

    col21, col22 = st.sidebar.columns(2)

    col21.metric(
        "Current stock price is 25% above 52 weeks low",
        (
            "✅"
            if min(helper.data["low"]) * 1.25 <= helper.data["close"].iloc[-1]
            else "❌"
        ),
    )

    col22.metric(
        "Current Price is within 25% of 52 week high",
        (
            "✅"
            if max(helper.data["high"]) * 0.75 <= helper.data["close"].iloc[-1]
            else "❌"
        ),
    )

    company = df_tickers[df_tickers["symbol"] == ticker]
    symbol = company["symbol"].values[0]
    name = company["name"].values[0]
    sector = company["sector"].values[0]
    industry = company["subSector"].values[0]
    founded = company["founded"].values[0]

    st.sidebar.markdown(
        f"""
        ## About \n
        Symbol: {symbol}\n
        Name: {name}\n
        Sector: {sector}\n
        Industry: {industry}\n
        Founded: {founded}\n
        """
    )
