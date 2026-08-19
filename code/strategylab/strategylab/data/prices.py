"""Price store and the aligned panel the backtester runs on.

Two jobs:
  1. Fetch split/dividend-adjusted OHLCV once, cache it on disk, never again.
  2. Assemble a set of symbols into date-aligned numpy matrices — the panel —
     because the whole simulation is written against matrices, not DataFrames.

Alignment matters more than it looks. Every matrix shares one date index, so
`row t` means the same calendar session for every symbol, and a NaN means "this
name did not trade that day" rather than "the series is offset by one". That
single property is what makes the look-ahead audit in `backtest.py` tractable.
"""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from ..config import price_cache_dir
from . import fmp

log = logging.getLogger(__name__)

_COLUMNS = ["open", "high", "low", "close", "volume"]


@dataclass
class Panel:
    """Date-aligned OHLCV matrices, shape (n_days, n_symbols)."""

    dates: np.ndarray          # datetime64[D]
    symbols: list[str]
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray

    @property
    def shape(self) -> tuple[int, int]:
        return self.close.shape

    def index_of(self, symbol: str) -> int:
        return self.symbols.index(symbol)

    def date_index(self, day) -> int:
        """First row on or after `day`."""
        d = np.datetime64(pd.Timestamp(day).date())
        return int(np.searchsorted(self.dates, d, side="left"))

    def slice_dates(self, start, end) -> "Panel":
        i = self.date_index(start)
        j = self.date_index(end)
        j = min(len(self.dates), j + 1)
        return Panel(self.dates[i:j], list(self.symbols), self.open[i:j], self.high[i:j],
                     self.low[i:j], self.close[i:j], self.volume[i:j])

    def subset(self, symbols: list[str]) -> "Panel":
        keep = [i for i, s in enumerate(self.symbols) if s in set(symbols)]
        idx = np.array(keep, dtype=int)
        return Panel(self.dates, [self.symbols[i] for i in keep], self.open[:, idx],
                     self.high[:, idx], self.low[:, idx], self.close[:, idx],
                     self.volume[:, idx])


