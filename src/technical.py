import pandas as pd
import numpy as np
from scipy.signal import argrelextrema
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import os
from datetime import datetime, timedelta
from src.fmp import fmp

from src.logging import logger


class technical:
    def __init__(self):
        self.APIKEY: str = os.environ["APIKEY"]
        self.VWAP_PERIOD = 60

        self.data: pd.DataFrame = None
        self.trend_template_dict = None
        self.fmp = fmp()
        self.df_rs = None
        self.spx_df: pd.DataFrame = None  # populated by get_market_direction()

    def get_sp500_tickers(self):
        return self.fmp.sp500tickers()

    def get_indices_tickers(self):
        return self.fmp.indices_tickers()

    def get_exhange_tickers(self, exchange: str):
        return self.fmp.exchange_tickers(exchange)

    def get_quote_prices(self, tickers: list):

        cutoff = 400
        if len(tickers) < cutoff:
            df = self.fmp.quote_price(tickers)
        else:
            logger.info("Getting quotes in chunks")
            col = []
            for i in range(0, len(tickers), cutoff):

                df = self.fmp.quote_price(tickers[i : i + cutoff])
                col.append(df)

            df = pd.concat(col, axis=0)

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
            "PriceWithin25Percent52WeekHigh": max(self.data[mask_remove_latest]["high"])
            * 0.75
            <= self.data["close"].iloc[-1]
            and max(self.data[mask_remove_latest]["high"])
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
        )
        return self.trend_template_dict

    def get_daily_chart(
        self,
        ticker,
        startdate="2024-01-01",
        enddate="2024-07-11",
        shares_outstanding=1,
    ):
        chart = self.fmp.daily_chart(ticker, startdate, enddate)

        # SMAs computed locally — replaces 3 separate API calls per ticker
        chart["SMA200"] = chart["close"].rolling(window=200).mean()
        chart["SMA150"] = chart["close"].rolling(window=150).mean()
        chart["SMA50"] = chart["close"].rolling(window=50).mean()

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

    def get_complete_graph(
        self,
        ticker,
        startdate,
        enddate,
        shares_outstanding=1,
        include_trend_template=True,
    ):
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

        if include_trend_template:
            self.minervini_trend_template(ticker, enddate)

        return self.fig

    def get_market_direction(self, lookback_days=365):
        """
        Assesses overall market condition using the S&P 500 (^SPX).

        Combines:
        - SMA alignment (21 > 50 > 150 > 200) — Minervini / O'Neil market filter
        - Distribution day count in last 25 sessions — O'Neil (≥5 = danger)
        - OBV trend vs its 21-day SMA — from index_trend.py logic

        Also populates self.spx_df so RS-line calculations can reuse the data.

        Returns dict:
            condition            : "uptrend" | "uptrend_under_pressure" |
                                   "correction" | "downtrend"
            is_confirmed_uptrend : bool — safe to take new positions
            distribution_days    : int  — count of distribution days in last 25
            sma_aligned          : bool — SMA21 > SMA50 > SMA150 > SMA200
            price_above_sma200   : bool
            price_above_sma50    : bool
            sma50_rising         : bool — SMA50 trending up over last 10 sessions
            obv_rising           : bool — OBV above its 21-day SMA
        """
        today = datetime.today()
        start = (today - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
        end = today.strftime("%Y-%m-%d")

        df = self.fmp.daily_chart("^SPX", start, end)
        df = df.sort_values("date").reset_index(drop=True)

        # SMAs computed locally — avoids extra API calls
        for p in [21, 50, 150, 200]:
            df[f"SMA{p}"] = df["close"].rolling(window=p).mean()

        # OBV
        df["_price_chg"] = df["close"].diff()
        df["_obv_day"] = df["volume"] * ((df["_price_chg"] > 0).astype(int) * 2 - 1)
        df["OBV"] = df["_obv_day"].cumsum()
        df["OBV_SMA21"] = df["OBV"].rolling(window=21).mean()

        # Distribution day: closes lower AND volume higher than previous session
        df["_down"] = df["close"] < df["close"].shift(1)
        df["_higher_vol"] = df["volume"] > df["volume"].shift(1)
        df["dist_day"] = (df["_down"] & df["_higher_vol"]).astype(int)
        distribution_days = int(df.tail(25)["dist_day"].sum())

        latest = df.iloc[-1]

        price_above_sma200 = bool(latest["close"] > latest["SMA200"])
        price_above_sma150 = bool(latest["close"] > latest["SMA150"])
        price_above_sma50 = bool(latest["close"] > latest["SMA50"])
        sma_aligned = bool(
            latest["SMA21"] > latest["SMA50"]
            and latest["SMA50"] > latest["SMA150"]
            and latest["SMA150"] > latest["SMA200"]
        )
        sma50_rising = bool(df["SMA50"].tail(10).diff().sum() > 0)
        obv_rising = bool(latest["OBV"] > latest["OBV_SMA21"])

        if price_above_sma200 and sma_aligned and sma50_rising:
            if distribution_days >= 5:
                condition = "uptrend_under_pressure"
                is_confirmed = False
            elif distribution_days >= 3:
                condition = "uptrend_under_pressure"
                is_confirmed = True   # tradeable but cautious
            else:
                condition = "uptrend"
                is_confirmed = True
        elif price_above_sma200:
            condition = "correction"
            is_confirmed = False
        else:
            condition = "downtrend"
            is_confirmed = False

        # Store for RS-line calculations downstream
        self.spx_df = df[["date", "close"]].copy()

        return {
            "condition": condition,
            "is_confirmed_uptrend": is_confirmed,
            "distribution_days": distribution_days,
            "sma_aligned": sma_aligned,
            "price_above_sma50": price_above_sma50,
            "price_above_sma150": price_above_sma150,
            "price_above_sma200": price_above_sma200,
            "sma50_rising": sma50_rising,
            "obv_rising": obv_rising,
        }

    # ------------------------------------------------------------------
    # Per-stock metric helpers
    # ------------------------------------------------------------------

    def _compute_volume_metrics(self, df):
        """
        Volume-based flags from OHLCV data.

        up_down_vol_ratio   — ratio of volume on up-days vs down-days (50-day)
                              >1.25 = institutional accumulation (O'Neil / Minervini)
        vol_ratio_today     — today's volume / 50-day average
                              >1.4 on a breakout day is the O'Neil confirmation signal
        vol_contracting     — average volume of last 20 days < prior 20 days
                              desirable during base formation (Minervini VCP)
        """
        if len(df) < 20:
            return {}

        avg_vol_50 = df["volume"].tail(50).mean()
        latest_vol = float(df["volume"].iloc[-1])

        last_50 = df.tail(50).copy()
        last_50["_up"] = last_50["close"] >= last_50["close"].shift(1)
        up_vol = last_50.loc[last_50["_up"], "volume"].sum()
        down_vol = last_50.loc[~last_50["_up"], "volume"].sum()
        ud_ratio = float(up_vol / down_vol) if down_vol > 0 else 9.99

        recent_avg = df["volume"].tail(20).mean()
        prior_avg = df["volume"].tail(40).head(20).mean()

        return {
            "avg_vol_50d": int(avg_vol_50),
            "vol_ratio_today": round(latest_vol / avg_vol_50, 2) if avg_vol_50 > 0 else 0.0,
            "up_down_vol_ratio": round(ud_ratio, 2),
            "accumulation": bool(ud_ratio >= 1.25),
            "vol_contracting_in_base": bool(recent_avg < prior_avg),
        }

    def _compute_adr(self, df, period=20):
        """
        Average Daily Range % — Minervini's volatility measure.
        ADR% = mean((high - low) / midpoint) over last {period} sessions.
        Practical range for swing trading: 3–15%.
        Below 2% = too slow; above 15% = too risky for standard position sizing.
        """
        if len(df) < period:
            return {"adr_pct": None}
        tail = df.tail(period).copy()
        tail["mid"] = (tail["high"] + tail["low"]) / 2
        tail["range_pct"] = (tail["high"] - tail["low"]) / tail["mid"] * 100
        return {"adr_pct": round(float(tail["range_pct"].mean()), 2)}

    def _compute_buy_point(self, df, max_extension_pct=5.0):
        """
        Approximates the Minervini / O'Neil pivot and extension.

        Pivot  = highest high of the prior 50 sessions (the base high).
        Extension % = (current price − pivot) / pivot × 100.

        within_buy_range : 0 % ≤ extension ≤ 5 %  (O'Neil: don't chase > 5%)
        extended         : extension > 5 %
        below_pivot      : stock has not broken out yet
        """
        if len(df) < 15:
            return {"buy_point_status": "insufficient_data"}

        base = df.iloc[-51:-1] if len(df) >= 51 else df.iloc[:-1]
        pivot = float(base["high"].max())
        current = float(df["close"].iloc[-1])
        ext = (current - pivot) / pivot * 100

        return {
            "pivot": round(pivot, 2),
            "extension_pct": round(ext, 1),
            "within_buy_range": bool(0 <= ext <= max_extension_pct),
            "extended": bool(ext > max_extension_pct),
            "below_pivot": bool(ext < 0),
        }

    def _compute_rs_line(self, df):
        """
        RS line = normalised stock return / normalised SPX return.

        O'Neil / IBD: an RS line making new highs before or with the price
        breakout is one of the most powerful confirmation signals.

        Requires self.spx_df to be populated (call get_market_direction first).
        """
        if self.spx_df is None or len(df) < 20:
            return {"rs_line_new_high": None}

        merged = df[["date", "close"]].merge(
            self.spx_df.rename(columns={"close": "spx_close"}),
            on="date",
            how="inner",
        )
        if len(merged) < 20:
            return {"rs_line_new_high": None}

        merged["rs_line"] = (
            (merged["close"] / merged["close"].iloc[0])
            / (merged["spx_close"] / merged["spx_close"].iloc[0])
            * 100
        )

        rs_52w_high = merged["rs_line"].tail(252).max()
        rs_now = float(merged["rs_line"].iloc[-1])

        return {
            "rs_line_new_high": bool(rs_now >= rs_52w_high * 0.98),
            "rs_line_value": round(rs_now, 1),
        }

    # ------------------------------------------------------------------

    def get_screening(self, tickers, startdate, enddate):
        error = False
        try:
            self.data = self.get_daily_chart(
                tickers, startdate=startdate, enddate=enddate
            )
            self.minervini_trend_template(tickers, enddate)

            # Attach supplementary metrics to the same dict
            self.trend_template_dict.update(self._compute_volume_metrics(self.data))
            self.trend_template_dict.update(self._compute_adr(self.data))
            self.trend_template_dict.update(self._compute_buy_point(self.data))
            self.trend_template_dict.update(self._compute_rs_line(self.data))
        except Exception as e:
            logger.error(f"get_screening failed for {tickers}: {e}")
            error = True
            self.data = None
            self.trend_template_dict = None

        return self.data, self.trend_template_dict, error
