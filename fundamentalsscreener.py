from src import fundamentals
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import plotly.express as px
from src.logging import logger

fund = fundamentals.Fundamentals()

df_tickers = pd.read_excel("output/CPH_trend_template.xlsx")
df_tickers = df_tickers[df_tickers["Passed"] == True]

# df_tickers = df_tickers[df_tickers["ticker"] == "ROCK-B.CO"]

print(df_tickers)


df_earn = pd.DataFrame()
today = pd.Timestamp.today()

err_ls = []
for t in df_tickers["ticker"]:
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

        df["revenue_sma"] = df["revenue"].rolling(window=4).mean()
        df["revenue_sma_slope"] = df["revenue_sma"].diff()
        df["revenue_sma_direction"] = (df["revenue_sma_slope"] > 0).astype(int)

        df_earn = pd.concat([df_earn, df], axis=0)
    except Exception as e:
        err_ls.append(t)
        logger.error(f"Error in earnings: {t}")


# ////////////////////////////////////////////////////////////
fig = make_subplots(rows=2, cols=2, shared_xaxes=True)

print(df_earn)

buttons = []
for t in df_tickers["ticker"]:
    if t not in err_ls:
        button = {
            "label": t,
            "method": "update",
            "args": [
                {
                    "yaxis0.data": [
                        df_earn[df_earn["symbol"] == t]["eps"],
                        df_earn[df_earn["symbol"] == t]["epsEstimated"],
                        df_earn[df_earn["symbol"] == t]["eps_sma"],
                    ],
                    "yaxis1.data": [
                        df_earn[df_earn["symbol"] == t]["eps_sma_slope"],
                    ],
                    "yaxis2.data": [
                        df_earn[df_earn["symbol"] == t]["revenue"],
                        df_earn[df_earn["symbol"] == t]["revenueEstimated"],
                        df_earn[df_earn["symbol"] == t]["revenue_sma"],
                    ],
                    "yaxis3.data": [
                        df_earn[df_earn["symbol"] == t]["revenue_sma_slope"],
                    ],
                },
            ],
        }

        buttons.append(button)

fig.update_layout(
    updatemenus=[
        dict(
            type="buttons",
            direction="left",
            buttons=buttons,
            pad={"r": 10, "t": 10},
            showactive=True,
            x=0.11,
            xanchor="left",
            y=1.1,
            yanchor="top",
        ),
    ]
)

fig.add_trace(
    go.Scatter(
        x=df_earn["date"],
        y=df_earn["eps"],
        opacity=0.5,
        mode="lines",
        name="EPS",
    ),
    row=1,
    col=1,
)

fig.add_trace(
    go.Scatter(
        x=df_earn["date"],
        y=df_earn["epsEstimated"],
        mode="lines",
        name="epsEst",
        opacity=0.5,
    ),
    row=1,
    col=1,
)

fig.add_trace(
    go.Scatter(
        x=df_earn["date"],
        y=df_earn["eps_sma"],
        mode="lines",
        name="epsSMA",
    ),
    row=1,
    col=1,
)

fig.add_trace(
    go.Scatter(
        x=df_earn["date"],
        y=df_earn["eps_sma_slope"],
        mode="lines",
        name="epsSMASlope",
    ),
    row=1,
    col=2,
)

# ////////////////////////////////////////////////////////////

fig.add_trace(
    go.Scatter(
        x=df_earn["date"],
        y=df_earn["revenue"],
        mode="lines",
        name="Revenue",
        opacity=0.5,
    ),
    row=2,
    col=1,
)

fig.add_trace(
    go.Scatter(
        x=df_earn["date"],
        y=df_earn["revenueEstimated"],
        mode="lines",
        name="RevenueEst",
        opacity=0.5,
    ),
    row=2,
    col=1,
)

fig.add_trace(
    go.Scatter(
        x=df_earn["date"],
        y=df_earn["revenue_sma"],
        mode="lines",
        name="revenueSMA",
    ),
    row=2,
    col=1,
)

fig.add_trace(
    go.Scatter(
        x=df_earn["date"],
        y=df_earn["revenue_sma_slope"],
        mode="lines",
        name="revenueSMASlope",
    ),
    row=2,
    col=2,
)

# ////////////////////////////////////////////////////////////
fig.show()
