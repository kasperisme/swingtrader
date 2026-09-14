"""A local per-ticker store of FMP daily bars, topped up with only the days it
is missing.

Why: ``/v3/historical-price-full`` was ~89% of the FMP plan's 30-day BANDWIDTH
cap (15.2 of ~17 GB, 2026-09), and the plan ran out. Every daily board asked for
the full window again on every run — stage_2 a year of bars for ~2,100
candidates, nis_short THREE years for ~1,200 — though all but the last bar were
identical to yesterday's answer. A year of bars is ~60 KB; the days since the
last run are a few hundred bytes.

What a ticker's file remembers (``<dir>/<TICKER>.pkl``):

    bars        every bar fetched, one row per date, FMP's columns unchanged
    lo          first date the store is complete from (the earliest start asked
                for — a ticker that listed later simply has no rows before it)
    hi          last date the store is AUTHORITATIVE through: the last session
                that was already over when it was fetched
    through     last date fetched at all — past ``hi`` the bars are provisional
                (today's candle, still moving, or a bar FMP has not finalised)
    fetched_at  when ``through`` was fetched

A request for [start, end] is served from disk when [start, min(end, today)] is
inside [lo, hi], or inside [lo, through] and the provisional tail is under
``PROVISIONAL_TTL`` old (so boards that start together share one fetch). Anything
else fetches only the missing head and/or tail — each overlapping the stored
bars by ``OVERLAP_DAYS`` — and merges it in. Coverage only ever grows
contiguously, so ``[lo, hi]`` never has holes.

The overlap is also the split detector. FMP back-adjusts OHLC for splits, so
after a 2:1 split every stored close is double what FMP now says for the same
date. Any overlapping settled close more than ``MISMATCH`` apart means the
history was re-based: the ticker's file is dropped and the request refetched
whole. (Dividends move ``adjClose`` only, which nothing reads.)

Failure semantics match the uncached client: an FMP error raises, and so does an
empty answer where the store HAS bars — that is FMP failing, not the ticker
having no history, and serving the stale store as if current would hide it.

    FMP_BAR_CACHE=0        bypass entirely (every call fetches, as before)
    FMP_BAR_CACHE_DIR=...  move the store (default code/analytics/.cache/fmp_bars)

Files are written to a temp name and ``os.replace``d, so concurrent boards can
share the store: the worst case is two processes fetching the same tail.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional
from zoneinfo import ZoneInfo

import pandas as pd

from shared.logging import logger

_VERSION = 1
_ET = ZoneInfo("America/New_York")
_DEFAULT_DIR = Path(__file__).resolve().parents[2] / ".cache" / "fmp_bars"

# A session's bar is treated as final once the ET clock passes this hour.
# Conservative on purpose: FMP publishes the EOD bar some time after the 16:00
# close, and trusting a still-moving bar forever is the one unrecoverable error.
SETTLE_HOUR_ET = 20
OVERLAP_DAYS = 10            # calendar days; ≥5 sessions to compare outside holidays
MISMATCH = 0.01              # relative close difference that means "re-based history"
PROVISIONAL_TTL = timedelta(minutes=10)

Fetch = Callable[[str, str, str], pd.DataFrame]


def _as_date(value) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return pd.Timestamp(value).date()


def _settled_through(at: datetime) -> date:
    et = at.astimezone(_ET)
    return et.date() if et.hour >= SETTLE_HOUR_ET else et.date() - timedelta(days=1)


def _between(bars: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
    if bars.empty:
        return bars
    mask = (bars["date"] >= pd.Timestamp(start)) & (bars["date"] <= pd.Timestamp(end))
    return bars.loc[mask]


def _normalise(bars: pd.DataFrame) -> pd.DataFrame:
    if bars is None or bars.empty or "date" not in bars.columns:
        return pd.DataFrame()
    bars = bars.copy()
    bars["date"] = pd.to_datetime(bars["date"])
    return bars.drop_duplicates("date", keep="last").sort_values("date").reset_index(drop=True)


def _consistent(stored: pd.DataFrame, fresh: pd.DataFrame, start: date, end: date) -> bool:
    """Whether stored and fresh closes agree on every settled date both hold in
    [start, end]. Nothing in common is agreement — there is nothing to contradict."""
    if stored.empty or fresh.empty or "close" not in stored or "close" not in fresh:
        return True
    a = _between(stored, start, end).set_index("date")["close"].astype(float)
    b = fresh.set_index("date")["close"].astype(float)
    common = a.index.intersection(b.index)
    if common.empty:
        return True
    rel = (a[common] - b[common]).abs() / b[common].abs().clip(lower=1e-9)
    return bool((rel <= MISMATCH).all())


@dataclass
class _Entry:
    bars: pd.DataFrame
    lo: date
    hi: date
    through: date
    fetched_at: datetime


class BarCache:
    def __init__(
        self,
        fetch: Fetch,
        directory: Optional[Path] = None,
        *,
        now: Optional[Callable[[], datetime]] = None,
    ):
        self._fetch_raw = fetch
        self._dir = Path(directory or os.environ.get("FMP_BAR_CACHE_DIR") or _DEFAULT_DIR)
        self._now = now or (lambda: datetime.now(timezone.utc))
        self.enabled = os.environ.get("FMP_BAR_CACHE", "1").lower() not in ("0", "false", "off", "no")

    # ── public ───────────────────────────────────────────────────────────────

    def get(self, ticker: str, start, end) -> pd.DataFrame:
        """Bars for [start, end], ascending, ``date`` as datetime64. Empty when
        the ticker has none in the window."""
        start, end = _as_date(start), _as_date(end)
        if not self.enabled:
            return self._window(self._fetch(ticker, start, end), start, end)

        now = self._now()
        want_end = min(end, now.astimezone(_ET).date())
        if want_end < start:
            return pd.DataFrame()

        entry = self._load(ticker)
        if entry is None:
            return self._refetch(ticker, start, want_end, end, now)

        covered_end = entry.through if now - entry.fetched_at < PROVISIONAL_TTL else entry.hi
        if start >= entry.lo and want_end <= covered_end:
            return self._window(entry.bars, start, end)

        if start < entry.lo:
            head_to = entry.lo + timedelta(days=OVERLAP_DAYS)
            head = self._fetch(ticker, start, head_to)
            if not self._merge(ticker, entry, head, start, head_to):
                return self._refetch(ticker, start, want_end, end, now)
            entry.lo = start

        if want_end > covered_end:
            tail_from = entry.hi - timedelta(days=OVERLAP_DAYS)
            tail = self._fetch(ticker, tail_from, want_end)
            if not self._merge(ticker, entry, tail, tail_from, want_end):
                return self._refetch(ticker, start, want_end, end, now)
            entry.hi = max(entry.hi, min(want_end, _settled_through(now)))
            entry.through = want_end
            entry.fetched_at = now

        self._save(ticker, entry)
        return self._window(entry.bars, start, end)

    # ── internals ────────────────────────────────────────────────────────────

    def _fetch(self, ticker: str, start: date, end: date) -> pd.DataFrame:
        return _normalise(self._fetch_raw(ticker, start.isoformat(), end.isoformat()))

    def _refetch(self, ticker: str, start: date, want_end: date, end: date, now: datetime) -> pd.DataFrame:
        """Fetch the request whole and make it the ticker's store."""
        bars = self._fetch(ticker, start, want_end)
        if not bars.empty:
            self._save(ticker, _Entry(bars, start, min(want_end, _settled_through(now)), want_end, now))
        return self._window(bars, start, end)

    def _merge(self, ticker: str, entry: _Entry, fresh: pd.DataFrame, start: date, end: date) -> bool:
        """Fold a fetched segment into ``entry``. False when it contradicts the
        settled bars already stored (a split re-based the history)."""
        if fresh.empty:
            if not _between(entry.bars, start, min(end, entry.hi)).empty:
                raise RuntimeError(
                    f"FMP returned no bars for {ticker} {start}..{end}, where the bar cache has them"
                )
            return True  # legitimately nothing there (not yet listed)
        if not _consistent(entry.bars, fresh, start, min(end, entry.hi)):
            logger.info("bar cache: %s history re-based (split?) — refetching the window whole", ticker)
            self._drop(ticker)
            return False
        keep = entry.bars.loc[~entry.bars["date"].between(pd.Timestamp(start), pd.Timestamp(end))]
        entry.bars = _normalise(pd.concat([keep, fresh], ignore_index=True))
        return True

    @staticmethod
    def _window(bars: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
        return _between(bars, start, end).reset_index(drop=True).copy()

    def _path(self, ticker: str) -> Path:
        return self._dir / f"{re.sub(r'[^A-Z0-9.^=_-]', '_', ticker.upper())}.pkl"

    def _load(self, ticker: str) -> Optional[_Entry]:
        path = self._path(ticker)
        if not path.exists():
            return None
        try:
            raw = pd.read_pickle(path)
            if raw.get("version") != _VERSION:
                return None
            return _Entry(raw["bars"], raw["lo"], raw["hi"], raw["through"], raw["fetched_at"])
        except Exception as exc:
            logger.warning("bar cache: unreadable %s (%s) — refetching", path.name, exc)
            return None

    def _save(self, ticker: str, entry: _Entry) -> None:
        path = self._path(ticker)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(f".{os.getpid()}.{id(entry)}.tmp")
            pd.to_pickle(
                {"version": _VERSION, "bars": entry.bars, "lo": entry.lo, "hi": entry.hi,
                 "through": entry.through, "fetched_at": entry.fetched_at},
                tmp,
            )
            os.replace(tmp, path)
        except Exception as exc:  # a store that can't write is a slower client, not a broken one
            logger.warning("bar cache: could not write %s: %s", path.name, exc)

    def _drop(self, ticker: str) -> None:
        try:
            self._path(ticker).unlink(missing_ok=True)
        except OSError:
            pass
