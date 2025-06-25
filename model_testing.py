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


def plot(df_future, y_future_pred, med_err_test, med_err_val, symbol, y_col, range):

    fig = make_subplots(
        rows=3,
        cols=4,
        specs=[
            [{"colspan": 4}, None, None, None],
            [{"colspan": 4}, None, None, None],
            [{}, {}, {}, {}],
        ],
        shared_xaxes=True,
    )

    fig.add_trace(
        go.Candlestick(
            x=df_future["date"],
            open=df_future["open"],
            high=df_future["high"],
            low=df_future["low"],
            close=df_future["close"],
        ),
        row=1,
        col=1,
    )

    y_abs_pred = y_future_pred * df_future["close"]

    fig.add_trace(
        go.Scatter(
            x=df_future["date"] + datetime.timedelta(days=range),
            y=y_abs_pred,
            mode="lines",
            name="Prediction",
            line=dict(color="blue"),
        ),
        row=1,
        col=1,
    )

    fig.add_trace(
        go.Scatter(
            x=df_future["date"] + datetime.timedelta(days=range),
            y=y_abs_pred + (med_err_val * df_future["close"]),
            mode="lines",
            name="Prediction",
            line=dict(color="blue", dash="dot"),
        ),
        row=1,
        col=1,
    )

    fig.add_trace(
        go.Scatter(
            x=df_future["date"] + datetime.timedelta(days=range),
            y=y_abs_pred - (med_err_val * df_future["close"]),
            mode="lines",
            name="Prediction",
            line=dict(color="blue", dash="dot"),
        ),
        row=1,
        col=1,
    )

    fig.add_trace(
        go.Scatter(
            x=df_future["date"] + datetime.timedelta(days=range),
            y=y_future_pred,
            mode="lines",
            name="Prediction",
            line=dict(color="green"),
        ),
        row=2,
        col=1,
    )

    fig.add_trace(
        go.Scatter(
            x=df_future["date"] + datetime.timedelta(days=range),
            y=y_future_pred + med_err_test,
            mode="lines",
            name="Prediction+test",
            line=dict(dash="dot", color="orange"),
        ),
        row=2,
        col=1,
    )

    fig.add_trace(
        go.Scatter(
            x=df_future["date"] + datetime.timedelta(days=range),
            y=y_future_pred - med_err_test,
            mode="lines",
            name="Prediction-test",
            line=dict(dash="dot", color="orange"),
        ),
        row=2,
        col=1,
    )

    fig.add_trace(
        go.Scatter(
            x=df_future["date"] + datetime.timedelta(days=range),
            y=y_future_pred - med_err_val,
            mode="lines",
            name="Prediction-val",
            line=dict(dash="dash", color="red"),
        ),
        row=2,
        col=1,
    )

    fig.add_trace(
        go.Scatter(
            x=df_future["date"] + datetime.timedelta(days=range),
            y=y_future_pred + med_err_val,
            mode="lines",
            name="Prediction+val",
            line=dict(dash="dash", color="red"),
        ),
        row=2,
        col=1,
    )

    fig.add_trace(
        go.Scatter(
            x=df_future[y_col],
            y=df_future["OBV"],
            mode="markers",
            name=f"OBV vs {y_col}",
        ),
        row=3,
        col=1,
    )

    fig.add_trace(
        go.Scatter(
            x=df_future[y_col],
            y=df_future["change"],
            mode="markers",
            name=f"Change vs {y_col}",
        ),
        row=3,
        col=2,
    )
    fig.add_trace(
        go.Scatter(
            x=df_future[y_col],
            y=df_future["volume"],
            mode="markers",
            name=f"Volume vs {y_col}",
        ),
        row=3,
        col=3,
    )
    fig.add_trace(
        go.Scatter(
            x=df_future[y_col],
            y=df_future["SMA_200_vol_slope"],
            mode="markers",
            name=f"SMA200 vol slope vs {y_col}",
        ),
        row=3,
        col=4,
    )
    fig.update_layout(
        title_text=f"{y_col} - {symbol}",
        yaxis_autorange=True,
        yaxis_fixedrange=False,
        xaxis_rangeslider_visible=False,
    )

    return fig


