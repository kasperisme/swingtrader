from src.fmp import fmp

import pandas as pd

import plotly.graph_objects as go
from plotly.subplots import make_subplots
import plotly.express as px

from datetime import datetime, timedelta

f = fmp()

# region ######## Parameter control ########
ticker = "^SPX"

years = 20
today = datetime.today()
startdate = today - timedelta(days=365 * years)

startcapital = 10000
capital = startcapital
# number of days the trend has to persist
trend_days = 2
count_trend = 0

# endregion ######## Parameter control ########
# getting all tickers from SPX
df_index = f.daily_chart(
    ticker, startdate.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")
)

df_index = df_index.sort_values("date")

# finding the direction of the day
df_index["direction"] = df_index["close"] > df_index["open"]

df_index.loc[df_index["direction"] == True, "direction"] = "Green"
df_index.loc[df_index["direction"] == False, "direction"] = "Red"

# calculate the OBV
df_index["OBV"] = df_index["volume"] * (
    (df_index["close"] - df_index["close"].shift(1) > 0).astype(int) * 2 - 1
)
df_index["OBV"] = df_index["OBV"].fillna(0)
df_index["OBV"].iloc[0] = 0

df_index["OBV"] = df_index["OBV"].cumsum()


# region ######## Moving averages ########
SMA = [10, 21, 50, 100, 150, 200]
for sma in SMA:
    df_index[f"SMA_{sma}"] = df_index["close"].rolling(window=sma).mean()
    df_index[f"SMA_{sma}_slope"] = df_index[f"SMA_{sma}"].diff()
    df_index[f"SMA_{sma}_velocity"] = abs(df_index[f"SMA_{sma}_slope"].diff())
    df_index[f"SMA_{sma}_direction"] = (df_index[f"SMA_{sma}_slope"] > 0).astype(int)

    df_index[f"SMA_{sma}_vol"] = df_index["volume"].rolling(window=sma).mean()
    df_index[f"SMA_{sma}_vol_slope"] = df_index[f"SMA_{sma}_vol"].diff()
    df_index[f"SMA_{sma}_vol_velocity"] = abs(df_index[f"SMA_{sma}_slope"].diff())
    df_index[f"SMA_{sma}_vol_direction"] = (
        df_index[f"SMA_{sma}_vol_slope"] > 0
    ).astype(int)

    df_index[f"OBV_SMA_{sma}"] = df_index["OBV"].rolling(window=sma).mean()
    df_index[f"OBV_SMA_{sma}_slope"] = df_index[f"OBV_SMA_{sma}"].diff()
    df_index[f"OBV_SMA_{sma}_velocity"] = abs(df_index[f"OBV_SMA_{sma}_slope"].diff())
    df_index[f"OBV_SMA_{sma}_direction"] = (
        df_index[f"OBV_SMA_{sma}_slope"] > 0
    ).astype(int)

# endregion ######## Moving averages ########
# region ######## Trading ########

print("start backtesting")
print("____________________")
scaled_back = []
profit_ls = []

exitdate = None
entrydate = df_index["date"].iloc[0]
entryprice = df_index["close"].iloc[0]
exitprice = 0

# Gode resultater (slår indeksen, ved at handle smart på indekset) på følgende strategi:
"""
Exit:
        row["SMA_10_velocity"] > 1.8
        and row["OBV_SMA_10"] < row["OBV_SMA_21"]
        and row["close"] < row["SMA_50"]
        and row["close"] < row["SMA_150"]

Entry:
        row["SMA_50_slope"] > 0
        and row["SMA_21_slope"] > 0
        and row["SMA_50"] >= row["SMA_100"]
"""


for i, row in df_index.iterrows():
    # Complete exit strategy
    if (
        row["SMA_10_velocity"] > 1.8
        and row["OBV_SMA_10"] < row["OBV_SMA_21"]
        and row["close"] < row["SMA_50"]
        and row["close"] < row["SMA_150"]
        and exitdate is None
    ):
        if count_trend < trend_days:
            count_trend += 1
        else:
            exitdate = row["date"]
            exitprice = row["close"]

            profittaking = {
                "entrydate": entrydate,
                "exitdate": exitdate,
                "range": row["close"] - entryprice,
                "change": (row["close"] - entryprice) / entryprice,
            }
            profit_ls.append(profittaking)

            capital = capital * (1 + profittaking["change"])

            entrydate = None
    else:
        count_trend = 0

    # entry strategy
    if (
        row["SMA_50_slope"] > 0
        and row["SMA_21_slope"] > 0
        and row["SMA_100_slope"] > 0
        and row["SMA_50"] >= row["SMA_100"]
        and exitdate is not None
    ):

        entrydate = row["date"]
        entryprice = row["close"]
        scaled_back.append({"x0": exitdate, "x1": entrydate})

        """
        print("Exit date:", exitdate)
        print("Exit price:", exitprice)
        print("Entry date:", entrydate)
        print("Entry price:", entryprice)
        print("Price range:", exitprice - entryprice)
        print("Change:", ((exitprice - entryprice) / exitprice) * 100)
        print("____________________")
        """
        count_trend = 0
        exitdate = None

# calculate the end profit
# only if the trade is still open today
if startdate is not None:
    row = df_index.iloc[-1]

    profittaking = {
        "exitdate": row["date"],
        "range": row["close"] - entryprice,
        "change": (row["close"] - entryprice) / entryprice,
    }

    profit_ls.append(profittaking)

    capital = capital * (1 + profittaking["change"])

print("Profit:")

print(capital)
print(capital / startcapital)

print("SPX:")
print(df_index["close"].iloc[0])
print(df_index["close"].iloc[-1] / df_index["close"].iloc[0])

# region ######## Plotting ########
template = "plotly_dark"
fig = make_subplots(
    rows=3,
    cols=1,
    shared_xaxes=True,
    vertical_spacing=0.03,
    subplot_titles=("OHLC", "Slope", "Velocity"),
    row_width=[0.15, 0.15, 0.7],
    specs=[
        [{"type": "candlestick"}],
        [{"type": "bar"}],
        [{"type": "xy", "secondary_y": True}],
    ],
)

fig.update_layout(
    template=template,
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
    go.Scatter(x=df_index["date"], y=df_index["OBV_SMA_10"], name="OBV_SMA_10"),
    row=2,
    col=1,
)

fig.add_trace(
    go.Scatter(x=df_index["date"], y=df_index["OBV_SMA_21"], name="OBV_SMA_21"),
    row=2,
    col=1,
)

fig.add_trace(
    go.Scatter(
        x=df_index["date"],
        y=df_index["OBV_SMA_50"],
        name="OBV_SMA_50",
    ),
    row=2,
    col=1,
)


fig.add_trace(
    go.Scatter(
        x=df_index["date"], y=df_index["SMA_21_velocity"], name="SMA_21_velocity"
    ),
    row=3,
    col=1,
)

fig.add_trace(
    go.Scatter(
        x=df_index["date"], y=df_index["SMA_50_velocity"], name="SMA_50_velocity"
    ),
    row=3,
    col=1,
)

fig.add_trace(
    go.Scatter(
        x=df_index["date"], y=df_index["SMA_100_velocity"], name="SMA_100_velocity"
    ),
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


for i in scaled_back:
    fig.add_vrect(
        x0=i["x0"],
        x1=i["x1"],
        fillcolor="red",
        opacity=0.25,
        layer="below",
        row=1,
        col=1,
    )

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
fig.write_html(f"./output/{ticker}_trend.html")
df_index.to_excel(f"./output/{ticker}_trend.xlsx", index=False)
