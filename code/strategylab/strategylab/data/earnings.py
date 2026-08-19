"""Earnings announcement dates, cached.

Used for the universe's ±10-session blackout. Earnings volume swamps any flow
proxy — the release, not the filing, is what moves the stock, so the blackout
has to be anchored on the announcement date.
"""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

from ..config import CACHE_ROOT
from . import fmp

log = logging.getLogger(__name__)


class EarningsStore:
    def __init__(self, cache_dir: Path | None = None):
        self.dir = Path(cache_dir or (CACHE_ROOT / "earnings"))
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, symbol: str) -> Path:
        return self.dir / f"{symbol.replace('/', '_').replace('.', '-')}.json"

    def ensure(self, symbols: list[str], workers: int = 8, force: bool = False) -> dict:
        todo = [s for s in symbols if force or not self._path(s).exists()]
        stats = {"requested": len(symbols), "fetched": 0, "errors": 0,
                 "skipped": len(symbols) - len(todo)}
        if not todo:
            return stats

        def one(sym: str):
            try:
                rows = fmp.earnings_calendar_history(sym)
                dates = sorted({r["date"] for r in rows
                                if r.get("date") and r.get("eps") is not None})
                self._path(sym).write_text(json.dumps(dates))
                return None
            except Exception as exc:
                return exc

        with ThreadPoolExecutor(max_workers=workers) as pool:
            for fut in as_completed([pool.submit(one, s) for s in todo]):
                if fut.result() is None:
                    stats["fetched"] += 1
                else:
                    stats["errors"] += 1
        return stats

    def dates(self, symbol: str) -> list:
        p = self._path(symbol)
        if not p.exists():
            return []
        try:
            return [pd.Timestamp(d) for d in json.loads(p.read_text())]
        except Exception:
            return []

    def all_dates(self, symbols: list[str]) -> dict:
        return {s: self.dates(s) for s in symbols}