def plot_importance(importance, df, y_col):
    fig = make_subplots(
        rows=3,
        cols=4,
        specs=[
            [{"colspan": 4}, None, None, None],
            [{}, {}, {}, {}],
            [{}, {}, {}, {}],
        ],
        shared_xaxes=True,
    )

    fig.add_trace(
        go.Bar(
            x=importance["feature"],
            y=importance["importance"],
            name="Importance",
        ),
        row=1,
        col=1,
    )

    importance = importance.sort_values("avg_importance", ascending=False)

    markersettings = {"size": 2, "opacity": 0.9}

    feature = importance["feature"].iloc[0]
    fig.add_trace(
        go.Scatter(
            x=df[y_col],
            y=df[feature],
            mode="markers",
            name=f"{feature} vs {y_col}",
            marker=markersettings,
        ),
        row=2,
        col=1,
    )

    feature = importance["feature"].iloc[1]
    fig.add_trace(
        go.Scatter(
            x=df[y_col],
            y=df[feature],
            mode="markers",
            name=f"{feature} vs {y_col}",
            marker=markersettings,
        ),
        row=2,
        col=2,
    )

    feature = importance["feature"].iloc[2]
    fig.add_trace(
        go.Scatter(
            x=df[y_col],
            y=df[feature],
            mode="markers",
            name=f"{feature} vol vs {y_col}",
            marker=markersettings,
        ),
        row=2,
        col=3,
    )

    feature = importance["feature"].iloc[3]
    fig.add_trace(
        go.Scatter(
            x=df[y_col],
            y=df[feature],
            mode="markers",
            name=f"{feature} vs {y_col}",
            marker=markersettings,
        ),
        row=2,
        col=4,
    )

    feature = importance["feature"].iloc[4]
    fig.add_trace(
        go.Scatter(
            x=df[y_col],
            y=df[feature],
            mode="markers",
            name=f"{feature} vs {y_col}",
            marker=markersettings,
        ),
        row=3,
        col=1,
    )

    feature = importance["feature"].iloc[5]
    fig.add_trace(
        go.Scatter(
            x=df[y_col],
            y=df[feature],
            mode="markers",
            name=f"{feature} vs {y_col}",
            marker=markersettings,
        ),
        row=3,
        col=2,
    )

    feature = importance["feature"].iloc[6]
    fig.add_trace(
        go.Scatter(
            x=df[y_col],
            y=df[feature],
            mode="markers",
            name=f"{feature} vs {y_col}",
            marker=markersettings,
        ),
        row=3,
        col=3,
    )

    feature = importance["feature"].iloc[7]
    fig.add_trace(
        go.Scatter(
            x=df[y_col],
            y=df[feature],
            mode="markers",
            name=f"{feature} vs {y_col}",
            marker=markersettings,
        ),
        row=3,
        col=4,
    )

    fig.update_layout(
        title_text="Feature importance",
        yaxis_autorange=True,
        yaxis_fixedrange=False,
        xaxis_rangeslider_visible=False,
    )

    return fig


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

df_sp500 = m.dataconstruct(
    "^SPX", datetime.datetime(2021, 1, 1), datetime.datetime(2024, 10, 6)
)

# add prefix to all columns
df_sp500.columns = [f"SP500_{col}" for col in df_sp500.columns]

df_sp500 = df_sp500.drop(
    columns=[
        "SP500_exit",
        "SP500_entry",
        "SP500_M1; Not seasonally adjusted",
        "SP500_M2; Not seasonally adjusted",
        "SP500_label",
        "SP500_direction",
    ]
)