class PriceStore:
    """Disk-cached adjusted daily bars."""

    def __init__(self, cache_dir: Path | None = None):
        self.dir = Path(cache_dir or price_cache_dir())
        self.dir.mkdir(parents=True, exist_ok=True)

    # ---------------------------------------------------------- paths ----
    def _path(self, symbol: str) -> Path:
        safe = symbol.replace("/", "_").replace(".", "-")
        return self.dir / f"{safe}.csv.gz"

    def _meta_path(self, symbol: str) -> Path:
        safe = symbol.replace("/", "_").replace(".", "-")
        return self.dir / f"{safe}.meta.json"

    def cached_symbols(self) -> list[str]:
        return sorted(p.name[: -len(".csv.gz")].replace("-", ".")
                      for p in self.dir.glob("*.csv.gz"))

    # ---------------------------------------------------------- fetch ----
    # FMP's dividend-adjusted endpoint returns at most this many rows and gives
    # no indication that it truncated — a request for 1995-2026 comes back
    # starting in 2006, looking like the symbol simply has no earlier history.
    ADJUSTED_ROW_CAP = 5000

    def fetch(self, symbol: str, start: str, end: str) -> pd.DataFrame:
        """Adjusted bars from FMP.

        Two sources, and the choice between them matters:

        * `stable/historical-price-eod/dividend-adjusted` gives vendor-adjusted
          OHLC but silently truncates at 5000 rows (~20 years).
        * `v3/historical-price-full` reaches back to 1995 but returns raw OHLC
          plus an adjusted close, so OHLC has to be scaled by the
          close/adjClose factor here.

        For a window that fits under the cap the vendor series is preferred. For
        a longer one the v3 series is used for the WHOLE range rather than
        stitching the two: splicing series adjusted by different methods puts a
        discontinuity in the middle of the panel, which a momentum strategy
        would happily trade.
        """
        span_days = (pd.Timestamp(end) - pd.Timestamp(start)).days
        want_deep = span_days > int(self.ADJUSTED_ROW_CAP * 1.45)   # ~trading days

        rows = []
        if not want_deep:
            try:
                rows = fmp.eod_adjusted(symbol, start, end)
                if len(rows) >= self.ADJUSTED_ROW_CAP:
                    rows = []          # hit the cap — fall through to the deep source
            except fmp.FMPError as exc:
                log.debug("%s adjusted endpoint unavailable (%s), falling back", symbol, exc)
        if rows:
            df = pd.DataFrame(rows)
            ren = {"adjOpen": "open", "adjHigh": "high", "adjLow": "low", "adjClose": "close"}
            df = df.rename(columns=ren)
        else:
            raw = fmp.eod_raw(symbol, start, end)
            if not raw:
                return pd.DataFrame(columns=["date"] + _COLUMNS)
            df = pd.DataFrame(raw)
            if "adjClose" in df.columns and "close" in df.columns:
                factor = pd.to_numeric(df["adjClose"], errors="coerce") / \
                    pd.to_numeric(df["close"], errors="coerce").replace(0, np.nan)
                for col in ("open", "high", "low"):
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col], errors="coerce") * factor
                df["close"] = pd.to_numeric(df["adjClose"], errors="coerce")

        missing = [c for c in _COLUMNS if c not in df.columns]
        if missing or "date" not in df.columns:
            return pd.DataFrame(columns=["date"] + _COLUMNS)

        df = df[["date"] + _COLUMNS].copy()
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        for c in _COLUMNS:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        df = (df.dropna(subset=["date", "close"])
                .drop_duplicates(subset=["date"])
                .sort_values("date")
                .reset_index(drop=True))
        # Zero/negative prices are data errors, not information.
        df = df[(df[["open", "high", "low", "close"]] > 0).all(axis=1)].reset_index(drop=True)
        return df

    # ----------------------------------------------------------- cache ----
    def load(self, symbol: str) -> pd.DataFrame | None:
        p = self._path(symbol)
        if not p.exists():
            return None
        try:
            df = pd.read_csv(p, parse_dates=["date"])
        except Exception:
            return None
        return df if len(df) else None

    def save(self, symbol: str, df: pd.DataFrame, start: str, end: str) -> None:
        df.to_csv(self._path(symbol), index=False, compression="gzip")
        self._meta_path(symbol).write_text(json.dumps({
            "symbol": symbol, "rows": int(len(df)),
            "requested_from": start, "requested_to": end,
            "first": str(df["date"].iloc[0].date()) if len(df) else None,
            "last": str(df["date"].iloc[-1].date()) if len(df) else None,
        }))

    def covers(self, symbol: str, start: str, end: str) -> bool:
        """Cached range is sufficient. `end` is satisfied loosely: a delisted
        name legitimately has no bars near the end of the window."""
        mp = self._meta_path(symbol)
        if not mp.exists():
            return False
        try:
            meta = json.loads(mp.read_text())
        except Exception:
            return False
        return (meta.get("requested_from", "9999") <= start
                and meta.get("requested_to", "0000") >= end)

    # ----------------------------------------------------------- sync ----
    def sync(self, symbols: list[str], start: str, end: str, workers: int = 8,
             force: bool = False, progress_every: int = 100) -> dict:
        """Download anything missing. Idempotent and safe to interrupt."""
        todo = [s for s in symbols if force or not self.covers(s, start, end)]
        stats = {"requested": len(symbols), "fetched": 0, "skipped": len(symbols) - len(todo),
                 "empty": 0, "errors": 0}
        if not todo:
            return stats

        def one(sym: str):
            try:
                df = self.fetch(sym, start, end)
                self.save(sym, df, start, end)
                return sym, len(df), None
            except Exception as exc:
                return sym, 0, exc

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(one, s) for s in todo]
            for n, fut in enumerate(as_completed(futures), 1):
                sym, rows, err = fut.result()
                if err is not None:
                    stats["errors"] += 1
                    log.debug("sync %s failed: %s", sym, err)
                elif rows == 0:
                    stats["empty"] += 1
                else:
                    stats["fetched"] += 1
                if progress_every and n % progress_every == 0:
                    log.info("price sync %d/%d", n, len(todo))
        return stats

    # ----------------------------------------------------------- panel ----
    def build_panel(self, symbols: list[str], start: str, end: str,
                    min_rows: int = 60) -> Panel:
        """Assemble the aligned matrices.

        The date index is the union of all sessions seen across the symbols
        (so a name that stops trading simply goes NaN from that day on, rather
        than shifting later names' rows).
        """
        frames: dict[str, pd.DataFrame] = {}
        lo, hi = pd.Timestamp(start), pd.Timestamp(end)
        for s in symbols:
            df = self.load(s)
            if df is None:
                continue
            df = df[(df["date"] >= lo) & (df["date"] <= hi)]
            if len(df) < min_rows:
                continue
            frames[s] = df.set_index("date")

        if not frames:
            raise RuntimeError(
                "No cached price history for the requested symbols/window — "
                "run `strategylab data sync` first."
            )

        idx = pd.DatetimeIndex(sorted(set().union(*(f.index for f in frames.values()))))
        syms = sorted(frames)
        n, m = len(idx), len(syms)
        mats = {c: np.full((n, m), np.nan, dtype=np.float64) for c in _COLUMNS}
        for j, s in enumerate(syms):
            f = frames[s].reindex(idx)
            for c in _COLUMNS:
                mats[c][:, j] = f[c].to_numpy(dtype=np.float64)

        return Panel(dates=idx.values.astype("datetime64[D]"), symbols=syms,
                     open=mats["open"], high=mats["high"], low=mats["low"],
                     close=mats["close"], volume=mats["volume"])
