import pandas as pd
import json
from pathlib import Path
from sklearn.preprocessing import MinMaxScaler
import src.fmp as fmp
from plotly.subplots import make_subplots
import plotly.graph_objects as go

from src.logging import logger

_ROOT = Path(__file__).resolve().parent.parent


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

        self._ratio_logic = None  # lazy-loaded on first use

        self.tickerbaseurl = (
            "https://financialmodelingprep.com/api/{version}/{endpoint}"
        )
        self.rationbaseurl = (
            "https://financialmodelingprep.com/api/v3/ratios-ttm/{ticker}"
        )

    @property
    def ratio_logic(self):
        if self._ratio_logic is None:
            self._ratio_logic = json.load(open(_ROOT / "input" / "ratio_logic.json", "r"))
        return self._ratio_logic

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

        # ------------------------------------------------------------------
        # O'Neil / Minervini growth metrics
        # ------------------------------------------------------------------

        # Year-over-year growth: current quarter vs same quarter 12 months ago
        # Uses shift(4) — same fiscal quarter in the prior year
        df["eps_yoy_growth"] = (
            (df["eps"] - df["eps"].shift(4)) / df["eps"].shift(4).abs() * 100
        )
        df["rev_yoy_growth"] = (
            (df["revenue"] - df["revenue"].shift(4))
            / df["revenue"].shift(4).abs()
            * 100
        )

        # EPS acceleration: current quarter YoY growth > prior quarter YoY growth
        df["eps_accelerating"] = df["eps_yoy_growth"] > df["eps_yoy_growth"].shift(1)

        # Trailing-twelve-month EPS (sum of last 4 quarters) for annual growth check
        df["eps_ttm"] = df["eps"].rolling(window=4).sum()
        df["eps_ttm_yoy"] = (
            (df["eps_ttm"] - df["eps_ttm"].shift(4))
            / df["eps_ttm"].shift(4).abs()
            * 100
        )

        return df

    def get_fundamental_flags(self, ticker):
        """
        Returns a flat dict of fundamental screening flags aligned with
        the O'Neil (CAN SLIM) and Minervini SEPA criteria.

        Criteria applied:
        - EPS YoY growth ≥ 25 % (O'Neil current-quarter minimum)
        - Revenue YoY growth ≥ 20 % (O'Neil sales growth requirement)
        - Beat consensus EPS estimate in last 3 quarters
        - EPS accelerating quarter-over-quarter
        - 3 consecutive years of TTM EPS growth ≥ 25 % (CAN SLIM A criterion)

        Returns None if insufficient data.
        """
        try:
            df = self.get_earnings_data(ticker)
        except Exception:
            return None

        if len(df) < 5:
            return None

        latest = df.iloc[-1]

        eps_yoy = float(latest["eps_yoy_growth"]) if pd.notna(latest["eps_yoy_growth"]) else None
        rev_yoy = float(latest["rev_yoy_growth"]) if pd.notna(latest["rev_yoy_growth"]) else None
        eps_accel = bool(latest["eps_accelerating"]) if pd.notna(latest["eps_accelerating"]) else None

        # 3 consecutive years of ≥ 25 % TTM EPS growth
        annual_growth_series = (
            df.dropna(subset=["eps_ttm_yoy"])
            .tail(3)["eps_ttm_yoy"]
            .tolist()
        )
        three_yr_25pct = (
            len(annual_growth_series) >= 3
            and all(g >= 25 for g in annual_growth_series)
        )

        beat_last_3 = bool(df.tail(3)["beat_estimate"].sum() == 3)
        eps_direction = bool(latest["eps_sma_direction"] == 1)

        # ROE from key metrics (most recent quarter)
        roe = None
        roe_above_17pct = False
        try:
            km_df = self.fmp.key_metrics_quarterly(ticker, limit=2)
            if not km_df.empty:
                roe_raw = km_df.iloc[-1].get("returnOnEquity")
                if roe_raw is not None:
                    roe = round(float(roe_raw) * 100, 1)  # FMP returns decimal (0.23 = 23%)
                    roe_above_17pct = bool(roe >= 17)
        except Exception:
            pass  # ROE is supplementary — do not block

        passes_oneil = bool(
            eps_yoy is not None and eps_yoy >= 25
            and rev_yoy is not None and rev_yoy >= 20
            and beat_last_3
            and roe_above_17pct
        )

        return {
            # Carry-over from original checks
            "increasing_eps": eps_direction,
            "beat_estimate": beat_last_3,
            # Growth rates
            "eps_growth_yoy": round(eps_yoy, 1) if eps_yoy is not None else None,
            "rev_growth_yoy": round(rev_yoy, 1) if rev_yoy is not None else None,
            # Acceleration
            "eps_accelerating": eps_accel,
            # 3-year annual criterion
            "three_yr_annual_eps_25pct": three_yr_25pct,
            # ROE
            "roe": roe,
            "roe_above_17pct": roe_above_17pct,
            # Composite O'Neil pass (now includes ROE)
            "passes_oneil_fundamentals": passes_oneil,
        }

    def get_sector_leadership(self, sector):
        """
        Checks whether the given sector is in the top 40 % of S&P sectors
        by today's performance — O'Neil's sector-leadership filter.

        Returns dict with sector_rank, total_sectors, sector_pct_change,
        sector_is_leader.  All values are None if the lookup fails.
        """
        _null = {"sector_rank": None, "total_sectors": None,
                 "sector_pct_change": None, "sector_is_leader": None}
        try:
            raw = self.fmp.sector_performance()
            df = pd.DataFrame(raw)

            # changesPercentage may arrive as "1.23%" string or as a float
            def _parse_pct(v):
                if isinstance(v, str):
                    return float(v.replace("%", "").strip())
                return float(v)

            df["pct"] = df["changesPercentage"].apply(_parse_pct)
            df = df.sort_values("pct", ascending=False).reset_index(drop=True)
            total = len(df)

            # Fuzzy match — FMP sector names can differ slightly from profile data
            match = df[df["sector"].str.lower().str.contains(
                sector.lower().split()[0], na=False
            )]
            if match.empty:
                return _null

            rank = int(match.index[0] + 1)
            return {
                "sector_rank": rank,
                "total_sectors": total,
                "sector_pct_change": round(float(match["pct"].iloc[0]), 2),
                "sector_is_leader": bool(rank / total <= 0.40),
            }
        except Exception:
            return _null

    def get_institutional_flags(self, ticker: str) -> dict:
        """
        Analyzes quarter-over-quarter changes in institutional ownership from 13-F data.

        Returns a flat dict with:
        - inst_holders              : int   — number of institutional holders (latest quarter)
        - inst_shares_held          : float — total shares held institutionally
        - inst_ownership_pct        : float — % of shares outstanding held institutionally
        - inst_holders_increasing   : bool  — holder count up vs prior quarter
        - inst_shares_increasing    : bool  — total shares held up vs prior quarter
        - inst_ownership_pct_increasing: bool
        - inst_net_new_holders      : int   — delta in holder count vs prior quarter
        - inst_qoq_share_change_pct : float — % change in shares held vs prior quarter

        Returns {} on any exception (supplementary data — must not block the pipeline).
        """
        try:
            df = self.fmp.institutional_ownership_summary(ticker)
        except Exception:
            return {}

        if df.empty or len(df) < 1:
            return {}

        # Use the dominant filing date (the one with the most records — most complete 13-F tranche)
        if "dateReported" not in df.columns or "shares" not in df.columns:
            return {}

        df["dateReported"] = pd.to_datetime(df["dateReported"], errors="coerce")
        df = df.dropna(subset=["dateReported"])

        # Most complete quarter = date with the most individual holder filings
        latest_date = df["dateReported"].value_counts().index[0]
        latest_df = df[df["dateReported"] == latest_date]

        holders_now = int(latest_df["holder"].nunique())
        shares_now = float(latest_df["shares"].sum())

        # net_change: sum of change values from most recent filings (positive = accumulation)
        net_change = float(latest_df["change"].sum()) if "change" in latest_df.columns else None
        pct_accumulators = None
        if "change" in latest_df.columns and len(latest_df) > 0:
            n_accumulating = int((latest_df["change"] > 0).sum())
            pct_accumulators = round(n_accumulating / len(latest_df) * 100, 1)

        return {
            "inst_holders": holders_now,
            "inst_shares_held": shares_now,
            "inst_ownership_pct": None,   # not available from this endpoint
            "inst_holders_increasing": None,  # can't determine without prior-period aggregate
            "inst_shares_increasing": bool(net_change > 0) if net_change is not None else None,
            "inst_ownership_pct_increasing": None,
            "inst_net_new_holders": None,
            "inst_qoq_share_change_pct": (
                round(net_change / (shares_now - net_change) * 100, 1)
                if net_change is not None and (shares_now - net_change) > 0 else None
            ),
            "inst_pct_accumulating": pct_accumulators,  # % of holders that increased positions
        }

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