for symbol in symbols:
    df = m.dataconstruct(
        symbol, datetime.datetime(2021, 1, 1), datetime.datetime(2024, 10, 6)
    )

    df = df.merge(df_sp500, left_on="date", right_on="SP500_date")

    df_dropped = df.dropna()

    # drop all x values that are in the future
    drop_cols = df_dropped.columns[df_dropped.columns.str.contains("FUTURE")].tolist()

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
            "SP500_date",
        ]
    )

    drop_cols.extend(
        [
            "LOW_100",
            "HIGH_100",
            "LOW_200",
            "LOW_21",
            "eps_pct_change_annual",
            "revenue_pct_change_annual",
            "eps_sma_slope",
            "revenue_sma_slope",
            "revenue_pct_change",
            "unadjustedVolume",
            "epsEstimated",
            "eps_pct_change",
            "eps_sma_slope_above",
            "eps_sma_gap_above",
            "revenueEstimated",
            "eps_sma_gap",
            "eps_sma",
            "eps_sma_gap_below",
            "revenue_sma",
            "HIGH_200",
            "SMA_21_OBV_direction",
            "eps_sma_direction",
            "eps_sma_slope_below",
            "open",
            "close",
            "high",
            "low",
            "adjClose",
            "vwap",
            "LOW_50",
            "SP500_LOW_200",
            "SP500_LOW_50",
            "SP500_LOW_21",
            "eps",
            "revenue",
            "SP500_LOW_100",
            "SP500_HIGH_100",
            "beat_estimate",
        ]
    )

    cutoff = datetime.datetime(2023, 12, 1)

    df_validation = df_dropped[df_dropped["date"] > cutoff].copy()
    df_dropped = df_dropped[df_dropped["date"] < cutoff]

    range = 21
    y_col = f"FUTURE_HIGH_{range}_change"
    x_cols = [col for col in df_dropped.columns if col not in drop_cols]

    y = df_dropped[y_col]
    y_validation = df_validation[y_col]

    # saving df
    df_temp = df[x_cols + [y_col]].copy()

    df_temp[x_cols] = scaler.fit_transform(df_temp[x_cols])
    df_collection.append(df_temp)

    X = scaler.fit_transform(df_dropped[x_cols])
    X_validation = scaler.transform(df_validation[x_cols])

    X_train, X_test, y_train, y_test = train_test_split(X, y, random_state=1)

    # finding best params
    if optimize:
        grid = GridSearchCV(
            xgb.XGBRegressor(),
            param_grid,
            n_jobs=1,
            cv=3,
            scoring="r2",
            verbose=1,
            refit=True,
        )

        grid.fit(X_train, y_train)

        # Print the best set of hyperparameters and the corresponding score
        print("Best set of hyperparameters: ", grid.best_params_)
        print("Best score: ", grid.best_score_)

        params.update(grid.best_params_)

    dtrain_reg = xgb.DMatrix(X_train, y_train, enable_categorical=True)
    dtest_reg = xgb.DMatrix(X_test, y_test, enable_categorical=True)
    dval_reg = xgb.DMatrix(X_validation, enable_categorical=True)

    n = 1000
    model = xgb.train(
        params=params,
        dtrain=dtrain_reg,
        num_boost_round=n,
    )

    print("Model trained")

    print("Model feature importance: ")

    count = 0
    for i in x_cols:
        try:
            if i not in importance:
                importance[i] = [model.get_score(importance_type="weight")[f"f{count}"]]
            else:
                importance[i].append(
                    model.get_score(importance_type="weight")[f"f{count}"]
                )
        except:
            pass
        count += 1

    # produce predictions for the future
    y_test_pred = model.predict(dtest_reg)
    y_val_pred = model.predict(dval_reg)

    print("Validation error: ", ((y_validation - y_val_pred) ** 2).mean())
    print("Test error: ", ((y_test - y_test_pred) ** 2).mean())

    med_err_val = (y_validation - y_val_pred).abs().median()
    med_err_test = (y_test - y_test_pred).abs().median()

    print("Median error val: ", med_err_val)
    print("Median error test: ", med_err_test)

    df_future = df.tail(90).copy()
    X_future = scaler.transform(df_future[x_cols])
    dfuture_reg = xgb.DMatrix(X_future, enable_categorical=True)

    y_future_pred = model.predict(dfuture_reg)

    if plot_graph:
        fig = plot(
            df_future,
            y_future_pred,
            med_err_test,
            med_err_val,
            symbol,
            y_col,
            range,
        )

        fig.show()


ls_importance = []
for i in importance.keys():
    ls_importance.append(
        [
            i,
            sum(importance[i]),
            len(importance[i]),
            sum(importance[i]) / len(importance[i]),
        ]
    )


importance = pd.DataFrame(
    ls_importance, columns=["feature", "importance", "count", "avg_importance"]
)
importance = importance.sort_values("avg_importance", ascending=False)

df = pd.concat(df_collection, axis=0)

fig = plot_importance(importance, df, y_col)

print(importance)

df.to_csv("./output/stock_data_scaled.csv", index=False)

fig.show()
