import pandas as pd
import numpy as np
import requests as r
from scipy.signal import argrelextrema
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from src.config import config
import os

class helper:
    def __init__(self):
        self.APIKEY: str = os.environ["APIKEY"]
        self.data: pd.DataFrame = None

    def get_tickers(self):
        url = self.add_query_token(
            "https://financialmodelingprep.com/api/v3/sp500_constituent"
        )

        response = r.get(url)

        if response.status_code != 200:
            raise Exception("API response on tickers: " + str(response.status_code))

        data = response.json()

        tickers = pd.DataFrame(data)

        return tickers

    def add_query_token(self, url):
        if "?" in url:
            return url + "&apikey=" + self.APIKEY
        else:
            return url + "?apikey=" + self.APIKEY

    def add_smadata(self, ticker, startdate, enddate, period):
        url = self.add_query_token(
            f"https://financialmodelingprep.com/api/v3/technical_indicator/1day/{ticker}?type=sma&period={period}&from={startdate}&to={enddate}",
        )

        response = r.get(url)

        if response.status_code != 200:
            raise Exception("API response on SMA200: " + str(response.status_code))

        data = response.json()

        sma = pd.DataFrame(data)

        sma["date"] = pd.to_datetime(sma["date"])

        colname = "SMA{}".format(period)
        sma = sma.rename(columns={"sma": colname})
        sma = sma[["date", colname]]

        return sma

    def get_daily_chart(self, ticker, startdate="2024-01-01", enddate="2024-07-11"):
        url = self.add_query_token(
            f"https://financialmodelingprep.com/api/v3/historical-price-full/{ticker}?from={startdate}&to={enddate}",
        )
        response = r.get(url)

        if response.status_code != 200:
            raise Exception("API response on chart: " + str(response.status_code))

        data = response.json()

        chart = pd.DataFrame(data["historical"])
        chart["date"] = pd.to_datetime(chart["date"])
        chart = chart.sort_values(by="date", ascending=True).reset_index(drop=True)
        ####______________________SMA200______________________####
        sma200 = self.add_smadata(ticker, startdate, enddate, 200)

        chart = chart.merge(sma200, on="date", how="left")

        ####______________________SMA150______________________####
        sma50 = self.add_smadata(ticker, startdate, enddate, 150)

        chart = chart.merge(sma50, on="date", how="left")

        ####______________________SMA50______________________####
        sma50 = self.add_smadata(ticker, startdate, enddate, 50)

        chart = chart.merge(sma50, on="date", how="left")

        ####_SLOPE_####
        chart["SMA200_slope"] = chart["SMA200"].diff()
        chart["SMA200_slope_direction"] = (chart["SMA200_slope"] > 0).astype(int)

        ########

        url = self.add_query_token(
            f"https://financialmodelingprep.com/api/v4/price-target-consensus?symbol={ticker}",
        )

        response = r.get(url)

        if response.status_code != 200:
            raise Exception("API response on pricetarget: " + str(response.status_code))

        price_target = response.json()

        ### clean up
        chart = chart.sort_values(by="date")

        return chart, price_target

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
            rows=2,
            cols=1,
            shared_xaxes=True,
            vertical_spacing=0.03,
            subplot_titles=("OHLC", "Volume"),
            row_width=[0.2, 0.7],
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
            go.Bar(x=data["date"], y=data["volume"], showlegend=False), row=2, col=1
        )

        fig.update_layout(xaxis_rangeslider_visible=False)

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

    def get_complete_graph(self, ticker, startdate, enddate):
        self.data, price_target = self.get_daily_chart(
            ticker, startdate=startdate, enddate=enddate
        )

        localmin, localmax, sorted_extremes = self.getextremes(self.data, 10)

        self.fig = self.create_candlestick_graph(self.data)
        self.fig = self.add_price_target(self.fig, self.data, price_target)
        self.fig = self.add_circles(
            self.fig, self.data, localmin, yparam="low", color="red"
        )
        self.fig = self.add_circles(
            self.fig, self.data, localmax, yparam="high", color="green"
        )
        self.fig = self.draw_extreme_lines(self.fig, self.data, sorted_extremes)
        self.fig = self.draw_support_lines(self.fig, self.data, localmax, localmin)

        return self.fig
