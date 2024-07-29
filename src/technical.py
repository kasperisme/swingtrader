import pandas as pd
import numpy as np
from scipy.signal import argrelextrema
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import os
from src.fmp import fmp


class technical:
    def __init__(self):
        self.APIKEY: str = os.environ["APIKEY"]
        self.VWAP_PERIOD = 60

        self.data: pd.DataFrame = None
        self.trend_template_dict = None
        self.fmp = fmp()
        self.df_rs = None

    def get_sp500_tickers(self):
        return self.fmp.sp500tickers()

    def get_exhange_tickers(self, exchange: str):
        return self.fmp.exchange_tickers(exchange)

    def get_quote_prices(self, tickers: list):

        df = self.fmp.quote_price(tickers)

        df["PRICE_OVER_SMA200"] = (df["price"] > df["priceAvg200"]).astype(int)
        df["SMA50_OVER_SMA200"] = (df["priceAvg50"] > df["priceAvg200"]).astype(int)
        df["PRICE_25PCT_OVER_LOW"] = (df["price"] > df["yearLow"] * 1.25).astype(int)
        df["PRICE_25PCT_WITHIN_HIGH"] = (
            (df["price"] > df["yearHigh"] * 0.75) & (df["price"] < df["yearHigh"])
        ).astype(int)

        cols = [
            "PRICE_OVER_SMA200",
            "SMA50_OVER_SMA200",
            "PRICE_25PCT_OVER_LOW",
            "PRICE_25PCT_WITHIN_HIGH",
        ]

        df["SCREENER"] = (df[cols].sum(axis=1) == len(cols)).astype(int)

        return df

    def get_change_prices(self, tickers: list):
        self.df_rs = self.fmp.change_price(tickers)

        cols = [
            {"period": "3M", "weight": 2},
            {"period": "6M", "weight": 1},
            {"period": "1Y", "weight": 1},
        ]

        self.df_rs["Weighted_score"] = 0
        for col in cols:
            period = col["period"]
            self.df_rs[f"{period}_RANK"] = self.df_rs[f"{period}"].rank(ascending=True)
            self.df_rs["Weighted_score"] += self.df_rs[f"{period}_RANK"] * col["weight"]

        maxscore = len(self.df_rs["symbol"]) * sum([i["weight"] for i in cols])

        self.df_rs["RS"] = (self.df_rs["Weighted_score"] / maxscore) * 100

        return self.df_rs

    def minervini_trend_template(
        self,
        ticker,
        today,
    ):

        latest_trading_day = self.data["date"].iloc[-1]

        mask_remove_latest = self.data["date"] != latest_trading_day

        mask_rs = self.df_rs["symbol"] == ticker

        self.trend_template_dict = {
            "ticker": ticker,
            "date": today,
            "PriceOverSMA150And200": self.data["close"].iloc[-1]
            > self.data["SMA200"].iloc[-1]
            and self.data["close"].iloc[-1] > self.data["SMA150"].iloc[-1],
            "SMA150AboveSMA200": self.data["SMA150"].iloc[-1]
            > self.data["SMA200"].iloc[-1],
            "SMA50AboveSMA150And200": self.data["SMA50"].iloc[-1]
            > self.data["SMA200"].iloc[-1]
            and self.data["SMA50"].iloc[-1] > self.data["SMA150"].iloc[-1],
            "SMA200Slope": self.data["SMA200_slope_direction"].tail(20).sum() == 20,
            "PriceAbove25Percent52WeekLow": min(self.data[mask_remove_latest]["low"])
            * 1.25
            <= self.data["close"].iloc[-1],
            "PriceWithin25Percent52WeekHigh": max(
                self.data[mask_remove_latest]["close"]
            )
            * 0.75
            <= self.data["close"].iloc[-1]
            and max(self.data[mask_remove_latest]["close"])
            >= self.data["close"].iloc[-1],
            "RSOver70": self.df_rs[mask_rs]["RS"].iloc[0] > 70,
        }

        self.trend_template_dict["Passed"] = (
            self.trend_template_dict["PriceOverSMA150And200"]
            and self.trend_template_dict["SMA150AboveSMA200"]
            and self.trend_template_dict["SMA50AboveSMA150And200"]
            and self.trend_template_dict["SMA200Slope"]
            and self.trend_template_dict["PriceAbove25Percent52WeekLow"]
            and self.trend_template_dict["PriceWithin25Percent52WeekHigh"]
            and self.trend_template_dict["RSOver70"]
        )
        return self.trend_template_dict

    def get_daily_chart(
        self, ticker, startdate="2024-01-01", enddate="2024-07-11", shares_outstanding=1
    ):
        chart = self.fmp.daily_chart(ticker, startdate, enddate)
        ####______________________SMA200______________________####
        sma200 = self.fmp.sma(ticker, 200, startdate, enddate)

        chart = chart.merge(sma200, on="date", how="left")

        ####______________________SMA150______________________####
        sma50 = self.fmp.sma(ticker, 150, startdate, enddate)

        chart = chart.merge(sma50, on="date", how="left")

        ####______________________SMA50______________________####
        sma50 = self.fmp.sma(ticker, 50, startdate, enddate)

        chart = chart.merge(sma50, on="date", how="left")

        ####______________________RSI(63)______________________####
        rsi = self.fmp.rsi(ticker, 63, startdate, enddate)

        chart = chart.merge(rsi, on="date", how="left")

        ####_SLOPE_####
        chart["SMA200_slope"] = chart["SMA200"].diff()
        chart["SMA200_slope_direction"] = (chart["SMA200_slope"] > 0).astype(int)

        ##_____________VOLUME TURNOVER %_____________##
        chart["relative_volume"] = chart["volume"].astype(int) / shares_outstanding

        ##_____________VWAP______________##
        chart["price"] = (chart["close"] + chart["high"] + chart["low"]) / 3
        chart["product_volume_price"] = chart["volume"] * chart["price"]

        chart["product_volume_price_rolling"] = (
            chart["product_volume_price"].rolling(window=self.VWAP_PERIOD).sum()
        )
        chart["volume_rolling"] = chart["volume"].rolling(window=self.VWAP_PERIOD).sum()

        chart["vwap"] = chart["product_volume_price_rolling"] / chart["volume_rolling"]
        ### clean up
        chart = chart.sort_values(by="date")

        return chart

    def getextremes(self, data, order):
        localmin = argrelextrema(data["low"].values, np.less, order=order)[0]
        localmax = argrelextrema(data["high"].values, np.greater, order=order)[0]

        dir_localmin = [{"type": "low", "index": i} for i in localmin.tolist()]
        dir_localmax = [{"type": "high", "index": i} for i in localmax.tolist()]

        extremes = dir_localmin + dir_localmax

        sorted_extremes = sorted(extremes, key=lambda x: x["index"])

        return localmin, localmax, sorted_extremes

    def create_candlestick_graph(self, data):
        template = "plotly_dark"
        fig = make_subplots(
            rows=3,
            cols=1,
            shared_xaxes=True,
            vertical_spacing=0.03,
            subplot_titles=("OHLC", "Volume"),
            row_width=[0.15, 0.15, 0.7],
        )

        fig.update_layout(template=template)

        fig.add_trace(
            go.Candlestick(
                x=data["date"],
                open=data["open"],
                high=data["high"],
                low=data["low"],
                close=data["close"],
            ),
            row=1,
            col=1,
        )

        fig.add_trace(
            go.Scatter(
                x=data["date"],
                y=data["SMA200"],
                mode="lines",
                line=dict(color="brown", width=1),
                name="SMA200",
            ),
            row=1,
            col=1,
        )

        fig.add_trace(
            go.Scatter(
                x=data["date"],
                y=data["SMA150"],
                mode="lines",
                line=dict(color="orange", width=1),
                name="SMA150",
            ),
            row=1,
            col=1,
        )
        fig.add_trace(
            go.Scatter(
                x=data["date"],
                y=data["SMA50"],
                mode="lines",
                line=dict(color="yellow", width=1),
                name="SMA50",
            ),
            row=1,
            col=1,
        )

        fig.add_trace(
            go.Scatter(
                x=data["date"],
                y=data["vwap"],
                mode="lines",
                line=dict(color="blue", width=1),
                name=f"VWAP({self.VWAP_PERIOD})",
            ),
            row=1,
            col=1,
        )

        fig.add_trace(
            go.Bar(
                x=data["date"],
                y=data["relative_volume"],
                showlegend=False,
            ),
            row=2,
            col=1,
        )

        fig.add_trace(
            go.Scatter(
                x=data["date"],
                y=data["RSI63"],
                mode="lines",
                showlegend=False,
            ),
            row=3,
            col=1,
        )

        fig.add_hline(70, row=3, col=1)

        fig.update_layout(
            xaxis_rangeslider_visible=False, yaxis2={"tickformat": ",.2%"}
        )

        dt_all = pd.date_range(
            start=data["date"].iloc[0], end=data["date"].iloc[-1], freq="1D"
        )

        # check which dates from your source that also accur in the continuous date range
        dt_obs = [d.strftime("%Y-%m-%d %H:%M:%S") for d in data["date"]]

        # isolate missing timestamps
        dt_breaks = [
            d for d in dt_all.strftime("%Y-%m-%d %H:%M:%S").tolist() if not d in dt_obs
        ]

        # adjust xaxis for rangebreaks
        fig.update_xaxes(
            rangebreaks=[dict(dvalue=24 * 60 * 60 * 1000, values=dt_breaks)]
        )

        return fig

    def add_price_target(self, fig, data, price_target):
        if len(price_target) == 0:
            return fig
        fig.add_trace(
            go.Scatter(
                x=[
                    data["date"].iloc[-1],
                    data["date"].iloc[-1] + pd.Timedelta(days=10),
                    data["date"].iloc[-1] + pd.Timedelta(days=10),
                    data["date"].iloc[-1],
                    data["date"].iloc[-1],
                ],
                y=[
                    data["close"].iloc[-1],
                    data["close"].iloc[-1],
                    price_target[0]["targetConsensus"],
                    price_target[0]["targetConsensus"],
                    data["close"].iloc[-1],
                ],
                fill="toself",
            )
        )

        return fig

    def add_circles(self, fig, data, indexes, yparam="high", color="green"):

        last_record = 0 if yparam == "low" else 999999999999
        for index in indexes:
            fig.add_trace(
                go.Scatter(
                    x=[data["date"][index]],
                    y=[data[yparam][index]],
                    mode="markers",
                    marker=dict(color=color, size=10, symbol="circle"),
                    showlegend=False,
                )
            )

            if (
                yparam == "high"
                and data[yparam][index] > last_record
                or yparam == "low"
                and data[yparam][index] < last_record
            ):
                fig.add_trace(
                    go.Scatter(
                        x=[data["date"][index]],
                        y=[data[yparam][index]],
                        mode="markers",
                        marker=dict(
                            color=color,
                            size=13,
                            symbol="circle",
                            opacity=0.5,
                            line=dict(color="Black", width=2),
                        ),
                        showlegend=False,
                    )
                )

            last_record = data[yparam][index]

        return fig

    def draw_extreme_lines(self, fig, data, extremes):
        for index in range(len(extremes) - 1):
            current = extremes[index]
            next = extremes[index + 1]

            fig.add_shape(
                dict(
                    type="line",
                    x0=data["date"][current["index"]],
                    y0=data[current["type"]][current["index"]],
                    x1=data["date"][next["index"]],
                    y1=data[next["type"]][next["index"]],
                    line=dict(width=1),
                )
            )

        # draw line to last record
        fig.add_shape(
            dict(
                type="line",
                x0=data["date"][extremes[-1]["index"]],
                y0=data[extremes[-1]["type"]][extremes[-1]["index"]],
                x1=data["date"].iloc[-1],
                y1=data["close"].iloc[-1],
                line=dict(width=1),
            )
        )
        return fig

    def draw_support_lines(self, fig, data, localmax, localmin, maxage=180):
        # draw support lines for highs
        skiplist = []

        for i in range(len(localmax)):
            linedrawn = False
            lowerfound = False

            if i not in skiplist:
                for j in range(i + 1, len(localmax)):
                    if data["high"][localmax[i]] > data["high"][localmax[j]] and data[
                        "date"
                    ][localmax[j]] - data["date"][localmax[i]] < pd.Timedelta(
                        days=maxage
                    ):
                        lowerfound = True
                        skiplist.append(j)
                    else:
                        if not linedrawn:
                            fig.add_shape(
                                type="line",
                                x0=data["date"][localmax[i]],
                                y0=data["high"][localmax[i]],
                                x1=data["date"][localmax[j]],
                                y1=data["high"][localmax[i]],
                                line=dict(color="green", width=1),
                            )
                            linedrawn = True

                if not linedrawn and lowerfound:
                    fig.add_shape(
                        type="line",
                        x0=data["date"][localmax[i]],
                        y0=data["high"][localmax[i]],
                        x1=max(data["date"]),
                        y1=data["high"][localmax[i]],
                        line=dict(color="green", width=1),
                    )

        # draw support lines for lows
        skiplist = []
        for i in range(len(localmin)):
            linedrawn = False
            higherfound = False
            if i not in skiplist:
                for j in range(i + 1, len(localmin)):
                    if data["low"][localmin[i]] < data["low"][localmin[j]] and data[
                        "date"
                    ][localmin[j]] - data["date"][localmin[i]] < pd.Timedelta(
                        days=maxage
                    ):
                        higherfound = True
                        skiplist.append(j)
                    else:
                        if not linedrawn:
                            fig.add_shape(
                                type="line",
                                x0=data["date"][localmin[i]],
                                y0=data["low"][localmin[i]],
                                x1=data["date"][localmin[j]],
                                y1=data["low"][localmin[i]],
                                line=dict(color="red", width=1),
                            )
                            linedrawn = True

                if not linedrawn and higherfound:
                    fig.add_shape(
                        type="line",
                        x0=data["date"][localmin[i]],
                        y0=data["low"][localmin[i]],
                        x1=data["date"][localmin[j]],
                        y1=data["low"][localmin[i]],
                        line=dict(color="red", width=1),
                    )

        return fig

    def get_complete_graph(self, ticker, startdate, enddate, shares_outstanding=1):
        self.data = self.get_daily_chart(
            ticker,
            startdate=startdate,
            enddate=enddate,
            shares_outstanding=shares_outstanding,
        )

        localmin, localmax, sorted_extremes = self.getextremes(self.data, 10)

        self.fig = self.create_candlestick_graph(self.data)

        self.fig = self.add_circles(
            self.fig, self.data, localmin, yparam="low", color="red"
        )
        self.fig = self.add_circles(
            self.fig, self.data, localmax, yparam="high", color="green"
        )
        self.fig = self.draw_extreme_lines(self.fig, self.data, sorted_extremes)
        self.fig = self.draw_support_lines(self.fig, self.data, localmax, localmin)

        self.minervini_trend_template(ticker, enddate)

        return self.fig

    def get_screening(self, ticker, startdate, enddate):

        self.data = self.get_daily_chart(ticker, startdate=startdate, enddate=enddate)

        self.minervini_trend_template(ticker, enddate)

        return self.data, self.trend_template_dict
