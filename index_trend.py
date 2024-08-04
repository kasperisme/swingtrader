from src.fmp import fmp

import pandas as pd

import plotly.graph_objects as go
from plotly.subplots import make_subplots
import plotly.express as px

from datetime import datetime, timedelta

f = fmp()

# region ######## Parameter control ########
ticker = "^SP500-15"  # S&P 500 Materials (Sector)
ticker = "^SP500-20"  # S&P 500 Industrials (Sector)
ticker = "^SP500-25"  # S&P 500 Consumer Discretionary (Sector) - this is the second most interesting
ticker = "^SP500-30"  # S&P 500 Consumer Staples (Sector)
ticker = "^SP500-35"  # S&P 500 Health Care (Sector)
ticker = "^SP500-40"  # S&P 500 Financials (Sector), this is the most interesting
ticker = "^SP500-45"  # S&P 500 Information Technology (Sector)
ticker = "^SP500-50"  # S&P 500 Communication Services
ticker = "^SP500-55"  # S&P 500 Utilities (Sector)
ticker = "^SP500-60"  # S&P 500 Real Estate (Sector)


ticker = "^SPX"
years = 27
today = datetime.today()
startdate = today - timedelta(days=365 * years)

startcapital = 10000
capital = startcapital


# number of days the trend has to persist
trend_days = 1
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


# calculate distances between moving averages

df_index["SMA_21_50"] = (df_index["SMA_21"] - df_index["SMA_50"]) / df_index["close"]
df_index["SMA_50_100"] = (df_index["SMA_50"] - df_index["SMA_100"]) / df_index["close"]
df_index["SMA_100_150"] = (df_index["SMA_100"] - df_index["SMA_150"]) / df_index[
    "close"
]
df_index["SMA_150_200"] = (df_index["SMA_150"] - df_index["SMA_200"]) / df_index[
    "close"
]


# endregion ######## Moving averages ########
# region ######## Trading ########

# ^SPX:
velocity_bound = 1.8


print("start backtesting")
print("____________________")
print("Ticker:", ticker)
print("Start capital:", startcapital)
print("Start date:", startdate)
print("End date:", today)
print("Velocity bound:", velocity_bound)
print("____________________")

scaled_back = []
complete_exit = []
profit_ls = []
scaled_ls = []
earlyalarm = []

downscaleddate = None
downscaleprice = 0
upscaleddate = None
upscaleprice = 0
exitedlow = 0
lowcount = 0

exitdate = None
exitprice = 0
entrydate = df_index["date"].iloc[0]
entryprice = df_index["close"].iloc[0]

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
        and row["SMA_100_slope"] > 0
        and row["SMA_50"] >= row["SMA_100"]
"""
# Forklaring:
# når SMA_10_velocity er høj, så er der momentum i markedet


for i, row in df_index.iterrows():

    # downscale strategy
    # only scaling back if the trade is still open
    if (
        row["SMA_10_velocity"] > velocity_bound
        and row["OBV_SMA_10"] < row["OBV_SMA_21"]
        and row["close"] < row["SMA_21"]
        and (
            row["close"] < row["SMA_50"]
            or row["close"] < row["SMA_100"]
            or row["close"] < row["SMA_200"]
        )
        and exitdate is None
        and downscaleddate is None
    ):
        downscaleddate = row["date"]
        downscaleprice = row["close"]
        upscaleddate = None
    # upscaling strategy
    if (
        row["SMA_10_slope"] > 0
        and row["SMA_21_slope"] > 0
        and row["SMA_50_slope"] > 0
        and row["SMA_21"] >= row["SMA_50"]
        and downscaleddate is not None
    ):
        upscaleddate = row["date"]
        upscaleprice = row["close"]
        scaled_back.append({"x0": downscaleddate, "x1": upscaleddate})

        scaled_results = {
            "upscaleddate": upscaleddate,
            "downscaleddate": downscaleddate,
            "range": downscaleprice - row["close"],
            "change": ((downscaleprice - row["close"]) / downscaleprice) * 0.5,
        }

        scaled_ls.append(scaled_results)

        # capital = capital * (1 + scaled_results["change"])

        downscaleddate = None

    # Complete exit strategy
    if (
        row["SMA_10_velocity"] > velocity_bound
        and row["OBV_SMA_10"] < row["OBV_SMA_21"]
        and row["close"] < row["SMA_50"]
        and row["close"] < row["SMA_150"]
        and exitdate is None
    ):
        if count_trend <= trend_days:
            earlyalarm.append(
                {"x": row["date"], "y": row["high"], "count": count_trend}
            )
            count_trend += 1
        else:
            # starting exit
            exitdate = row["date"]
            exitprice = row["close"]
            exitedlow = row["low"]

            # if complete exit, then scaling is cancelled on date
            scaled_results = {
                "upscaleddate": None,
                "downscaleddate": downscaleddate,
                "range": downscaleprice - row["close"],
                "change": ((downscaleprice - row["close"]) / downscaleprice) * 0.5,
            }

            scaled_ls.append(scaled_results)
            scaled_back.append({"x0": downscaleddate, "x1": exitdate})

            downscaleddate = None

            # capital = capital * (1 + (scaled_results["change"]))

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
        complete_exit.append({"x0": exitdate, "x1": entrydate})

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

if exitdate is not None:
    complete_exit.append({"x0": exitdate, "x1": df_index["date"].iloc[-1]})

if downscaleddate is not None:
    scaled_back.append({"x0": downscaleddate, "x1": df_index["date"].iloc[-1]})


# summarize the results
print("Profit:")
print(capital / startcapital)

print(f"{ticker} staying in:")
print(df_index["close"].iloc[-1] / df_index["close"].iloc[0])

if exitdate is not None:
    print("Exit market")

# endregion ######## Trading ########
# region ######## Plotting ########
template = "plotly_dark"
fig = make_subplots(
    rows=3,
    cols=1,
    shared_xaxes=True,
    vertical_spacing=0.03,
    subplot_titles=("OHLC", "OBV", "Velocity"),
    row_width=[0.15, 0.15, 0.7],
    specs=[
        [{"type": "OHLC"}],
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
        x=df_index["date"], y=df_index["SMA_10_velocity"], name="SMA_10_velocity"
    ),
    row=3,
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

fig.add_hline(y=velocity_bound, line_dash="dot", line_color="red", row=3, col=1)

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


for i in complete_exit:
    fig.add_vrect(
        x0=i["x0"],
        x1=i["x1"],
        fillcolor="red",
        opacity=0.25,
        layer="below",
        row=1,
        col=1,
    )

for i in scaled_back:
    fig.add_vrect(
        x0=i["x0"],
        x1=i["x1"],
        fillcolor="yellow",
        opacity=0.25,
        layer="below",
        row=1,
        col=1,
    )

for i in earlyalarm:
    fig.add_annotation(
        x=i["x"],
        y=i["y"],
        text=f"{i['count']+1}",
        showarrow=True,
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
