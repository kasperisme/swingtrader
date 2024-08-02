import os
import requests
import pandas as pd
from src.logging import logger


class RequestError(Exception):
    def __init__(self, content):
        self.content = content
        super().__init__()

    def __str__(self):
        return f"Request Error: {self.content}"


class fmp:
    def __init__(self):
        self.APIKEY = os.environ["APIKEY"]

    def __format_ticker_df(self, r: requests.models.Response):
        df = pd.json_normalize(r.json())
        return df

    def ratio(self, ticker=None):
        url = f"https://financialmodelingprep.com/api/v3/ratios-ttm/{ticker}"

        r = requests.get(url, params={"apikey": self.APIKEY})

        return self.__format_ticker_df(r)

    def earnings_calender(self, ticker):
        url = f"https://financialmodelingprep.com/api/v3/historical/earning_calendar/{ticker}"

        r = requests.get(url, params={"apikey": self.APIKEY})
        if r.status_code != 200:
            raise RequestError

        return self.__format_ticker_df(r)

    def sectors(self):
        url = f"https://financialmodelingprep.com/api/v3/sectors-list"

        r = requests.get(url, params={"apikey": self.APIKEY})
        if r.status_code != 200:
            raise RequestError

        return r.json()

    def industries(self):
        url = f"https://financialmodelingprep.com/api/v3/industries-list"

        r = requests.get(url, params={"apikey": self.APIKEY})
        if r.status_code != 200:
            raise RequestError

        return r.json()

    def sp500tickers(self):
        url = f"https://financialmodelingprep.com/api/v3/sp500_constituent"

        r = requests.get(url, params={"apikey": self.APIKEY})
        if r.status_code != 200:
            raise RequestError

        return self.__format_ticker_df(r)

    def indices_tickers(self):
        url = f"https://financialmodelingprep.com/api/v3/symbol/available-indexes"

        r = requests.get(url, params={"apikey": self.APIKEY})
        if r.status_code != 200:
            raise RequestError

        return self.__format_ticker_df(r)

    def exchange_tickers(self, exchange: str):
        url = f"https://financialmodelingprep.com/api/v3/symbol/{exchange}"

        r = requests.get(url, params={"apikey": self.APIKEY})
        if r.status_code != 200:
            raise RequestError

        return self.__format_ticker_df(r)

    def quote_price(self, tickers: list):
        joined_tickers = ",".join(tickers)

        url = f"https://financialmodelingprep.com/api/v3/quote/{joined_tickers}"

        response = requests.get(url, params={"apikey": self.APIKEY})

        if response.status_code != 200:
            raise Exception("API response on eod prices: " + str(response.status_code))

        data = response.json()

        df = pd.DataFrame(data)

        return df

    def change_price(self, tickers: list):
        if len(tickers) < 500:
            joined_tickers = ",".join(tickers)

            url = f"https://financialmodelingprep.com/api/v3/stock-price-change/{joined_tickers}"

            response = requests.get(url, params={"apikey": self.APIKEY})

            if response.status_code != 200:
                raise Exception(
                    "API response on eod prices: " + str(response.status_code)
                )

            data = response.json()

            df = pd.DataFrame(data)

            return df
        else:
            logger.info("Getting change in chunks")
            df = pd.DataFrame()
            for i in range(0, len(tickers), 500):
                joined_tickers = ",".join(tickers[i : i + 500])

                url = f"https://financialmodelingprep.com/api/v3/stock-price-change/{joined_tickers}"

                response = requests.get(url, params={"apikey": self.APIKEY})

                if response.status_code != 200:
                    raise Exception(
                        "API response on eod prices: " + str(response.status_code)
                    )

                data = response.json()

                df = pd.concat([df, pd.DataFrame(data)], axis=0)

            return df

    def sma(self, ticker, period, startdate, enddate):
        url = f"https://financialmodelingprep.com/api/v3/technical_indicator/1day/{ticker}?type=sma&period={period}&from={startdate}&to={enddate}"

        response = requests.get(url, params={"apikey": self.APIKEY})

        if response.status_code != 200:
            raise Exception("API response on SMA200: " + str(response.status_code))

        data = response.json()

        sma = pd.DataFrame(data)

        sma["date"] = pd.to_datetime(sma["date"])

        colname = "SMA{}".format(period)
        sma = sma.rename(columns={"sma": colname})
        sma = sma[["date", colname]]
        return sma

    def rsi(self, ticker, period, startdate, enddate):
        url = f"https://financialmodelingprep.com/api/v3/technical_indicator/1day/{ticker}?type=rsi&period={period}&from={startdate}&to={enddate}"

        response = requests.get(url, params={"apikey": self.APIKEY})

        if response.status_code != 200:
            raise Exception("API response on RSI: " + str(response.status_code))

        data = response.json()

        rsi = pd.DataFrame(data)

        rsi["date"] = pd.to_datetime(rsi["date"])

        colname = "RSI{}".format(period)
        rsi = rsi.rename(columns={"rsi": colname})
        rsi = rsi[["date", colname]]
        return rsi

    def daily_chart(self, ticker, startdate, enddate):
        url = f"https://financialmodelingprep.com/api/v3/historical-price-full/{ticker}?from={startdate}&to={enddate}"

        response = requests.get(url, params={"apikey": self.APIKEY})

        if response.status_code != 200:
            raise Exception("API response on chart: " + str(response.status_code))

        data = response.json()

        chart = pd.DataFrame(data["historical"])
        chart["date"] = pd.to_datetime(chart["date"])
        chart = chart.sort_values(by="date", ascending=True).reset_index(drop=True)
        return chart

    def price_target(self, ticker):
        url = f"https://financialmodelingprep.com/api/v4/price-target-consensus?symbol={ticker}"

        response = requests.get(url, params={"apikey": self.APIKEY})

        if response.status_code != 200:
            raise Exception("API response on pricetarget: " + str(response.status_code))

        pt = response.json()

        return pt
