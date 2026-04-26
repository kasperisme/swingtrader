import os
import requests
import pandas as pd
from shared.logging import logger


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
        url = f"https://financialmodelingprep.com/stable/company-screener?exchange={exchange}&isEtf=false&isFund=false&isActivelyTrading=true&limit=10000"

        r = requests.get(url, params={"apikey": self.APIKEY})
        if r.status_code != 200:
            raise RequestError

        return self.__format_ticker_df(r)

    def profile(self, tickers: list) -> pd.DataFrame:
        """
        Company profile (sector, industry, …) for one or many symbols.
        Batched to respect URL length limits.
        """
        if not tickers:
            return pd.DataFrame()
        chunk_size = 80
        frames = []
        for i in range(0, len(tickers), chunk_size):
            chunk = tickers[i : i + chunk_size]
            joined = ",".join(chunk)
            url = f"https://financialmodelingprep.com/api/v3/profile/{joined}"
            r = requests.get(url, params={"apikey": self.APIKEY})
            if r.status_code != 200:
                raise RequestError(r.content)
            data = r.json()
            if not data:
                continue
            frames.append(pd.DataFrame(data))
        if not frames:
            return pd.DataFrame()
        return pd.concat(frames, axis=0).reset_index(drop=True)

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

    def earningscalltranscript(self, ticker, year, quarter):
        url = f"https://financialmodelingprep.com/api/v3/earning_call_transcript/{ticker}?year={year}&quarter={quarter}"

        response = requests.get(url, params={"apikey": self.APIKEY})

        if response.status_code != 200:
            raise Exception(
                "API response on earnings call transcript: " + str(response.status_code)
            )

        data = response.json()

        return data

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

    def intraday_chart(self, interval, ticker, startdate, enddate):
        url = f"https://financialmodelingprep.com/api/v3/historical-chart/{interval}/{ticker}?from={startdate}&to={enddate}"

        response = requests.get(url, params={"apikey": self.APIKEY})

        if response.status_code != 200:
            raise Exception("API response on chart: " + str(response.status_code))

        data = response.json()

        chart = pd.DataFrame(data)
        chart["date"] = pd.to_datetime(chart["date"])
        chart = chart.sort_values(by="date", ascending=True).reset_index(drop=True)
        return chart

    def stock_screener(
        self,
        price_min: float = 15.0,
        volume_min: int = 300_000,
        country: str = "US",
        exchange: str = "nyse,nasdaq",
        limit: int = 3000,
    ) -> pd.DataFrame:
        """
        FMP stock screener — returns all US-listed stocks that pass basic
        liquidity and price filters in a single API call.

        Used as an upstream filter before the per-ticker Minervini loop so
        that tickers that can't possibly pass are never fetched individually.

        Parameters deliberately set slightly looser than our hard thresholds
        (price_min=15, volume_min=300k vs our 400k) to avoid edge cases where
        FMP's volume metric differs slightly from the quote's avgVolume.
        """
        url = "https://financialmodelingprep.com/api/v3/stock-screener"
        params = {
            "apikey": self.APIKEY,
            "priceMoreThan": price_min,
            "volumeMoreThan": volume_min,
            "country": country,
            "exchange": exchange,
            "isActivelyTrading": "true",
            "limit": limit,
        }
        r = requests.get(url, params=params)
        if r.status_code != 200:
            raise RequestError(r.content)
        return pd.DataFrame(r.json())

    def sector_performance(self):
        """Current daily performance % for each S&P sector."""
        url = "https://financialmodelingprep.com/api/v3/sectors-performance"
        r = requests.get(url, params={"apikey": self.APIKEY})
        if r.status_code != 200:
            raise RequestError(r.content)
        return r.json()

    def shares_float(self, ticker):
        """Free float and shares outstanding for a ticker."""
        url = "https://financialmodelingprep.com/api/v3/shares-float"
        r = requests.get(url, params={"apikey": self.APIKEY, "symbol": ticker})
        if r.status_code != 200:
            raise RequestError(r.content)
        return self.__format_ticker_df(r)

    def institutional_ownership_summary(self, ticker):
        """
        Individual institutional holder records from 13-F filings.
        Returns one row per holder per reporting date (holder, shares, dateReported, change).
        Caller should aggregate by quarter to compute totals and QoQ changes.
        """
        url = f"https://financialmodelingprep.com/api/v3/institutional-holder/{ticker}"
        r = requests.get(url, params={"apikey": self.APIKEY})
        if r.status_code != 200:
            raise RequestError(r.content)
        return self.__format_ticker_df(r)

    def price_target(self, ticker):
        url = f"https://financialmodelingprep.com/api/v4/price-target-consensus?symbol={ticker}"

        response = requests.get(url, params={"apikey": self.APIKEY})

        if response.status_code != 200:
            raise Exception("API response on pricetarget: " + str(response.status_code))

        pt = response.json()

        return pt

    def income_statement_quarterly(self, ticker: str, limit: int = 12) -> pd.DataFrame:
        """Quarterly income statements (revenue, netIncome, eps, grossProfit) — last {limit} quarters."""
        url = "https://financialmodelingprep.com/stable/income-statement"
        r = requests.get(url, params={
            "apikey": self.APIKEY,
            "symbol": ticker,
            "period": "quarter",
            "limit": limit,
        })
        if r.status_code != 200:
            raise RequestError(r.content)
        data = r.json()
        if not data:
            return pd.DataFrame()
        df = pd.DataFrame(data)
        if not df.empty and "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])
            df = df.sort_values("date").reset_index(drop=True)
        return df

    def key_metrics_quarterly(self, ticker: str, limit: int = 4) -> pd.DataFrame:
        """
        Key fundamental metrics (returnOnEquity, roic, currentRatio, etc.) — last {limit} annual periods.
        Note: quarterly period requires a premium FMP subscription; annual is used here.
        """
        url = "https://financialmodelingprep.com/stable/key-metrics"
        r = requests.get(url, params={
            "apikey": self.APIKEY,
            "symbol": ticker,
            "limit": limit,
        })
        if r.status_code != 200:
            raise RequestError(r.content)
        data = r.json()
        if not data:
            return pd.DataFrame()
        df = pd.DataFrame(data)
        if not df.empty and "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])
            df = df.sort_values("date").reset_index(drop=True)
        return df

    def earnings_calendar_range(self, from_date: str, to_date: str) -> pd.DataFrame:
        """
        Confirmed upcoming earnings calendar for a date range (all tickers).
        from_date, to_date: 'YYYY-MM-DD' strings.
        Returns: symbol, date, time (bmo/amc), epsEstimated, revenueEstimated.
        """
        url = "https://financialmodelingprep.com/stable/earnings-calendar-confirmed"
        r = requests.get(url, params={
            "apikey": self.APIKEY,
            "from": from_date,
            "to": to_date,
        })
        if r.status_code != 200:
            raise RequestError(r.content)
        data = r.json()
        if not data:
            return pd.DataFrame()
        return pd.DataFrame(data)
