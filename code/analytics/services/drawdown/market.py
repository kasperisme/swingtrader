"""Trend, volatility, beta and liquidity per name — the tape the stress test cannot see.

Council round 3 (swing trader, risk manager): a valuation-gap list with no trend
input is early on both sides, and a book graded against SPY without beta
measures the rebound, not the stress test. Everything here is computed from
one year of FMP daily OHLC; the market-analyst agent reads it, and picks.py
uses beta and ADV to size and constrain the book.
"""

from __future__ import annotations

import math
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

from .snapshots import FMP_BASE, _fmp_key, _get


def _bars(sym: str, key: str, since: date) -> list[dict]:
    try:
        b = _get(f"{FMP_BASE}/historical-price-eod/full", {"symbol": sym, "from": since.isoformat(), "apikey": key}).json()
    except Exception:  # noqa: BLE001
        return []
    rows = b if isinstance(b, list) else (b or {}).get("historical", []) if isinstance(b, dict) else []
    return sorted((r for r in rows if r.get("close")), key=lambda r: r["date"])


def _rets(closes: list[float]) -> list[float]:
    return [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes))]


def _beta(a: dict[str, float], m: dict[str, float]) -> float | None:
    days = sorted(set(a) & set(m))
    if len(days) < 60:
        return None
    x = [m[d] for d in days]
    y = [a[d] for d in days]
    mx, my = sum(x) / len(x), sum(y) / len(y)
    var = sum((v - mx) ** 2 for v in x)
    return sum((u - mx) * (v - my) for u, v in zip(x, y)) / var if var else None


def _ret_by_day(bars: list[dict]) -> dict[str, float]:
    return {bars[i]["date"]: bars[i]["close"] / bars[i - 1]["close"] - 1 for i in range(1, len(bars))}


def block(bars: list[dict], spy: dict[str, float], qqq: dict[str, float]) -> dict:
    if len(bars) < 30:
        return {"error": "under 30 sessions of history"}
    c = [float(b["close"]) for b in bars]
    px = c[-1]

    def ret(n):
        return c[-1] / c[-1 - n] - 1 if len(c) > n else None

    def sma(n, end=None):
        xs = c[: end] if end else c
        return sum(xs[-n:]) / n if len(xs) >= n else None

    trs = []
    for i in range(1, len(bars)):
        h, lo, pc = float(bars[i].get("high") or c[i]), float(bars[i].get("low") or c[i]), c[i - 1]
        trs.append(max(h - lo, abs(h - pc), abs(lo - pc)))
    r = _rets(c)

    def vol(n):
        xs = r[-n:]
        if len(xs) < n:
            return None
        m = sum(xs) / n
        return math.sqrt(sum((v - m) ** 2 for v in xs) / (n - 1)) * math.sqrt(252)

    s50, s200, s50_prev = sma(50), sma(200), sma(50, -10)
    dv = [float(b["close"]) * float(b.get("volume") or 0) for b in bars[-20:]]
    own = _ret_by_day(bars)
    mom = (c[-22] / c[-253] - 1) if len(c) > 253 else None
    low20, high20 = min(c[-20:]), max(c[-20:])
    return {
        "price": px, "date": bars[-1]["date"],
        "ret_1m": ret(21), "ret_3m": ret(63), "ret_6m": ret(126), "mom_12_1": mom,
        "vs_20dma": px / sma(20) - 1 if sma(20) else None,
        "vs_50dma": px / s50 - 1 if s50 else None, "vs_200dma": px / s200 - 1 if s200 else None,
        "sma50_slope_10d": (s50 / s50_prev - 1) if s50 and s50_prev else None,
        "atr20_pct": (sum(trs[-20:]) / 20) / px if len(trs) >= 20 else None,
        "vol_20d": vol(20), "vol_60d": vol(60),
        "beta_spy_1y": _beta(own, spy), "beta_qqq_1y": _beta(own, qqq),
        "adv20_usd": sum(dv) / len(dv) if dv else None,
        "range_20d": {"low": low20, "high": high20},
        "trend": ("down" if s50 and s200 and px < s50 < s200 else "up" if s50 and s200 and px > s50 > s200 else "mixed"),
    }


def blocks(symbols: list[str], workers: int = 6, today: date | None = None) -> dict[str, dict]:
    key = _fmp_key()
    since = (today or date.today()) - timedelta(days=400)
    spy, qqq = (_ret_by_day(_bars(s, key, since)) for s in ("SPY", "QQQ"))
    with ThreadPoolExecutor(workers) as ex:
        got = dict(zip(symbols, ex.map(lambda s: _bars(s, key, since), symbols)))
    return {s: block(b, spy, qqq) for s, b in got.items()}
