from src import technical, logging, fundamentals, fmp
from datetime import datetime, timedelta
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from typing import Callable


class models:
    def __init__(self) -> None:
        self.fmp = fmp.fmp()
        self.fund = fundamentals.Fundamentals()
        self.tech = technical.technical()
        self.logger = logging.logger

        self.strf = "%Y-%m-%d"

    def __OBV(self, df: pd.DataFrame) -> pd.Series:
        df["OBV_temp"] = df["volume"] * (
            (df["close"] - df["close"].shift(1) > 0).astype(int) * 2 - 1
        )
        df["OBV_temp"] = df["OBV_temp"].fillna(0)
        df.loc[0, "OBV_temp"] = 0
        df["OBV"] = df["OBV_temp"].cumsum().copy()

        return df["OBV"]

    def __moving_values(self, df: pd.DataFrame, periods: list[int]) -> pd.DataFrame:
        for sma in periods:
            df[f"SMA_{sma}"] = df["close"].rolling(window=sma).mean()
            df[f"SMA_{sma}_slope"] = df[f"SMA_{sma}"].diff()
            df[f"SMA_{sma}_direction"] = (df[f"SMA_{sma}_slope"] > 0).astype(int)

            df[f"SMA_{sma}_vol"] = df["volume"].rolling(window=sma).mean()
            df[f"SMA_{sma}_vol_slope"] = df[f"SMA_{sma}_vol"].diff()
            df[f"SMA_{sma}_vol_direction"] = (df[f"SMA_{sma}_vol_slope"] > 0).astype(
                int
            )

            df[f"SMA_{sma}_OBV"] = df["OBV"].rolling(window=sma).mean()
            df[f"SMA_{sma}_OBV_slope"] = df[f"SMA_{sma}_OBV"].diff()
            df[f"SMA_{sma}_OBV_direction"] = (df[f"SMA_{sma}_OBV_slope"] > 0).astype(
                int
            )

            df[f"HIGH_{sma}"] = df["high"].rolling(window=sma).max()
            df[f"LOW_{sma}"] = df["low"].rolling(window=sma).min()

            # measure volatility
            df[f"VOLATILITY_{sma}"] = (df[f"HIGH_{sma}"] - df[f"LOW_{sma}"]) / df[
                f"SMA_{sma}"
            ]

            #### THESE VALUES ARE NOT USED IN THE STRATEGY
            df[f"FUTURE_HIGH_{sma}"] = df["high"].shift(-sma)
            df[f"FUTURE_LOW_{sma}"] = df["low"].shift(-sma)

            df[f"FUTURE_HIGH_{sma}_change"] = df[f"FUTURE_HIGH_{sma}"] / df["close"]

            df[f"FUTURE_LOW_{sma}_change"] = df[f"FUTURE_LOW_{sma}"] / df["close"]

        return df

    def __direction(self, df: pd.DataFrame) -> pd.Series:

        mask = df["close"] > df["open"]
        df.loc[mask, "direction"] = "Green"
        df.loc[~mask, "direction"] = "Red"

        return df["direction"]

    def dataconstruct(
        self, symbol: str, startdate: datetime.date, enddate: datetime.date
    ) -> pd.DataFrame:
        assert startdate < enddate, "Start date must be before end date"

        df_chart = self.fmp.daily_chart(
            symbol,
            startdate=startdate.strftime(self.strf),
            enddate=enddate.strftime(self.strf),
        )

        df_intraday_chart = self.fmp.intraday_chart(
            "1hour",
            symbol,
            startdate=startdate.strftime(self.strf),
            enddate=enddate.strftime(self.strf),
        )

        # calculate the OBV
        df_chart["OBV"] = self.__OBV(df_chart)
        df_intraday_chart["OBV"] = self.__OBV(df_intraday_chart)

        # direction, only used for coloring the chart
        df_chart["direction"] = self.__direction(df_chart)
        df_intraday_chart["direction"] = self.__direction(df_intraday_chart)

        # calculate the EPS slope
        SMA = [10, 21, 50, 100, 200]
        df_chart = self.__moving_values(df_chart, SMA)
        df_intraday_chart = self.__moving_values(df_intraday_chart, SMA)

        try:
            df_fund = self.fund.get_earnings_data(symbol)

            df_chart = df_chart.merge(
                df_fund,
                left_on="date",
                right_on="date",
                how="left",
            )

            df_chart[df_fund.columns] = df_chart[df_fund.columns].ffill()
        except Exception as e:
            self.logger.error("Failed to fetch earnings", e)

        try:
            df_money = self.load_moneysupply()

            df_money = df_money[
                ["date", "M1; Not seasonally adjusted", "M2; Not seasonally adjusted"]
            ]

            df_money = df_money.ffill()

            df_chart = df_chart.merge(
                df_money, left_on="date", right_on="date", how="left"
            )

            df_chart[df_money.columns] = df_chart[df_money.columns].ffill()

        except Exception as e:
            self.logger.error("Failed to fetch money supply", e)

        # previous high within 5
        df_chart["entry"] = 0
        df_chart["exit"] = 0

        return df_chart, df_intraday_chart

    def load_moneysupply(self, filepath: str = "./input/FRB_H6.csv") -> pd.DataFrame:

        df = pd.read_csv(filepath)

        df = df.drop(index=[0, 1, 2, 3, 4])

        df = df.rename(columns={"Series Description": "date"})

        df["date"] = pd.to_datetime(df["date"])

        return df

    def strategy_EPS_SMA(self, df: pd.DataFrame, state: int) -> pd.DataFrame:
        if state == 0 and df["eps_sma_slope"] > 0 and df["close"] > df["SMA_100"]:
            return 1
        elif state == 1 and (df["eps_sma_slope"] < 0 or df["close"] < df["SMA_100"]):
            return -1

    def strategy_VPC_SMA(self, df: pd.DataFrame, state: int) -> pd.DataFrame:
        if (
            state == 0
            and df["LOW_10"] >= df["LOW_21"]
            and df["LOW_21"] >= df["LOW_50"]
            and df["LOW_50"] >= df["LOW_100"]
            and df["eps_sma_gap"] > 0
        ):
            return 1
        elif state == 1 and df["close"] < df["SMA_50"]:
            return -1

    def apply_strategy(
        self, df: pd.DataFrame, strategy: Callable[[pd.Series, int], int]
    ) -> pd.DataFrame:

        # 1: in market, 0: not in market
        state = 0
        entryprice = 0

        trades = []
        for index, row in df.iterrows():
            action = strategy(row, state)

            if strategy(row, state) == 1:
                # Entry signal
                df.loc[index, "entry"] = 1
                entryprice = row["close"]
                entrydate = row["date"]
                state = 1
            elif strategy(row, state) == -1:
                # Exit signal
                df.loc[index, "exit"] = 1
                df.loc[index, "pnl"] = row["close"] - entryprice

                trades.append(
                    {
                        "entrydate": entrydate,
                        "exitdate": row["date"],
                        "entryprice": entryprice,
                        "exitprice": row["close"],
                        "pnl": row["close"] - entryprice,
                        "direction": "Long",
                        "symbol": row["symbol"],
                        "pnl%": (row["close"] - entryprice) / entryprice,
                    }
                )
                state = 0
        if state == 1:
            df.loc[index, "exit"] = 1
            df.loc[index, "pnl"] = row["close"] - entryprice

            trades.append(
                {
                    "entrydate": entrydate,
                    "exitdate": row["date"],
                    "entryprice": entryprice,
                    "exitprice": row["close"],
                    "pnl": row["close"] - entryprice,
                    "direction": "Long",
                    "symbol": row["symbol"],
                    "pnl%": (row["close"] - entryprice) / entryprice,
                }
            )

        return df, trades

    def get_graph(self, df):

        template = "plotly_dark"
        fig = make_subplots(
            rows=3,
            cols=1,
            shared_xaxes=True,
            vertical_spacing=0.03,
            subplot_titles=("OHLC", "Volume", "EPS slope"),
            row_width=[0.1, 0.1, 0.5],
        )

        fig.update_layout(
            template=template,
            yaxis_autorange=True,
            yaxis_fixedrange=False,
            xaxis_rangeslider_visible=False,
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

        fig.add_trace(
            go.Scatter(
                x=df["date"],
                y=df["eps_sma_slope_above"],
                name="eps_slope",
                fill="tozeroy",
                mode="none",
                fillcolor="green",
            ),
            row=2,
            col=1,
        )

        fig.add_trace(
            go.Scatter(
                x=df["date"],
                y=df["eps_sma_slope_below"],
                name="eps_slope",
                fill="tozeroy",
                mode="none",
                fillcolor="red",
            ),
            row=2,
            col=1,
        )

        fig.add_trace(
            go.Scatter(
                x=df["date"],
                y=df["eps_sma_gap_above"],
                name="eps_gap",
                fill="tozeroy",
                mode="none",
                fillcolor="green",
            ),
            row=3,
            col=1,
        )

        fig.add_trace(
            go.Scatter(
                x=df["date"],
                y=df["eps_sma_gap_below"],
                name="eps_gap",
                fill="tozeroy",
                mode="none",
                fillcolor="red",
            ),
            row=3,
            col=1,
        )

        SMA = [21, 50, 100, 200]
        for sma in SMA:
            fig.add_trace(
                go.Scatter(
                    x=df["date"], y=df[f"SMA_{sma}"], mode="lines", name=f"SMA_{sma}"
                ),
                row=1,
                col=1,
            )

        entries = df[df["entry"] == 1].to_dict("records")

        for entry in entries:
            fig.add_trace(
                go.Scatter(
                    x=[entry["date"]],
                    y=[df[df["date"] == entry["date"]]["close"].values[0]],
                    mode="markers",
                    marker=dict(color="blue", size=10),
                    showlegend=False,
                ),
                row=1,
                col=1,
            )

        exits = df[df["exit"] == 1].to_dict("records")
        for exit in exits:
            fig.add_trace(
                go.Scatter(
                    x=[exit["date"]],
                    y=[df[df["date"] == exit["date"]]["close"].values[0]],
                    mode="markers",
                    marker=dict(color="white", size=10),
                    showlegend=False,
                ),
                row=1,
                col=1,
            )

        return fig


if __name__ == "__main__":
    model = models()
    model.dataconstruct("AAPL", datetime(2021, 1, 1), datetime(2021, 12, 31))
