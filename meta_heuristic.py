import strategies.models as models
import datetime
from src.fmp import fmp
from sklearn.ensemble import RandomForestRegressor
from sklearn.preprocessing import StandardScaler
import xgboost as xgb
from sklearn.model_selection import train_test_split
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from sklearn.model_selection import GridSearchCV
import pandas as pd
from sklearn.metrics import f1_score

scaler = StandardScaler()
f = fmp()
m = models.models()

symbols = open("./output/IBD_trend_template.txt", "r").read().split("\n")

symbols = symbols[:3]

optimize = False
plot_graph = False

startdate = datetime.datetime(2018, 1, 1)
enddate = datetime.datetime(2024, 10, 6)
endcapital = 0

params = {
    "objective": "reg:squarederror",
}

param_grid = {
    "learning_rate": [0.05, 0.10, 0.20],
    "min_child_weight": [1, 5, 10],
    "gamma": [0.5, 1, 5],
    "subsample": [0.6, 0.8, 1.0],
    "colsample_bytree": [0.6, 0.8, 1.0],
    "max_depth": [3, 4, 5],
}

importance = {}
df_collection = []

df, df_intraday = m.dataconstruct(
    "EQH", datetime.datetime(2021, 1, 1), datetime.datetime(2024, 10, 6)
)

# find times where the SP500 moves up upside% and down downside%
upside = 0.15
downside = 0.05


for i, row in df.iterrows():
    # find out if the stoploss or takeprofit was hit first
    # if stoploss was hit, then the trade was a loss
    # if takeprofit was hit, then the trade was a win

    df_future = df.tail(df.shape[0] - i).copy()
    takeprofit = row["close"] * (1 + upside)
    stoploss = row["close"] * (1 - downside)

    df_future["takeprofit_hit"] = df_future["high"] >= takeprofit
    df_future["stoploss_hit"] = df_future["low"] <= stoploss

    # find first instance of takeprofit or stoploss
    takeprofit_hit = df_future[df_future["takeprofit_hit"] == True]
    stoploss_hit = df_future[df_future["stoploss_hit"] == True]

    if takeprofit_hit.empty and stoploss_hit.empty == False:
        # if takeprofit was not hit, then the trade was a loss
        df.loc[i, "stoploss_hit"] = True
        df.loc[i, "takeprofit_hit"] = False
    elif stoploss_hit.empty and takeprofit_hit.empty == False:
        # if stoploss was not hit, then the trade was a win
        df.loc[i, "stoploss_hit"] = False
        df.loc[i, "takeprofit_hit"] = True

    if takeprofit_hit.empty == False and stoploss_hit.empty == False:
        if takeprofit_hit.index[0] > stoploss_hit.index[0]:
            df.loc[i, "stoploss_hit"] = True
            df.loc[i, "takeprofit_hit"] = False
        else:
            df.loc[i, "stoploss_hit"] = False
            df.loc[i, "takeprofit_hit"] = True

    df.loc[i, "takeprofit"] = takeprofit
    df.loc[i, "stoploss"] = stoploss

df["stoploss_hit"].fillna(value=False, inplace=True)
df["takeprofit_hit"].fillna(value=False, inplace=True)

df["takeprofit_hit"] = df["takeprofit_hit"].astype(int)
df["stoploss_hit"] = df["stoploss_hit"].astype(int)


# create a classification model to predict if the trade will be a win or loss

drop_cols = df.columns[df.columns.str.contains("FUTURE")].tolist()
drop_cols.extend(
    [
        "date",
        "label",
        "direction",
        "time",
        "symbol",
        "updatedFromDate",
        "fiscalDateEnding",
        "entry",
        "exit",
    ]
)

cutoff = datetime.datetime(2023, 12, 1)

df_dropped = df[df["date"] < cutoff].copy()

df_dropped = df_dropped.dropna()

y_cols = ["takeprofit_hit", "stoploss_hit"]
X_cols = [col for col in df.columns if col not in drop_cols + y_cols]

X = df_dropped[X_cols].copy()
y = df_dropped[y_cols].copy()

X = scaler.fit_transform(X)

X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, random_state=42
)

xgb_model = xgb.XGBClassifier(**params)
xgb_model.fit(X_train, y_train)

df[["takeprofit_hit_pred", "stoploss_hit_pred"]] = xgb_model.predict(
    scaler.transform(df[X_cols])
)

fig = make_subplots(
    rows=2,
    cols=1,
    shared_xaxes=True,
    vertical_spacing=0.02,
    subplot_titles=("Close price", "Trade outcome"),
)

fig.add_trace(
    go.Candlestick(
        x=df["date"],
        open=df["open"],
        high=df["high"],
        low=df["low"],
        close=df["close"],
    ),
    row=1,
    col=1,
)

for i in df[df["takeprofit_hit_pred"] == 1].index:
    fig.add_trace(
        go.Scatter(
            x=[df.loc[i, "date"]],
            y=[df.loc[i, "close"]],
            mode="markers",
            marker=dict(color="green", size=10),
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=[df.loc[i, "date"]],
            y=[df.loc[i, "takeprofit"]],
            mode="markers",
            marker=dict(color="green", size=10),
            marker_line_width=2,
            marker_symbol="line-ew",
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=[df.loc[i, "date"]],
            y=[df.loc[i, "stoploss"]],
            mode="markers",
            marker=dict(color="red", size=10),
            marker_line_width=2,
            marker_symbol="line-ew",
        ),
        row=1,
        col=1,
    )


fig.add_vline(x=cutoff, line_width=2, line_dash="dash", line_color="black")

fig.update_layout(
    title_text="Win/loss trades",
    yaxis_autorange=True,
    yaxis_fixedrange=False,
    xaxis_rangeslider_visible=False,
)

print(
    f1_score(
        df[["takeprofit_hit", "stoploss_hit"]],
        df[["takeprofit_hit_pred", "stoploss_hit_pred"]],
        average=None,
    )
)


fig.show()
