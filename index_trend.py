from src.fmp import fmp

import pandas as pd

import plotly.graph_objects as go
from plotly.subplots import make_subplots
import plotly.express as px

from datetime import datetime, timedelta

f = fmp()

index = "^SPX"

# index = "^OMXC20"


today = datetime.today()
startdate = today - timedelta(days=365 * 18)

# getting all tickers from SPX
df_index = f.daily_chart(
    index, startdate.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")
)

df_index["direction"] = df_index["close"] > df_index["open"]

df_index.loc[df_index["direction"] == True, "direction"] = "Green"
df_index.loc[df_index["direction"] == False, "direction"] = "Red"

SMA = [10, 21, 50, 100, 200]

for sma in SMA:
    df_index[f"SMA_{sma}"] = df_index["close"].rolling(window=sma).mean()
    df_index[f"SMA_{sma}_slope"] = df_index[f"SMA_{sma}"].diff()
    df_index[f"SMA_{sma}_direction"] = (df_index[f"SMA_{sma}_slope"] > 0).astype(int)

    df_index[f"SMA_{sma}_vol"] = df_index["volume"].rolling(window=sma).mean()
    df_index[f"SMA_{sma}_vol_slope"] = df_index[f"SMA_{sma}_vol"].diff()
    df_index[f"SMA_{sma}_vol_direction"] = (
        df_index[f"SMA_{sma}_vol_slope"] > 0
    ).astype(int)


df_index["OBV"] = df_index["volume"] * (
    (df_index["close"] - df_index["close"].shift(1) > 0).astype(int) * 2 - 1
)

df_index["OBV"] = df_index["OBV"].cumsum()

df_index["OBV_SMA_21"] = df_index["OBV"].rolling(window=21).mean()


def get_corr(ser):
    rolling_df = df_index.loc[ser.index]
    return rolling_df["OBV_SMA_21"].corr(rolling_df["SMA_21"])


df_index["ROLL_CORR"] = df_index["close"].rolling(10).apply(get_corr)

df_index["RVOL"] = df_index["volume"] / df_index[f"SMA_10_vol"]

# finding

df_index["ROLL_CORR"] = df_index["ROLL_CORR"].clip(1, 0.96)

mask = (df_index["ROLL_CORR"] < 0.85) & (df_index["ROLL_CORR"] > -0.85)

df_index["TopIndicator"] = mask
df_index["TopIndicator"] = df_index["TopIndicator"].astype(int)

# region ######## Plotting ########
template = "plotly_dark"
fig = make_subplots(
    rows=3,
    cols=1,
    shared_xaxes=True,
    vertical_spacing=0.03,
    subplot_titles=("OHLC", "Volume"),
    row_width=[0.5, 0.01, 0.5],
    specs=[
        [{"type": "candlestick"}],
        [{"type": "bar"}],
        [{"type": "xy", "secondary_y": True}],
    ],
)

fig.update_layout(
    template=template,
    yaxis_autorange=True,
    yaxis_fixedrange=False,
    xaxis_rangeslider_visible=False,
)

fig.add_trace(
    go.Candlestick(
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
    go.Bar(
        x=df_index["date"],
        y=df_index["volume"],
        marker_color=df_index["direction"],
        showlegend=False,
    ),
    row=2,
    col=1,
)

fig.add_trace(
    go.Scatter(x=df_index["date"], y=df_index["ROLL_CORR"]),
    row=3,
    col=1,
)

for sma in SMA:
    fig.add_trace(
        go.Scatter(
            x=df_index["date"],
            y=df_index[f"SMA_{sma}"],
            mode="lines",
            name=f"SMA_{sma}",
        ),
        row=1,
        col=1,
    )

    fig.add_trace(
        go.Scatter(
            x=df_index["date"],
            y=df_index[f"SMA_{sma}_vol"],
            mode="lines",
            name=f"SMA_{sma}_vol",
        ),
        row=2,
        col=1,
    )


startdate = None
for i, row in df_index.iterrows():
    if row["TopIndicator"] == 1 and startdate is None:
        startdate = row["date"]

    if row["TopIndicator"] == 0 and startdate is not None:
        fig.add_vrect(
            x0=startdate,
            x1=row["date"],
            fillcolor="red",
            opacity=0.25,
            layer="below",
            row=1,
            col=1,
        )

        print(startdate, row["date"])
        startdate = None

dt_all = pd.date_range(
    start=df_index["date"].iloc[0], end=df_index["date"].iloc[-1], freq="1D"
)

# check which dates from your source that also accur in the continuous date range
dt_obs = [d.strftime("%Y-%m-%d %H:%M:%S") for d in df_index["date"]]

# isolate missing timestamps
dt_breaks = [
    d for d in dt_all.strftime("%Y-%m-%d %H:%M:%S").tolist() if not d in dt_obs
]

# adjust xaxis for rangebreaks
fig.update_xaxes(rangebreaks=[dict(dvalue=24 * 60 * 60 * 1000, values=dt_breaks)])


# endregion ######## Plotting ########


fig.write_html(f"./output/{index}_trend.html")
df_index.to_excel(f"./output/{index}_trend.xlsx", index=False)
