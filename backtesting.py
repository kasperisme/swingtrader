from src.fmp import fmp

import plotly.graph_objects as go
from plotly.subplots import make_subplots

f = fmp()

# getting all tickers from SPX
df_sp500 = f.daily_chart("^SPX", "1980-01-01", "2021-12-31")

df_sp500["direction"] = df_sp500["close"] > df_sp500["open"]

df_sp500.loc[df_sp500["direction"] == True, "direction"] = "Green"
df_sp500.loc[df_sp500["direction"] == False, "direction"] = "Red"

SMA = [21, 50, 100, 200]

for sma in SMA:
    df_sp500[f"SMA_{sma}"] = df_sp500["close"].rolling(window=sma).mean()
    df_sp500[f"SMA_{sma}_slope"] = df_sp500[f"SMA_{sma}"].diff()
    df_sp500[f"SMA_{sma}_direction"] = (df_sp500[f"SMA_{sma}_slope"] > 0).astype(int)

    df_sp500[f"SMA_{sma}_vol"] = df_sp500["volume"].rolling(window=sma).mean()
    df_sp500[f"SMA_{sma}_vol_slope"] = df_sp500[f"SMA_{sma}_vol"].diff()
    df_sp500[f"SMA_{sma}_vol_direction"] = (
        df_sp500[f"SMA_{sma}_vol_slope"] > 0
    ).astype(int)


startcap = 10000
currcap = startcap
trailingstoploss = 0.0
stoploss = 0.1
inmarket = False

entries = []
exits = []
trades = []

entryprice = 0.0
exitprice = 0.0
previousclose = 0.0
timesinceexit = 0


uptrendperiod = 5
#            and df_sp500.iloc[index - uptrendperiod : index][f"SMA_50_direction"].sum()== uptrendperiod
for index, row in df_sp500.iterrows():

    if row[f"SMA_100"] is not None:
        if (
            inmarket == False
            and row[f"close"] >= row[f"SMA_200"]
            and row[f"close"] >= row[f"SMA_100"]
            and row[f"SMA_21"] >= row[f"SMA_50"]
            and df_sp500.iloc[index - uptrendperiod : index][f"SMA_100_direction"].sum()
            == uptrendperiod
            and row["SMA_200_direction"] == 1
        ):
            entries.append({"date": row["date"]})
            trades.append({"date": row["date"], "type": "entry"})
            inmarket = True
            trailingstoploss = row["close"] * (1 - stoploss)
            entryprice = row["close"]
            previousclose = row["close"]

        if (
            inmarket == True
            and row["close"] < trailingstoploss
            and row["SMA_100_vol"] > row["SMA_200_vol"]
        ):
            exitprice = row["close"]
            profit = (exitprice - entryprice) / entryprice
            exits.append({"date": row["date"], "profit": profit})
            trades.append({"date": row["date"], "type": "exit", "profit": profit})
            inmarket = False
            currcap = currcap + currcap * profit

        if inmarket == True and row["close"] > previousclose:
            previousclose = row["close"]
            trailingstoploss = row["close"] * (1 - stoploss)

        if inmarket == False:
            timesinceexit += 1
        else:
            timesinceexit = 0

if inmarket == True:
    exitprice = row["close"]
    profit = exitprice - entryprice
    profitpct = profit / entryprice
    exits.append({"date": row["date"], "profit%": profitpct, "profit": profit})
    trades.append(
        {"date": row["date"], "type": "exit", "profit%": profitpct, "profit": profit}
    )
    inmarket = False

template = "plotly_dark"
fig = make_subplots(
    rows=2,
    cols=1,
    shared_xaxes=True,
    vertical_spacing=0.03,
    subplot_titles=("OHLC", "Volume"),
    row_width=[0.5, 0.5],
)

fig.update_layout(
    template=template,
    yaxis_autorange=True,
    yaxis_fixedrange=False,
    xaxis_rangeslider_visible=False,
)
fig.update_yaxes(type="log")

fig.add_trace(
    go.Candlestick(
        x=df_sp500["date"],
        open=df_sp500["open"],
        high=df_sp500["high"],
        low=df_sp500["low"],
        close=df_sp500["close"],
    ),
    row=1,
    col=1,
)


fig.add_trace(
    go.Bar(
        x=df_sp500["date"],
        y=df_sp500["volume"],
        marker_color=df_sp500["direction"],
        showlegend=False,
    ),
    row=2,
    col=1,
)


for sma in SMA:
    fig.add_trace(
        go.Scatter(x=df_sp500["date"], y=df_sp500[f"SMA_{sma}"], mode="lines"),
        row=1,
        col=1,
    )

    fig.add_trace(
        go.Scatter(x=df_sp500["date"], y=df_sp500[f"SMA_{sma}_vol"], mode="lines"),
        row=2,
        col=1,
    )
for entry in entries:
    fig.add_trace(
        go.Scatter(
            x=[entry["date"]],
            y=[df_sp500[df_sp500["date"] == entry["date"]]["close"].values[0]],
            mode="markers",
            marker=dict(color="blue", size=10),
            showlegend=False,
        ),
        row=1,
        col=1,
    )

for exit in exits:
    fig.add_trace(
        go.Scatter(
            x=[exit["date"]],
            y=[df_sp500[df_sp500["date"] == exit["date"]]["close"].values[0]],
            mode="markers",
            marker=dict(color="white", size=10),
            showlegend=False,
        ),
        row=1,
        col=1,
    )


fig.write_html("./output/output.html")

print(currcap)
print(
    startcap
    + startcap
    * (df_sp500["close"].iloc[-1] - df_sp500["close"].iloc[0])
    / df_sp500["close"].iloc[0]
)
