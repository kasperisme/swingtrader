import pandas as pd
import json
from sklearn.preprocessing import MinMaxScaler
import src.fmp as fmp

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


if __name__ == "__main__":
    fundamentals = Fundamentals()
    fundamentals.get_ratios()
    print(fundamentals.ratio)
