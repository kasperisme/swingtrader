"""News-impact overlay — the proprietary signal, made backtestable.

Pulls per-ticker scored sentiment out of the swingtrader Supabase instance and
folds it into a daily grid the backtester can read.

Two rules keep it honest:

  * **Publication-time alignment.** An article is attributed to the session it
    could first have been acted on: articles published after 16:00 US/Eastern
    belong to the NEXT trading day. Aggregating by naive UTC calendar date
    quietly hands the strategy a few hours of hindsight on every evening story.
  * **Coverage window.** Scoring only exists from the day the pipeline started.
    `coverage()` reports that window and the backtest clips to it, so a genome
    that switches the overlay on is scored on the period where the data is real
    instead of on a decade of silent zeros.
"""

from __future__ import annotations

import logging
import os
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from ..config import load_env, news_cache_dir

log = logging.getLogger(__name__)

_CACHE_NAME = "ticker_daily_sentiment.csv.gz"


def _connect():
    load_env()
    try:
        import psycopg2
    except ImportError as exc:
        raise RuntimeError("psycopg2-binary is required for the news overlay") from exc

    host = os.environ.get("SUPABASE_DB_POOLER_HOST")
    pwd = os.environ.get("SUPABASE_DB_PWD")
    if not host or not pwd:
        raise RuntimeError("SUPABASE_DB_POOLER_HOST / SUPABASE_DB_PWD not set")
    user = os.environ.get("SUPABASE_DB_USER")
    if not user:
        # Pooler hosts encode the project ref in the username.
        ref = os.environ.get("SUPABASE_URL", "").split("//")[-1].split(".")[0]
        user = f"postgres.{ref}" if ref else "postgres"
    return psycopg2.connect(host=host, port=int(os.environ.get("SUPABASE_DB_PORT", 6543)),
                            dbname=os.environ.get("SUPABASE_DB_NAME", "postgres"),
                            user=user, password=pwd, connect_timeout=20)


class NewsStore:
    def __init__(self, cache_dir: Path | None = None):
        self.dir = Path(cache_dir or news_cache_dir())
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path = self.dir / _CACHE_NAME

    # ------------------------------------------------------------ sync ---
    def sync(self) -> dict:
        """Materialise ticker x trading-day sentiment into the local cache."""
        schema = os.environ.get("SUPABASE_SCHEMA", "swingtrader")
        sql = f"""
            SELECT
              upper(h.ticker)                                   AS ticker,
              -- Attribute to the session the news could first be traded on:
              -- anything after the 16:00 ET close belongs to the next day.
              (((h.article_ts AT TIME ZONE 'America/New_York')
                 + interval '8 hours')::date)                   AS trade_date,
              avg(h.sentiment_score)                            AS mean_sentiment,
              count(*)                                          AS n_articles,
              avg(h.confidence)                                 AS mean_confidence
            FROM {schema}.ticker_sentiment_heads h
            WHERE h.article_ts IS NOT NULL
              AND h.sentiment_score IS NOT NULL
            GROUP BY 1, 2
        """
        conn = _connect()
        try:
            # A plain cursor rather than pandas.read_sql: psycopg2 connections
            # are not SQLAlchemy connectables and read_sql warns about it.
            with conn.cursor() as cur:
                cur.execute(sql)
                cols = [c[0] for c in cur.description]
                df = pd.DataFrame(cur.fetchall(), columns=cols)
        finally:
            conn.close()
        df["trade_date"] = pd.to_datetime(df["trade_date"])
        df = df.sort_values(["ticker", "trade_date"]).reset_index(drop=True)
        df.to_csv(self.path, index=False, compression="gzip")
        return {"rows": len(df), "tickers": int(df["ticker"].nunique()),
                "from": str(df["trade_date"].min().date()) if len(df) else None,
                "to": str(df["trade_date"].max().date()) if len(df) else None}

    # ------------------------------------------------------------ load ---
    def load(self) -> pd.DataFrame | None:
        if not self.path.exists():
            return None
        df = pd.read_csv(self.path, parse_dates=["trade_date"])
        return df if len(df) else None

    def coverage(self) -> tuple[date, date] | None:
        df = self.load()
        if df is None:
            return None
        return df["trade_date"].min().date(), df["trade_date"].max().date()

    # ------------------------------------------------------- panel align --
    def align(self, symbols: list[str], dates: np.ndarray, lookback: int) -> dict[str, np.ndarray]:
        """Rolling mean sentiment and article count over `lookback` sessions.

        Both matrices are shaped (n_days, n_symbols). Missing coverage stays
        NaN — the gate layer reads NaN as "no evidence", never as "positive".
        """
        n, m = len(dates), len(symbols)
        empty = {"news_sentiment": np.full((n, m), np.nan),
                 "news_articles": np.full((n, m), np.nan)}
        df = self.load()
        if df is None:
            return empty

        grid = pd.DatetimeIndex(dates)
        wanted = set(symbols)
        df = df[df["ticker"].isin(wanted)]
        if df.empty:
            return empty

        # Pivot to date x ticker, reindex onto the panel grid, then roll.
        sent = df.pivot_table(index="trade_date", columns="ticker",
                              values="mean_sentiment", aggfunc="mean")
        cnt = df.pivot_table(index="trade_date", columns="ticker",
                             values="n_articles", aggfunc="sum")
        sent = sent.reindex(index=grid, columns=symbols)
        cnt = cnt.reindex(index=grid, columns=symbols).fillna(0.0)

        # Article-weighted rolling mean: a single low-confidence mention should
        # not carry the same weight as a day with a dozen scored stories.
        num = (sent * cnt).rolling(lookback, min_periods=1).sum()
        den = cnt.rolling(lookback, min_periods=1).sum()
        roll_sent = num / den.replace(0.0, np.nan)
        roll_cnt = den

        out = {"news_sentiment": roll_sent.to_numpy(dtype=np.float64),
               "news_articles": roll_cnt.to_numpy(dtype=np.float64)}
        # Outside the coverage window the answer is "unknown", not "zero".
        cov = self.coverage()
        if cov:
            before = grid < pd.Timestamp(cov[0])
            out["news_sentiment"][before, :] = np.nan
            out["news_articles"][before, :] = np.nan
        return out
