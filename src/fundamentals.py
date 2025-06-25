import pandas as pd
import json
from sklearn.preprocessing import MinMaxScaler
import src.fmp as fmp
from plotly.subplots import make_subplots
import plotly.graph_objects as go

from src.logging import logger


class RequestError(Exception):
    def __init__(self, content):
        self.content = content
        super().__init__()

    def __str__(self):
        return f"Request Error: {self.content}"


class Fundamentals:
    def __init__(self) -> None:

        self.fmp = fmp.fmp()

        self.sector_options = self.fmp.sectors()

        self.sector = self.sector_options[0]
        self.tickers = []

        self.ratio_scaled = None

        self.ratio_ranked = None

        self.ratio_logic = json.load(open("./input/ratio_logic.json", "r"))

        self.tickerbaseurl = (
            "https://financialmodelingprep.com/api/{version}/{endpoint}"
        )
        self.rationbaseurl = (
            "https://financialmodelingprep.com/api/v3/ratios-ttm/{ticker}"
        )

    def get_ratios(self):
        logger.info(f"Getting SP500 tickers")
        self.tickers = self.fmp.sp500tickers()

        self.tickers = self.tickers[self.tickers["sector"] == self.sector][
            "symbol"
        ].tolist()

        ls_ratio = []
        for ticker in self.tickers:
            logger.info(f"Getting ratios for {ticker}")
            df_ratio = self.fmp.ratio(ticker)

            df_ratio["symbol"] = ticker

            ls_ratio.append(df_ratio)

        self.ratio = pd.concat(ls_ratio, axis=0)

        return self.ratio

    def get_earnings(self, ticker):
        logger.info(f"Getting earnings for {ticker}")
        earnings = self.fmp.earnings_calender(ticker)
        return earnings

    def scale_ratios(self):

        self.ratio_scaled = self.ratio.copy()

        for i in self.ratio_logic:
            if "direction" in i.keys():
                self.ratio_scaled[i["name"]] = (
                    self.ratio_scaled[i["name"]] * i["direction"]
                )

        cols = [key["name"] for key in self.ratio_logic]

        scaler = MinMaxScaler()

        self.ratio_scaled[cols] = scaler.fit_transform(self.ratio_scaled[cols])

        self.ratio_scaled["score"] = self.ratio_scaled[cols].mean(axis=1)

        cols.extend(["symbol", "score"])

        self.ratio_scaled = self.ratio_scaled[cols]

        self.ratio_ranked = self.ratio_scaled.set_index("symbol")

        self.ratio_ranked = self.ratio_ranked.rank(method="max", ascending=False)

        return self.ratio_scaled

    def get_earnings_data(self, ticker):
        today = pd.Timestamp.today()

        df = self.get_earnings(ticker)
        df = df.dropna(subset=["eps", "revenue"])
        df = df.sort_values("date")
        df["date"] = pd.to_datetime(df["date"])
        df = df[df["date"] < today]

        df["eps_sma"] = df["eps"].rolling(window=4).mean()
        df["eps_sma_slope"] = df["eps_sma"].diff()
        df["eps_sma_direction"] = (df["eps_sma_slope"] > 0).astype(int)
        df["eps_pct_change"] = df["eps"].diff() / abs(df["eps"].shift(1))
        df["eps_pct_change_annual"] = df["eps"].diff() / abs(df["eps"].shift(4))
        df["eps_sma_gap"] = df["eps"] - df["eps_sma"]
        df["beat_estimate"] = (df["eps"] >= df["epsEstimated"]).astype(int)

        mask = df["eps_sma_slope"] > 0
        df["eps_sma_slope_above"] = 0.0
        df["eps_sma_slope_below"] = 0.0
        df.loc[mask, "eps_sma_slope_above"] = df.loc[mask, "eps_sma_slope"]
        df.loc[~mask, "eps_sma_slope_below"] = df.loc[~mask, "eps_sma_slope"]

        mask = df["eps_sma_gap"] > 0
        df["eps_sma_gap_above"] = 0.0
        df["eps_sma_gap_below"] = 0.0
        df.loc[mask, "eps_sma_gap_above"] = df.loc[mask, "eps_sma_gap"]
        df.loc[~mask, "eps_sma_gap_below"] = df.loc[~mask, "eps_sma_gap"]

        df["revenue_sma"] = df["revenue"].rolling(window=4).mean()
        df["revenue_sma_slope"] = df["revenue_sma"].diff()
        df["revenue_sma_direction"] = (df["revenue_sma_slope"] > 0).astype(int)
        df["revenue_pct_change"] = df["revenue"].diff() / abs(df["revenue"].shift(1))
        df["revenue_pct_change_annual"] = df["revenue"].diff() / abs(
            df["revenue"].shift(4)
        )

        return df

    def get_earnings_graph(self, ticker):
        df = self.get_earnings_data(ticker)

        fig = make_subplots(
            rows=3,
            cols=1,
            shared_xaxes=True,
        )
        template = "plotly_dark"

        fig.update_layout(
            template=template,
            yaxis_fixedrange=False,
            xaxis_rangeslider_visible=False,
        )

        mask = df["symbol"] == ticker

        fig.add_trace(
            go.Bar(
                x=df[mask]["date"],
                y=df[mask]["eps"],
                opacity=0.5,
                name="EPS",
            ),
            row=1,
            col=1,
        )

        fig.add_trace(
            go.Bar(
                x=df["date"],
                y=df["epsEstimated"],
                name="epsEst",
                opacity=0.5,
            ),
            row=1,
            col=1,
        )

        fig.add_trace(
            go.Scatter(
                x=df["date"],
                y=df["eps_sma"],
                mode="lines",
                name="epsSMA",
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

        return fig


if __name__ == "__main__":
    fundamentals = Fundamentals()
    fundamentals.get_ratios()
    print(fundamentals.ratio)
