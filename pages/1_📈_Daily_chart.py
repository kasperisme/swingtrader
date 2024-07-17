import streamlit as st
from datetime import datetime, timedelta

from src import technical

helper = technical.technical()


def increment_counter():
    st.session_state["ticker_index"] += 1


def decrement_counter():
    st.session_state["ticker_index"] -= 1


def reset_counter():
    st.session_state["ticker_index"] = 0


def set_counter(df, index):
    st.session_state["ticker_index"] = index


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
        ),
    )

    st.sidebar.markdown("## Minervini trend template")
    col01, col02 = st.sidebar.columns(2)

    trend_template_dict = helper.trend_template_dict

    st.session_state["trend_template"].append(trend_template_dict)

    col01.metric(
        "All passed",
        ("✅" if trend_template_dict["Passed"] else "❌"),
    )

    col02.metric(
        "SMA150 above SMA200",
        ("✅" if trend_template_dict["SMA150AboveSMA200"] else "❌"),
    )

    col11, col12 = st.sidebar.columns(2)

    col11.metric(
        "SMA50 above SMA150 and 200",
        ("✅" if trend_template_dict["SMA50AboveSMA150And200"] else "❌"),
    )

    col12.metric(
        "SMA200 200 day slope",
        ("✅" if trend_template_dict["SMA200Slope"] else "❌"),
    )

    col21, col22 = st.sidebar.columns(2)

    col21.metric(
        "Current stock price is 25% above 52 weeks low",
        ("✅" if trend_template_dict["PriceAbove25Percent52WeekLow"] else "❌"),
    )

    col22.metric(
        "Current Price is within 25% of 52 week high",
        ("✅" if trend_template_dict["PriceWithin25Percent52WeekHigh"] else "❌"),
    )

    col31, col32 = st.sidebar.columns(2)

    col31.metric(
        "Relative Strength is above 70",
        ("✅" if trend_template_dict["RSOver70"] else "❌"),
    )

    col32.metric(
        "Price over SMA150 and 200",
        ("✅" if trend_template_dict["PriceOverSMA150And200"] else "❌"),
    )

    company = df_tickers[df_tickers["symbol"] == ticker]
    symbol = company["symbol"].values[0]
    name = company["name"].values[0]
    sector = company["sector"].values[0]
    industry = company["subSector"].values[0]
    founded = company["founded"].values[0]
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
        Sector: {sector}\n
        Industry: {industry}\n
        Founded: {founded}\n
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

df_tickers = helper.get_tickers()

tickers = df_tickers["symbol"].to_list()
df_quote = helper.get_quote_prices(tickers)

df = helper.get_change_prices(tickers)

df_quote = df_quote.sort_values("symbol")

df_quote["label"] = df_quote["symbol"] + " - " + df_quote["name"]

filter_tickers = st.toggle("Show only stage 2 tickers", on_change=reset_counter)

colselect1, colselect2, colselect3 = st.columns(
    [0.2, 0.6, 0.2], vertical_alignment="bottom"
)


if filter_tickers:
    mask = df_quote["SCREENER"] == 1

    ls_labels = df_quote[mask]["label"].tolist()

    ls_len = len(ls_labels)

    label = colselect2.selectbox(
        f"Choose a ticker ({ls_len} available):",
        ls_labels,
        index=st.session_state["ticker_index"],
    )
    st.session_state["ticker_index"] = ls_labels.index(label)
else:
    ls_labels = df_quote["label"].tolist()

    ls_len = len(ls_labels)

    label = colselect2.selectbox(
        f"Choose a ticker ({ls_len} available):",
        ls_labels,
        index=st.session_state["ticker_index"],
    )
    st.session_state["ticker_index"] = ls_labels.index(label)


prevbtn = colselect1.button("Previous ticker", on_click=decrement_counter)
nextbtn = colselect3.button("Next ticker", on_click=increment_counter)


if label:
    ticker = label.split(" - ")[0]

    curr_ticker = df_quote[df_quote["symbol"] == ticker].iloc[0]

    get_ticker_data(ticker, curr_ticker)
