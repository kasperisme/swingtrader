from src import fundamentals
from src.fmp import fmp

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import plotly.express as px
from src.logging import logger

fund = fundamentals.Fundamentals()
f = fmp()

df_tickers = pd.read_excel("./output/SPX_trend_template.xlsx")


# df_tickers = df_tickers[df_tickers["Passed"] == True]
ticker = "CMRE"
tickers = [ticker]

df_earn = pd.DataFrame()
today = pd.Timestamp.today()

err_ls = []
df_col = []
for t in tickers:
    # get the fast quotes for all tickers
    try:
        df = fund.get_earnings(t)
        df = df.dropna(subset=["eps", "revenue"])
        df = df.sort_values("date")
        df["date"] = pd.to_datetime(df["date"])
        df = df[df["date"] < today]

        df["eps_sma"] = df["eps"].rolling(window=4).mean()
        df["eps_sma_slope"] = df["eps_sma"].diff()
        df["eps_sma_direction"] = (df["eps_sma_slope"] > 0).astype(int)
        df["eps_pct_change"] = df["eps"].diff() / abs(df["eps"].shift(1))
        df["eps_pct_change_annual"] = df["eps"].diff() / abs(df["eps"].shift(4))
        df["eps_sma_gap"] = df["eps"] - df["eps_sma"]

        mask = df["eps_sma_slope"] > 0
        df["eps_sma_slope_above"] = 0.0
        df["eps_sma_slope_below"] = 0.0
        df.loc[mask, "eps_sma_slope_above"] = df.loc[mask, "eps_sma_slope"]
        df.loc[~mask, "eps_sma_slope_below"] = df.loc[~mask, "eps_sma_slope"]

        mask = df["eps_sma_gap"] > 0
        df["eps_sma_gap_above"] = 0.0
        df["eps_sma_gap_below"] = 0.0
        df.loc[mask, "eps_sma_gap_above"] = df.loc[mask, "eps_sma_gap"]
        df.loc[~mask, "eps_sma_gap_below"] = df.loc[~mask, "eps_sma_gap"]

        df["revenue_sma"] = df["revenue"].rolling(window=4).mean()
        df["revenue_sma_slope"] = df["revenue_sma"].diff()
        df["revenue_sma_direction"] = (df["revenue_sma_slope"] > 0).astype(int)
        df["revenue_pct_change"] = df["revenue"].diff() / abs(df["revenue"].shift(1))
        df["revenue_pct_change_annual"] = df["revenue"].diff() / abs(
            df["revenue"].shift(4)
        )

        df_col.append(df)
    except Exception as e:
        err_ls.append(t)
        logger.error(f"Error in earnings: {t}")

df_earn = pd.concat(df_col, axis=0)
df_earn = df_earn.reset_index(drop=True)

df_index = f.daily_chart(
    ticker,
    (min(df_earn["date"])).strftime("%Y-%m-%d"),
    (max(df_earn["date"])).strftime("%Y-%m-%d"),
)
# ////////////////////////////////////////////////////////////
fig = make_subplots(
    rows=4,
    cols=1,
    shared_xaxes=True,
    row_width=[0.15, 0.15, 0.15, 0.7],
)
template = "plotly_dark"

fig.update_layout(
    template=template,
    yaxis_fixedrange=False,
    xaxis_rangeslider_visible=False,
)


mask = df_earn["symbol"] == ticker

fig.add_trace(
    go.Ohlc(
        x=df_index["date"],
        open=df_index["open"],
        high=df_index["high"],
        low=df_index["low"],
        close=df_index["close"],
    ),
    row=1,
    col=1,
)

fig.add_trace(
    go.Scatter(
        x=df_earn[mask]["date"],
        y=df_earn[mask]["eps"],
        opacity=0.5,
        mode="lines",
        name="EPS",
    ),
    row=2,
    col=1,
)

fig.add_trace(
    go.Scatter(
        x=df_earn[mask]["date"],
        y=df_earn[mask]["epsEstimated"],
        mode="lines",
        name="epsEst",
        opacity=0.5,
    ),
    row=2,
    col=1,
)

fig.add_trace(
    go.Scatter(
        x=df_earn[mask]["date"],
        y=df_earn[mask]["eps_sma"],
        mode="lines",
        name="epsSMA",
    ),
    row=2,
    col=1,
)


fig.add_trace(
    go.Scatter(
        x=df_earn[mask]["date"],
        y=df_earn[mask]["eps_sma_slope_above"],
        name="eps_slope",
        fill="tozeroy",
        mode="none",
        fillcolor="green",
    ),
    row=3,
    col=1,
)

fig.add_trace(
    go.Scatter(
        x=df_earn[mask]["date"],
        y=df_earn[mask]["eps_sma_slope_below"],
        name="eps_slope",
        fill="tozeroy",
        mode="none",
        fillcolor="red",
    ),
    row=3,
    col=1,
)

fig.add_trace(
    go.Scatter(
        x=df_earn[mask]["date"],
        y=df_earn[mask]["eps_sma_gap_above"],
        name="eps_gap",
        fill="tozeroy",
        mode="none",
        fillcolor="green",
    ),
    row=4,
    col=1,
)

fig.add_trace(
    go.Scatter(
        x=df_earn[mask]["date"],
        y=df_earn[mask]["eps_sma_gap_below"],
        name="eps_gap",
        fill="tozeroy",
        mode="none",
        fillcolor="red",
    ),
    row=4,
    col=1,
)

df_earn.to_excel("./output/earnings.xlsx")
# ////////////////////////////////////////////////////////////
fig.show()
