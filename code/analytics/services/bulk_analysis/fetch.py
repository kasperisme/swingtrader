"""
Fetch OHLCV from FMP at chart granularity and compute SMAs locally.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd

from services.screener.fmp import fmp

from .chart_granularity import (
    DEFAULT_GRANULARITY,
    get_config,
    normalize_granularity,
)


def _parse_ymd(value: str | date | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    s = str(value).strip()[:10]
    if not s:
        return None
    return datetime.strptime(s, "%Y-%m-%d").date()


def _resample_weekly(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"])
    out = out.set_index("date")
    weekly = out.resample("W-FRI").agg(
        {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }
    )
    weekly = weekly.dropna(subset=["close"]).reset_index()
    return weekly


def fetch_history(
    ticker: str,
    *,
    granularity: str | None = None,
    date_from: str | date | None = None,
    date_to: str | date | None = None,
) -> pd.DataFrame:
    """
    Return columns: date, open, high, low, close, volume, sma_* per granularity config.

    ``granularity`` matches the screenings chart picker: 1hour | 4hour | 1day | 1week.
    Optional ``date_from`` / ``date_to`` (YYYY-MM-DD) come from the UI snapshot; when
    omitted, lookback follows the same defaults as ``fmpGetOhlc``.
    """
    gran = normalize_granularity(granularity)
    cfg = get_config(gran)

    end = _parse_ymd(date_to) or date.today()
    start = _parse_ymd(date_from)
    if start is None:
        start = end - timedelta(days=int(cfg.fetch_lookback_days * 1.15))
    if start > end:
        start, end = end, start

    client = fmp()
    if gran in ("1hour", "4hour"):
        fmp_interval = "1hour" if gran == "1hour" else "4hour"
        df = client.intraday_chart(
            fmp_interval, ticker, start.isoformat(), end.isoformat()
        )
    else:
        df = client.daily_chart(ticker, start.isoformat(), end.isoformat())
        if gran == "1week" and df is not None and not df.empty:
            df = _resample_weekly(df)

    if df is None or df.empty:
        return pd.DataFrame()

    df = df.copy()
    for w in cfg.sma_windows:
        df[f"sma_{w}"] = df["close"].rolling(window=w, min_periods=w).mean()
    df.attrs["bulk_granularity"] = gran
    df.attrs["bulk_sma_windows"] = cfg.sma_windows
    return df


def summarize_for_prompt(
    df: pd.DataFrame,
    *,
    granularity: str | None = None,
) -> dict[str, Any]:
    """
    Compact payload for the LLM — bar count and SMA windows depend on granularity.
    """
    if df is None or df.empty:
        return {}

    gran = normalize_granularity(
        str(df.attrs.get("bulk_granularity") or granularity or DEFAULT_GRANULARITY)
    )
    cfg = get_config(gran)
    sma_windows: tuple[int, ...] = tuple(
        df.attrs.get("bulk_sma_windows") or cfg.sma_windows
    )

    window = df.tail(cfg.prompt_tail_bars).reset_index(drop=True)
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
        if f != f:
            return None
        return round(f, 4)

    recent_vol = volumes.tail(cfg.recent_vol_bars).mean()
    older_slice = volumes.tail(cfg.vol_compare_bars).head(
        max(1, cfg.vol_compare_bars - cfg.recent_vol_bars)
    )
    older_vol = older_slice.mean() if len(older_slice) else None
    vol_trend = None
    if older_vol and older_vol > 0:
        vol_trend = round(float(recent_vol / older_vol), 3)

    sma_values: dict[str, float | None] = {}
    for w in sma_windows:
        sma_values[f"sma_{w}"] = _f(last.get(f"sma_{w}"))

    sma_stack = None
    if len(sma_windows) >= 3:
        a, b, c = (
            sma_values.get(f"sma_{sma_windows[0]}"),
            sma_values.get(f"sma_{sma_windows[1]}"),
            sma_values.get(f"sma_{sma_windows[2]}"),
        )
        if all(v is not None for v in (a, b, c)):
            if a > b > c:  # type: ignore[operator]
                labels = "/".join(str(w) for w in sma_windows)
                sma_stack = f"bullish ({labels} ascending)"
            elif a < b < c:  # type: ignore[operator]
                labels = "/".join(str(w) for w in sma_windows)
                sma_stack = f"bearish ({labels} descending)"
            else:
                sma_stack = "mixed"

    last_n = min(30, len(closes))
    last_closes = [_f(c) for c in closes.tail(last_n).tolist()]

    date_str = str(last.get("date"))
    if " " in date_str:
        last_date = date_str[:16]
    else:
        last_date = date_str[:10]

    return {
        "granularity": gran,
        "bar_label": cfg.bar_label,
        "last_date": last_date,
        "last_close": _f(last["close"]),
        "last_volume": _f(last["volume"]),
        "range_window": {
            "high": _f(highs.max()),
            "low": _f(lows.min()),
        },
        "smas": {**sma_values, "stack": sma_stack, "windows": list(sma_windows)},
        "volume": {
            f"avg_recent_{cfg.recent_vol_bars}": _f(recent_vol),
            f"avg_prior_{cfg.vol_compare_bars}": _f(volumes.tail(cfg.vol_compare_bars).mean()),
            "ratio_recent_vs_prior": vol_trend,
        },
        "last_closes": last_closes,
        "bars_total": int(len(window)),
    }
