"""
Prices for the arena — the only place the engine talks to FMP.

Two different prices matter and they must not be confused:

  - ``session_opens(date)``  — what a pending order FILLS at. An agent decides
    after Monday's close on Monday's information; it fills at Tuesday's open.
    Using Monday's close as the fill would hand every agent a free overnight
    gap, which is the single easiest way to fake a backtest.

  - ``session_closes(date)`` — what open positions are MARKED at, and what the
    NAV curve is built from.

Both read the daily bar (``historical-price-full``) rather than the live quote,
so a re-run of a past session produces the same numbers as the original run.
``latest_prices`` is the one exception — it is the intraday convenience used
for an agent's read-only view of its own book, never for accounting.
"""

from __future__ import annotations

import logging
import threading
from datetime import date, timedelta
from typing import Optional

from services.screener.fmp import fmp as FMPClient

log = logging.getLogger(__name__)

#: Cover long weekends / holidays when hunting for the nearest prior session.
_LOOKBACK_DAYS = 12


class PriceBook:
    """Bar cache for one run. One FMP call per ticker, reused by every pass."""

    def __init__(self, client: Optional[FMPClient] = None) -> None:
        self._client = client or FMPClient()
        # ticker -> {iso_date: {"open":…, "close":…, "high":…, "low":…, "volume":…}}
        self._bars: dict[str, dict[str, dict]] = {}
        # ticker -> (start, end) actually fetched, so a later request for a
        # window this book does not hold triggers a refetch instead of a silent
        # miss. Caching on ticker alone is correct for a live run (one process,
        # one session) and quietly wrong for a replay: a name first loaded for
        # June would then be unpriceable in August, and every order in it would
        # be rejected as "no recent price available".
        self._ranges: dict[str, tuple[date, date]] = {}
        # Agents run concurrently and each may warm a ticker from its own worker
        # thread (place_order -> _warm -> load). Without this, two agents asking
        # for the same name at the same moment both fetch it, and a widening
        # load can interleave with a read that then sees bars whose range entry
        # does not match. One lock around the fetch is cheap: the work is I/O
        # and the cache hit path is a dict lookup.
        self._lock = threading.Lock()

    # ── loading ─────────────────────────────────────────────────────────────

    def load(self, tickers: list[str], start: date, end: date) -> None:
        """Warm the cache for ``tickers`` over [start, end].

        Widens an existing entry rather than skipping it when the requested
        window falls outside what was already fetched.
        """
        want = sorted({(t or "").upper().strip() for t in tickers if t})
        for ticker in want:
            # Fast path outside the lock — an already-covered ticker is the
            # common case and must not serialise every agent behind one mutex.
            have = self._ranges.get(ticker)
            if have and have[0] <= start and end <= have[1]:
                continue
            with self._lock:
                have = self._ranges.get(ticker)
                if have and have[0] <= start and end <= have[1]:
                    continue
                lo = min(start, have[0]) if have else start
                hi = max(end, have[1]) if have else end
                bars = self._fetch(ticker, lo, hi)
                if bars or not have:
                    self._bars[ticker] = bars
                    self._ranges[ticker] = (lo, hi)

    def _fetch(self, ticker: str, start: date, end: date) -> dict[str, dict]:
        try:
            chart = self._client.daily_chart(ticker, start.isoformat(), end.isoformat())
        except Exception as exc:  # network / plan / delisted — absent, not fatal
            log.warning("arena: daily_chart failed for %s: %s", ticker, exc)
            return {}
        if chart is None or chart.empty or "date" not in chart.columns:
            return {}

        out: dict[str, dict] = {}
        for _, row in chart.iterrows():
            try:
                iso = row["date"].date().isoformat()
            except AttributeError:
                iso = str(row["date"])[:10]
            bar = {}
            for field in ("open", "close", "high", "low", "volume"):
                if field in chart.columns:
                    try:
                        bar[field] = float(row[field])
                    except (TypeError, ValueError):
                        bar[field] = None
            if bar.get("close"):
                out[iso] = bar
        return out

    # ── reads ───────────────────────────────────────────────────────────────

    def bar(self, ticker: str, on: date) -> Optional[dict]:
        return self._bars.get(ticker.upper().strip(), {}).get(on.isoformat())

    def open_price(self, ticker: str, on: date) -> Optional[float]:
        """The session open on ``on``. None if the ticker did not trade."""
        bar = self.bar(ticker, on)
        if not bar:
            return None
        # A few FMP rows carry a close but a zero/absent open; the close is the
        # honest fallback and is still same-session, so it cannot leak forward.
        return bar.get("open") or bar.get("close")

    def close_price(self, ticker: str, on: date) -> Optional[float]:
        bar = self.bar(ticker, on)
        return bar.get("close") if bar else None

    def last_close_on_or_before(self, ticker: str, on: date) -> tuple[Optional[float], Optional[date]]:
        """Nearest session close at or before ``on`` — weekends and holidays.

        Returns (price, session_date) so a caller can tell a stale mark from a
        fresh one instead of silently treating Friday's close as Monday's.
        """
        key = ticker.upper().strip()
        bars = self._bars.get(key, {})
        for back in range(_LOOKBACK_DAYS + 1):
            day = on - timedelta(days=back)
            bar = bars.get(day.isoformat())
            if bar and bar.get("close"):
                return float(bar["close"]), day
        return None, None

    def has(self, ticker: str) -> bool:
        return bool(self._bars.get(ticker.upper().strip()))

    def covers(self, ticker: str, on: date) -> bool:
        """Whether this book was actually loaded over a window containing ``on``."""
        rng = self._ranges.get(ticker.upper().strip())
        return bool(rng and rng[0] <= on <= rng[1])


def latest_prices(tickers: list[str], client: Optional[FMPClient] = None) -> dict[str, float]:
    """Intraday quotes, batched. Read-only convenience — never used to book a
    fill or write a NAV row (both of those must be reproducible)."""
    symbols = sorted({(t or "").upper().strip() for t in tickers if t})
    if not symbols:
        return {}
    fmp_client = client or FMPClient()
    out: dict[str, float] = {}
    for i in range(0, len(symbols), 200):
        chunk = symbols[i : i + 200]
        try:
            df = fmp_client.quote_price(chunk)
        except Exception as exc:
            log.warning("arena: quote_price failed for %d symbols: %s", len(chunk), exc)
            continue
        if df is None or df.empty or "symbol" not in df.columns or "price" not in df.columns:
            continue
        for _, r in df.iterrows():
            try:
                out[str(r["symbol"]).upper().strip()] = float(r["price"])
            except (TypeError, ValueError):
                continue
    return out
