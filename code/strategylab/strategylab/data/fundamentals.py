"""Point-in-time growth fundamentals.

The trap this module exists to avoid: quarterly financials are indexed by the
*period end* date, but they are not knowable until the filing is accepted —
typically 4–8 weeks later. Joining on period end lets a backtest buy a stock in
January on numbers published in March. That single mistake can turn a mediocre
screen into a spectacular one, and it is invisible in the equity curve.

So every metric here carries a `knowledge_date` (the accepted/filing date, with
a conservative 2-day settle) and is only ever forward-filled from that day on.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from ..config import fundamentals_cache_dir
from . import fmp

log = logging.getLogger(__name__)

_SETTLE_DAYS = 2       # filings land after the close; do not act the same day
_FALLBACK_LAG_DAYS = 45  # if no filing date is given, assume the slowest plausible lag


class FundamentalsStore:
    """Per-symbol PIT fundamental series, cached to disk."""

    def __init__(self, cache_dir: Path | None = None):
        self.dir = Path(cache_dir or fundamentals_cache_dir())
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, symbol: str) -> Path:
        return self.dir / f"{symbol.replace('/', '_').replace('.', '-')}.json"

    # ------------------------------------------------------------ fetch --
    def fetch(self, symbol: str) -> dict:
        rows = fmp.income_statement_quarterly(symbol, limit=44)
        surprises = []
        try:
            surprises = fmp.earnings_surprises(symbol)
        except Exception:
            pass
        return {"income": rows, "surprises": surprises}

    def ensure(self, symbols: list[str], workers: int = 6, force: bool = False) -> dict:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        todo = [s for s in symbols if force or not self._path(s).exists()]
        stats = {"requested": len(symbols), "fetched": 0, "errors": 0,
                 "skipped": len(symbols) - len(todo)}
        if not todo:
            return stats

        def one(sym: str):
            try:
                self._path(sym).write_text(json.dumps(self.fetch(sym)))
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

    # -------------------------------------------------------- PIT series --
    def series(self, symbol: str) -> pd.DataFrame | None:
        """Returns knowledge_date-indexed eps_yoy / rev_yoy / beat_streak."""
        p = self._path(symbol)
        if not p.exists():
            return None
        try:
            payload = json.loads(p.read_text())
        except Exception:
            return None

        inc = payload.get("income") or []
        if len(inc) < 6:
            return None

        df = pd.DataFrame(inc)
        for col in ("date", "fillingDate", "acceptedDate"):
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors="coerce")
        if "date" not in df.columns:
            return None
        df = df.sort_values("date").reset_index(drop=True)

        known = df.get("acceptedDate")
        if known is None or known.isna().all():
            known = df.get("fillingDate")
        if known is None or known.isna().all():
            known = df["date"] + pd.Timedelta(days=_FALLBACK_LAG_DAYS)
        else:
            known = known.fillna(df["date"] + pd.Timedelta(days=_FALLBACK_LAG_DAYS))
        df["knowledge_date"] = known + pd.Timedelta(days=_SETTLE_DAYS)
        # A filing can never be known before its own period ends.
        df["knowledge_date"] = df[["knowledge_date", "date"]].max(axis=1)

        eps = pd.to_numeric(df.get("epsdiluted", df.get("eps")), errors="coerce")
        rev = pd.to_numeric(df.get("revenue"), errors="coerce")
        # YoY on quarterly data = 4 periods back; sequential growth is dominated
        # by seasonality and is not the signal the gate is trying to express.
        df["eps_yoy"] = _yoy(eps, 4)
        df["rev_yoy"] = _yoy(rev, 4)

        beat = _beat_flags(payload.get("surprises") or [], df)
        df["beat_streak"] = beat

        out = df[["knowledge_date", "eps_yoy", "rev_yoy", "beat_streak"]].copy()
        out = out.dropna(subset=["knowledge_date"]).sort_values("knowledge_date")
        return out.reset_index(drop=True)

    def shares_outstanding(self, symbol: str) -> pd.DataFrame | None:
        """Filing-date-aligned diluted share count.

        FMP's historical shares-float endpoint only reaches back ~5 years on
        this plan, but quarterly income statements carry `weightedAverageShsOut`
        for a decade — and they carry a filing date, so the series is
        point-in-time by construction rather than by assumption.
        """
        p = self._path(symbol)
        if not p.exists():
            return None
        try:
            inc = (json.loads(p.read_text()).get("income") or [])
        except Exception:
            return None
        if len(inc) < 4:
            return None
        df = pd.DataFrame(inc)
        if "date" not in df.columns:
            return None
        for col in ("date", "fillingDate", "acceptedDate"):
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors="coerce")
        known = df.get("acceptedDate")
        if known is None or known.isna().all():
            known = df.get("fillingDate")
        if known is None or known.isna().all():
            known = df["date"] + pd.Timedelta(days=_FALLBACK_LAG_DAYS)
        else:
            known = known.fillna(df["date"] + pd.Timedelta(days=_FALLBACK_LAG_DAYS))
        df["knowledge_date"] = (known + pd.Timedelta(days=_SETTLE_DAYS)).dt.tz_localize(None)
        shares = pd.to_numeric(df.get("weightedAverageShsOutDil",
                                      df.get("weightedAverageShsOut")), errors="coerce")
        out = pd.DataFrame({"knowledge_date": df["knowledge_date"], "shares": shares})
        out = out.dropna().sort_values("knowledge_date")
        out = out[out["shares"] > 0]
        return out.reset_index(drop=True) if len(out) else None

    def align_shares(self, symbols: list[str], dates: np.ndarray) -> np.ndarray:
        """Forward-fill share counts onto the panel grid, PIT."""
        n, m = len(dates), len(symbols)
        out = np.full((n, m), np.nan)
        grid = pd.DatetimeIndex(dates)
        for j, sym in enumerate(symbols):
            s = self.shares_outstanding(sym)
            if s is None:
                continue
            pos = np.searchsorted(s["knowledge_date"].values, grid.values, side="right") - 1
            ok = pos >= 0
            if not ok.any():
                continue
            col = s["shares"].to_numpy(dtype=np.float64)
            vals = np.full(n, np.nan)
            vals[ok] = col[pos[ok]]
            out[:, j] = vals
        return out

    # ------------------------------------------------------- panel align --
    def align(self, symbols: list[str], dates: np.ndarray) -> dict[str, np.ndarray]:
        """Forward-fill each PIT series onto the panel's date grid.

        Returns matrices shaped (n_days, n_symbols); NaN = "not knowable yet",
        which the gate layer treats as failing (never as passing).
        """
        n, m = len(dates), len(symbols)
        out = {k: np.full((n, m), np.nan) for k in ("eps_yoy", "rev_yoy", "beat_streak")}
        grid = pd.DatetimeIndex(dates)
        for j, sym in enumerate(symbols):
            s = self.series(sym)
            if s is None or s.empty:
                continue
            # searchsorted on knowledge_date == strict PIT forward fill
            pos = np.searchsorted(s["knowledge_date"].values, grid.values, side="right") - 1
            valid = pos >= 0
            if not valid.any():
                continue
            for key in out:
                col = s[key].to_numpy(dtype=np.float64)
                vals = np.full(n, np.nan)
                vals[valid] = col[pos[valid]]
                out[key][:, j] = vals
        return out


def _yoy(series: pd.Series, lag: int) -> pd.Series:
    prev = series.shift(lag)
    # Growth off a negative or ~zero base is not a growth rate; leave it NaN
    # rather than emit a number the gate would misread as spectacular.
    denom = prev.where(prev > 0)
    return (series - prev) / denom.abs()


def _beat_flags(surprises: list[dict], inc: pd.DataFrame) -> pd.Series:
    """Consecutive EPS beats as of each filing, aligned on period end."""
    if not surprises:
        return pd.Series([np.nan] * len(inc))
    s = pd.DataFrame(surprises)
    if "date" not in s.columns:
        return pd.Series([np.nan] * len(inc))
    s["date"] = pd.to_datetime(s["date"], errors="coerce")
    act = pd.to_numeric(s.get("actualEarningResult"), errors="coerce")
    est = pd.to_numeric(s.get("estimatedEarning"), errors="coerce")
    s["beat"] = (act > est).astype(float).where(act.notna() & est.notna())
    s = s.dropna(subset=["date"]).sort_values("date")

    streaks, run = [], 0
    for b in s["beat"].tolist():
        run = run + 1 if b == 1.0 else 0
        streaks.append(run)
    s["streak"] = streaks

    pos = np.searchsorted(s["date"].values, inc["date"].values, side="right") - 1
    vals = np.full(len(inc), np.nan)
    ok = pos >= 0
    vals[ok] = s["streak"].to_numpy()[pos[ok]]
    return pd.Series(vals)
