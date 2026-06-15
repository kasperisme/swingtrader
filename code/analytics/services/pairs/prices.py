"""
Price access for the pairs layer — thin wrappers over the FMP client.

  - fetch_daily_closes  : dividend/split-adjusted daily closes for calibration
  - fetch_latest_quotes : current prices (batched) for the live z-score

Both are defensive: a failure on one ticker yields an empty/absent entry rather
than aborting the whole run.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

import pandas as pd

from services.screener.fmp import fmp as FMPClient

log = logging.getLogger(__name__)


def fetch_daily_closes(
    client: FMPClient,
    tickers: list[str],
    window_days: int,
) -> dict[str, pd.Series]:
    """Return {ticker: date-indexed adjusted-close Series} for each ticker.

    Pulls a generous calendar range (~2x window to cover weekends/holidays).
    Prefers adjClose (dividend/split adjusted — required for valid
    cointegration) and falls back to close when adjClose is absent.
    """
    end = date.today()
    start = end - timedelta(days=max(window_days, 60) * 2 + 10)
    start_s, end_s = start.isoformat(), end.isoformat()

    out: dict[str, pd.Series] = {}
    for ticker in sorted({t.upper().strip() for t in tickers if t}):
        try:
            chart = client.daily_chart(ticker, start_s, end_s)
        except Exception as exc:  # network/plan/parse — skip this ticker
            log.warning("daily_chart failed for %s: %s", ticker, exc)
            continue
        if chart is None or chart.empty:
            continue
        col = "adjClose" if "adjClose" in chart.columns else "close"
        if col not in chart.columns or "date" not in chart.columns:
            continue
        s = (
            chart.set_index(pd.to_datetime(chart["date"]).dt.date)[col]
            .astype(float)
            .sort_index()
        )
        s = s[~s.index.duplicated(keep="last")]
        out[ticker] = s
    return out


def fetch_latest_quotes(
    client: FMPClient,
    tickers: list[str],
    chunk_size: int = 200,
) -> dict[str, float]:
    """Return {ticker: latest price} via the batched FMP quote endpoint."""
    symbols = sorted({t.upper().strip() for t in tickers if t})
    out: dict[str, float] = {}
    for i in range(0, len(symbols), chunk_size):
        chunk = symbols[i : i + chunk_size]
        try:
            df = client.quote_price(chunk)
        except Exception as exc:
            log.warning("quote_price failed for %d symbols: %s", len(chunk), exc)
            continue
        if df is None or df.empty or "symbol" not in df.columns or "price" not in df.columns:
            continue
        for _, r in df.iterrows():
            sym = str(r["symbol"]).upper().strip()
            try:
                out[sym] = float(r["price"])
            except (TypeError, ValueError):
                continue
    return out
