"""Chart OHLC granularity for bulk analysis — mirrors UI ``ChartGranularity``."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

VALID_GRANULARITIES = frozenset({"1hour", "4hour", "1day", "1week"})
DEFAULT_GRANULARITY = "1day"


@dataclass(frozen=True)
class GranularityConfig:
    sma_windows: tuple[int, ...]
    fetch_lookback_days: int
    prompt_tail_bars: int
    recent_vol_bars: int
    vol_compare_bars: int
    bar_label: str


_CONFIGS: dict[str, GranularityConfig] = {
    "1hour": GranularityConfig(
        sma_windows=(10, 20, 50),
        fetch_lookback_days=180,
        prompt_tail_bars=120,
        recent_vol_bars=40,
        vol_compare_bars=80,
        bar_label="1-hour",
    ),
    "4hour": GranularityConfig(
        sma_windows=(10, 20, 50),
        fetch_lookback_days=365,
        prompt_tail_bars=100,
        recent_vol_bars=30,
        vol_compare_bars=60,
        bar_label="4-hour",
    ),
    "1day": GranularityConfig(
        sma_windows=(20, 50, 200),
        fetch_lookback_days=340,
        prompt_tail_bars=126,
        recent_vol_bars=20,
        vol_compare_bars=60,
        bar_label="daily",
    ),
    "1week": GranularityConfig(
        sma_windows=(4, 10, 20),
        fetch_lookback_days=365 * 5,
        prompt_tail_bars=52,
        recent_vol_bars=8,
        vol_compare_bars=24,
        bar_label="weekly",
    ),
}


def normalize_granularity(value: str | None) -> str:
    g = (value or DEFAULT_GRANULARITY).strip().lower()
    return g if g in VALID_GRANULARITIES else DEFAULT_GRANULARITY


def get_config(granularity: str | None) -> GranularityConfig:
    return _CONFIGS[normalize_granularity(granularity)]


def default_date_range(
    granularity: str | None,
    *,
    end: date | None = None,
) -> tuple[date, date]:
    """When the UI did not set a custom range, match ``fmpGetOhlc`` defaults."""
    cfg = get_config(granularity)
    end_d = end or date.today()
    start_d = end_d - timedelta(days=cfg.fetch_lookback_days)
    return start_d, end_d
