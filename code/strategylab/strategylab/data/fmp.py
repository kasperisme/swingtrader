"""Thin, retrying FMP client.

Only the endpoints the lab needs, and only in the shapes the lab needs. Every
call is rate-limit aware and returns plain JSON — parsing lives with the caller
so caching decisions stay explicit.
"""

from __future__ import annotations

import logging
import random
import threading
import time
from typing import Any

import requests

from ..config import fmp_key

log = logging.getLogger(__name__)

_BASE_V3 = "https://financialmodelingprep.com/api/v3"
_BASE_V4 = "https://financialmodelingprep.com/api/v4"
_BASE_STABLE = "https://financialmodelingprep.com/stable"

# FMP rate-limits per minute, and the ceiling differs by endpoint and by plan.
# A fixed guess is always wrong in one direction: too fast and every worker
# spends its time in exponential backoff (which is far slower than just pacing
# correctly), too slow and a large pull takes hours. So the interval adapts —
# it widens sharply on a 429 and decays back toward the floor while calls
# succeed, converging on whatever the account actually allows.
_LOCK = threading.Lock()
_LAST_CALL = [0.0]
_MIN_FLOOR = 0.012
_MIN_CEILING = 2.0
_INTERVAL = [0.15]      # start conservative; the pull is long, the limit is per-minute
_OK_STREAK = [0]


class FMPError(RuntimeError):
    pass


def _throttle() -> None:
    with _LOCK:
        wait = _INTERVAL[0] - (time.monotonic() - _LAST_CALL[0])
        if wait > 0:
            time.sleep(wait)
        _LAST_CALL[0] = time.monotonic()


def _saw_rate_limit() -> None:
    with _LOCK:
        _INTERVAL[0] = min(_MIN_CEILING, max(_INTERVAL[0] * 2.0, 0.05))
        _OK_STREAK[0] = 0
        log.warning("FMP rate limit — pacing to %.2f req/s (%.2fs between calls)",
                    1.0 / _INTERVAL[0], _INTERVAL[0])


def _saw_success() -> None:
    with _LOCK:
        _OK_STREAK[0] += 1
        # FMP's burst limit is per-minute, so a backoff triggered by one burst
        # should not persist for the rest of a multi-thousand-call pull. Ease
        # back after a modest clean run rather than a very long one.
        if _OK_STREAK[0] >= 40 and _INTERVAL[0] > _MIN_FLOOR:
            _INTERVAL[0] = max(_MIN_FLOOR, _INTERVAL[0] * 0.7)
            _OK_STREAK[0] = 0


def current_rate() -> float:
    return 1.0 / _INTERVAL[0]


def _get(url: str, params: dict | None = None, retries: int = 4, timeout: float = 45.0) -> Any:
    params = dict(params or {})
    params["apikey"] = fmp_key()
    last: Exception | None = None
    for attempt in range(retries):
        _throttle()
        try:
            r = requests.get(url, params=params, timeout=timeout)
            if r.status_code == 429:
                # Record it: without this, exhausting the retries reports
                # "(None)" and hides the fact that it was a rate limit.
                last = FMPError(f"FMP 429 rate limit: {r.text[:160]}")
                _saw_rate_limit()
                time.sleep(min(30.0, 2.0 * (2 ** attempt)) + random.random())
                continue
            if r.status_code == 403:
                raise FMPError(f"FMP 403 (plan restriction): {url}")
            if r.status_code != 200:
                raise FMPError(f"FMP {r.status_code}: {r.text[:200]}")
            _saw_success()
            return r.json()
        except FMPError:
            raise
        except Exception as exc:  # network/JSON errors are retryable
            last = exc
            time.sleep(min(10.0, 1.5 * (2 ** attempt)) + random.random())
    raise FMPError(f"FMP request failed after {retries} attempts: {url} ({last})")


# ---------------------------------------------------------------- prices ---
def eod_adjusted(symbol: str, start: str, end: str) -> list[dict]:
    """Split- AND dividend-adjusted OHLCV.

    Adjusted OHLC (not just adjusted close) is non-negotiable for a strategy
    with stops and breakout pivots: mixing raw highs with an adjusted close
    fabricates gaps at every historical split and silently invents trades.
    """
    rows = _get(f"{_BASE_STABLE}/historical-price-eod/dividend-adjusted",
                {"symbol": symbol, "from": start, "to": end})
    return rows if isinstance(rows, list) else []


def eod_raw(symbol: str, start: str, end: str) -> list[dict]:
    """Unadjusted OHLC + adjClose. Fallback when the adjusted endpoint is
    restricted on the account's plan."""
    payload = _get(f"{_BASE_V3}/historical-price-full/{symbol}", {"from": start, "to": end})
    if isinstance(payload, dict):
        return payload.get("historical", []) or []
    return []


# ------------------------------------------------------------- universes ---
def exchange_symbols(exchange: str) -> list[dict]:
    return _get(f"{_BASE_STABLE}/company-screener",
                {"exchange": exchange, "isEtf": "false", "isFund": "false",
                 "isActivelyTrading": "true", "limit": 10000}) or []


def sp500_constituents() -> list[dict]:
    return _get(f"{_BASE_V3}/sp500_constituent") or []


def delisted_companies(max_pages: int = 60) -> list[dict]:
    """Names that stopped trading. Including them is the cheapest available
    correction for survivorship bias — without them, every backtest is run on a
    universe pre-selected for having survived."""
    out: list[dict] = []
    for page in range(max_pages):
        try:
            rows = _get(f"{_BASE_STABLE}/delisted-companies", {"page": page, "limit": 100})
        except FMPError as exc:
            # Lower FMP tiers cap this feed at page 0. Take what we can get and
            # let the caller report the shortfall rather than pretending the
            # universe is survivorship-corrected.
            if page == 0:
                raise
            log.info("delisted feed truncated at page %d: %s", page, exc)
            break
        if not rows:
            break
        out.extend(rows)
        if len(rows) < 100:
            break
    return out


def profiles(symbols: list[str], chunk: int = 100) -> list[dict]:
    out: list[dict] = []
    for i in range(0, len(symbols), chunk):
        batch = ",".join(symbols[i:i + chunk])
        rows = _get(f"{_BASE_V3}/profile/{batch}")
        if isinstance(rows, list):
            out.extend(rows)
    return out


# ---------------------------------------------------------- fundamentals ---
def income_statement_quarterly(symbol: str, limit: int = 40) -> list[dict]:
    return _get(f"{_BASE_V3}/income-statement/{symbol}",
                {"period": "quarter", "limit": limit}) or []


def earnings_calendar_history(symbol: str) -> list[dict]:
    """Historical earnings ANNOUNCEMENT dates.

    Distinct from the 10-Q filing date: the press release moves the stock and
    comes first. Blacking out around the filing instead would mask the wrong
    window entirely.
    """
    return _get(f"{_BASE_V3}/historical/earning_calendar/{symbol}") or []


def earnings_surprises(symbol: str) -> list[dict]:
    return _get(f"{_BASE_V3}/earnings-surprises/{symbol}") or []
