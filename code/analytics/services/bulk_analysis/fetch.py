"""
Fetch 6mo OHLCV from FMP and compute SMAs locally.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pandas as pd

from services.screener.fmp import fmp


SMA_WINDOWS = (20, 50, 200)
LOOKBACK_DAYS = 220  # ~6 months of trading data with headroom for SMA-200 warmup


def fetch_history(ticker: str) -> pd.DataFrame:
    """
    Return a DataFrame with columns: date, open, high, low, close, volume,
    sma_20, sma_50, sma_200.

    Pulls a slightly longer window than the rendered 6mo so the SMA-200 has
    enough warmup to be meaningful on the most recent bars; the worker
    trims to the last 6 months when summarising for the prompt.
    """
    end = date.today()
    start = end - timedelta(days=int(LOOKBACK_DAYS * 1.6))  # buffer for non-trading days

    df = fmp().daily_chart(ticker, start.isoformat(), end.isoformat())
    if df is None or df.empty:
        return pd.DataFrame()

    df = df.copy()
    # The FMP frame is already sorted ascending and typed.
    for w in SMA_WINDOWS:
        df[f"sma_{w}"] = df["close"].rolling(window=w, min_periods=w).mean()
    return df


def summarize_for_prompt(df: pd.DataFrame) -> dict[str, Any]:
    """
    Reduce a daily-bar frame to the compact payload the LLM sees.

    We don't dump 130 candles into the prompt — Ollama can't reason over
    that volume reliably and it burns tokens. Instead we send a structured
    snapshot: latest values, range stats, recent vs older volume, SMA stack,
    and the last ~30 closes for shape inspection.
    """
    if df is None or df.empty:
        return {}

    # Trim to the last 6mo for the rendered window (keep the SMA columns from
    # the full-history compute).
    window = df.tail(126).reset_index(drop=True)  # ~6 months of trading days
    last = window.iloc[-1]

    closes = window["close"].astype(float)
    highs = window["high"].astype(float)
    lows = window["low"].astype(float)
    volumes = window["volume"].astype(float)

    def _f(v: Any) -> float | None:
        try:
            f = float(v)
        except (TypeError, ValueError):
            return None
        if f != f:  # NaN
            return None
        return round(f, 4)

    recent_vol = volumes.tail(20).mean()
    older_vol = volumes.tail(60).head(40).mean()
    vol_trend = None
    if older_vol and older_vol > 0:
        vol_trend = round(float(recent_vol / older_vol), 3)

    last_close = _f(last["close"])
    sma_20 = _f(last.get("sma_20"))
    sma_50 = _f(last.get("sma_50"))
    sma_200 = _f(last.get("sma_200"))

    sma_stack = None
    if all(v is not None for v in (sma_20, sma_50, sma_200)):
        if sma_20 > sma_50 > sma_200:  # type: ignore[operator]
            sma_stack = "bullish (20 > 50 > 200)"
        elif sma_20 < sma_50 < sma_200:  # type: ignore[operator]
            sma_stack = "bearish (20 < 50 < 200)"
        else:
            sma_stack = "mixed"

    last_30_closes = [_f(c) for c in closes.tail(30).tolist()]

    return {
        "last_date": str(last.get("date"))[:10],
        "last_close": last_close,
        "last_volume": _f(last["volume"]),
        "range_6mo": {
            "high": _f(highs.max()),
            "low": _f(lows.min()),
        },
        "smas": {
            "sma_20": sma_20,
            "sma_50": sma_50,
            "sma_200": sma_200,
            "stack": sma_stack,
        },
        "volume": {
            "avg_20d": _f(recent_vol),
            "avg_60d": _f(volumes.tail(60).mean()),
            "ratio_20d_vs_prior_40d": vol_trend,
        },
        "last_30_closes": last_30_closes,
        "bars_total": int(len(window)),
    }
