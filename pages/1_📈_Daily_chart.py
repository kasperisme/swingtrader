import streamlit as st
from datetime import datetime, timedelta
from src import fundamentals
import pandas as pd
from src import technical

fund = fundamentals.Fundamentals()
helper = technical.technical()


@st.cache_data
def get_tickers():

    index = ["NYSE", "NASDAQ"]

    df_col = []
    for i in index:
        df = helper.get_exhange_tickers(i)
        df_col.append(df)

    df_tickers = pd.concat(df_col, axis=0)

    df_tickers["label"] = df_tickers["symbol"] + " - " + df_tickers["name"]

    df_sp500 = helper.get_sp500_tickers()

    return df_tickers, df_sp500


@st.cache_data
def get_ticker_data(ticker, curr_ticker):
    period = 365
    strf = "%Y-%m-%d"

    today = datetime.today()
    startdate = today - timedelta(days=period)

    st.plotly_chart(
        helper.get_complete_graph(
            ticker,
            startdate=startdate.strftime(strf),
            enddate=today.strftime(strf),
            shares_outstanding=curr_ticker["sharesOutstanding"],
            include_trend_template=False,
        ),
    )

    st.plotly_chart(
        fund.get_earnings_graph(
            ticker,
            startdate=startdate,
            enddate=today,
        ),
    )

    company = df_tickers[df_tickers["symbol"] == ticker]

    symbol = company["symbol"].values[0]
    name = company["name"].values[0]
    sharesoutstanding = curr_ticker["sharesOutstanding"]
    turnovertate = round(period / helper.data["relative_volume"].sum(), 2)
    consensusprice = round(
        sum(helper.data["relative_volume"] * helper.data["close"])
        / sum(helper.data["relative_volume"]),
        2,
    )

    st.sidebar.markdown(
        f"""
        ## About \n
        Symbol: {symbol}\n
        Name: {name}\n
        Stocks outstanding: {sharesoutstanding}\n
        Turnover rate: {turnovertate} days\n
        Holders entry level: $ {consensusprice}\n
        """
    )


if "ticker_index" not in st.session_state:
    st.session_state["ticker_index"] = 0
    st.session_state["trend_template"] = []

st.set_page_config(
    page_title="Ticker screener",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("# Daily chart - 1 year")
st.sidebar.header("Plotting Daily chart - 1 year")

df_tickers = helper.get_sp500_tickers()

df_tickers, df_sp500 = get_tickers()

tickers = df_tickers["symbol"].to_list()

tickers_sp500 = df_sp500["symbol"].to_list()

df_quote = helper.get_quote_prices(tickers_sp500)

df = helper.get_change_prices(tickers_sp500)

df_quote = df_quote.sort_values("symbol")

df_quote["label"] = df_quote["symbol"] + " - " + df_quote["name"]

colselect1, colselect2, colselect3 = st.columns(
    [0.2, 0.6, 0.2], vertical_alignment="bottom"
)

ls_labels = df_tickers["symbol"].tolist()

ls_len = len(ls_labels)

label = colselect2.selectbox(
    f"Choose a ticker ({ls_len} available):",
    ls_labels,
)

if label:
    ticker = label

    curr_ticker = df_tickers[df_tickers["symbol"] == ticker].iloc[0]

    get_ticker_data(ticker, curr_ticker)
