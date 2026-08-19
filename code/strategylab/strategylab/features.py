"""Feature bank.

Every feature is a (n_days, n_symbols) matrix aligned to the panel, where row t
uses information available at the CLOSE of day t and nothing later. That is the
only invariant in this file, and everything downstream depends on it.

The bank is lazy and memoised. Base features (moving averages, ATR, 52-week
extremes, cross-sectional relative strength) are shared by every genome, so the
search pays for them once per data window rather than once per trial — which is
what makes a few hundred backtests affordable.
"""

from __future__ import annotations

from collections import OrderedDict

import numpy as np
import pandas as pd

from .data.prices import Panel

TRADING_DAYS = 252


def _df(mat: np.ndarray) -> pd.DataFrame:
    return pd.DataFrame(mat)


def _roll_mean(mat: np.ndarray, w: int, min_periods: int | None = None) -> np.ndarray:
    return _df(mat).rolling(w, min_periods=min_periods or w).mean().to_numpy()


def _roll_sum(mat: np.ndarray, w: int, min_periods: int | None = None) -> np.ndarray:
    return _df(mat).rolling(w, min_periods=min_periods or w).sum().to_numpy()


def _roll_max(mat: np.ndarray, w: int, min_periods: int | None = None) -> np.ndarray:
    return _df(mat).rolling(w, min_periods=min_periods or 2).max().to_numpy()


def _roll_min(mat: np.ndarray, w: int, min_periods: int | None = None) -> np.ndarray:
    return _df(mat).rolling(w, min_periods=min_periods or 2).min().to_numpy()


def _roll_median(mat: np.ndarray, w: int, min_periods: int | None = None) -> np.ndarray:
    return _df(mat).rolling(w, min_periods=min_periods or max(2, w // 2)).median().to_numpy()


def _roll_std(mat: np.ndarray, w: int) -> np.ndarray:
    return _df(mat).rolling(w, min_periods=max(3, w // 2)).std().to_numpy()


def _shift(mat: np.ndarray, k: int) -> np.ndarray:
    out = np.full_like(mat, np.nan)
    if k > 0:
        out[k:] = mat[:-k]
    elif k < 0:
        out[:k] = mat[-k:]
    else:
        out[:] = mat
    return out


class FeatureBank:
    """Lazily computes and caches feature matrices for one panel."""

    # Features every genome uses. They are computed once and never evicted;
    # everything else is LRU. Without a bound the cache grows without limit,
    # because genome-tunable lookbacks (stop MA length, pivot window, exit MA)
    # mint a new matrix per distinct value — a few hundred trials would hold
    # gigabytes of one-use arrays.
    PINNED = {"sma", "atr", "true_range", "atr_pct", "adr_pct", "rs_score", "rs_rank",
              "ret", "high_52w", "low_52w", "pct_above_52w_low", "pct_below_52w_high",
              "dollar_volume", "dollar_volume_20d", "avg_volume", "volume_ratio",
              "up_down_volume", "bars_available", "gap_pct", "tightness"}
    PINNED_SMA_LENGTHS = {20, 50, 150, 200}

    def __init__(self, panel: Panel, benchmark_close: np.ndarray | None = None,
                 max_cached: int = 80):
        self.panel = panel
        self.n, self.m = panel.close.shape
        self._cache: "OrderedDict[tuple, np.ndarray]" = OrderedDict()
        self._pinned: dict[tuple, np.ndarray] = {}
        self._bench = benchmark_close  # (n_days,) aligned to panel.dates
        self.extra: dict[str, np.ndarray] = {}   # fundamentals / news, injected
        self.max_cached = max_cached

    def _is_pinned(self, name: str, kw: dict) -> bool:
        if name == "sma":
            return kw.get("length") in self.PINNED_SMA_LENGTHS
        return name in self.PINNED and not kw

    # ------------------------------------------------------------ core ---
    def get(self, name: str, **kw) -> np.ndarray:
        key = (name, tuple(sorted(kw.items())))
        hit = self._pinned.get(key)
        if hit is not None:
            return hit
        hit = self._cache.get(key)
        if hit is not None:
            self._cache.move_to_end(key)
            return hit
        hit = getattr(self, f"_f_{name}")(**kw)
        if self._is_pinned(name, kw):
            self._pinned[key] = hit
        else:
            self._cache[key] = hit
            while len(self._cache) > self.max_cached:
                self._cache.popitem(last=False)
        return hit

    def clear(self) -> None:
        self._cache.clear()

    def memory_mb(self) -> float:
        total = sum(a.nbytes for a in self._cache.values())
        total += sum(a.nbytes for a in self._pinned.values())
        return total / 1e6

    # ------------------------------------------------------ price basics --
    def _f_sma(self, length: int) -> np.ndarray:
        return _roll_mean(self.panel.close, length)

    def _f_sma_rising(self, length: int, days: int) -> np.ndarray:
        sma = self.get("sma", length=length)
        return (sma > _shift(sma, days)).astype(np.float64)

    def _f_ret(self, days: int) -> np.ndarray:
        c = self.panel.close
        prev = _shift(c, days)
        return c / np.where(prev > 0, prev, np.nan) - 1.0

    def _f_true_range(self) -> np.ndarray:
        p = self.panel
        prev_close = _shift(p.close, 1)
        a = p.high - p.low
        b = np.abs(p.high - prev_close)
        c = np.abs(p.low - prev_close)
        return np.fmax(a, np.fmax(b, c))

    def _f_atr(self, length: int = 14) -> np.ndarray:
        return _roll_mean(self.get("true_range"), length, min_periods=max(3, length // 2))

    def _f_atr_pct(self, length: int = 14) -> np.ndarray:
        c = self.panel.close
        return self.get("atr", length=length) / np.where(c > 0, c, np.nan) * 100.0

    def _f_adr_pct(self, length: int = 20) -> np.ndarray:
        """Minervini's Average Daily Range %, the practical volatility screen."""
        p = self.panel
        mid = (p.high + p.low) / 2.0
        rng = (p.high - p.low) / np.where(mid > 0, mid, np.nan) * 100.0
        return _roll_mean(rng, length, min_periods=max(5, length // 2))

    def _f_realized_vol(self, length: int = 20) -> np.ndarray:
        r = self.get("ret", days=1)
        return _roll_std(r, length) * np.sqrt(TRADING_DAYS)

    # ------------------------------------------------ 52-week structure ---
    def _f_high_52w(self) -> np.ndarray:
        return _roll_max(self.panel.high, TRADING_DAYS, min_periods=60)

    def _f_low_52w(self) -> np.ndarray:
        return _roll_min(self.panel.low, TRADING_DAYS, min_periods=60)

    def _f_pct_above_52w_low(self) -> np.ndarray:
        lo = self.get("low_52w")
        return self.panel.close / np.where(lo > 0, lo, np.nan) - 1.0

    def _f_pct_below_52w_high(self) -> np.ndarray:
        hi = self.get("high_52w")
        return 1.0 - self.panel.close / np.where(hi > 0, hi, np.nan)

    def _f_pivot_high(self, lookback: int) -> np.ndarray:
        """Highest high of the PRIOR `lookback` bars.

        Excluding the current bar is the whole point: a pivot that includes
        today can never be broken by today, and a breakout rule written against
        an inclusive rolling max silently never fires (or fires on every bar,
        depending on the comparison) — a classic silent backtest bug.
        """
        return _shift(_roll_max(self.panel.high, lookback, min_periods=max(5, lookback // 3)), 1)

    def _f_pivot_low(self, lookback: int) -> np.ndarray:
        """Lowest low of the PRIOR `lookback` bars — the short-side mirror.

        Same exclusion of the current bar as `pivot_high`, and for the same
        reason: a pivot that includes today can never be broken by today.
        """
        return _shift(_roll_min(self.panel.low, lookback, min_periods=max(5, lookback // 3)), 1)

    # --------------------------------------------------------- volume -----
    def _f_dollar_volume(self) -> np.ndarray:
        return self.panel.close * self.panel.volume

    def _f_dollar_volume_20d(self) -> np.ndarray:
        return _roll_median(self.get("dollar_volume"), 20)

    def _f_avg_volume(self, length: int = 50) -> np.ndarray:
        return _roll_mean(self.panel.volume, length, min_periods=max(5, length // 3))

    def _f_volume_ratio(self, length: int = 50) -> np.ndarray:
        avg = self.get("avg_volume", length=length)
        return self.panel.volume / np.where(avg > 0, avg, np.nan)

    def _f_up_down_volume(self, length: int = 50) -> np.ndarray:
        """Accumulation/distribution: volume traded on up days vs down days."""
        c = self.panel.close
        up = (c > _shift(c, 1)).astype(np.float64)
        up_vol = _roll_sum(self.panel.volume * up, length, min_periods=max(10, length // 3))
        dn_vol = _roll_sum(self.panel.volume * (1.0 - up), length, min_periods=max(10, length // 3))
        return up_vol / np.where(dn_vol > 0, dn_vol, np.nan)

    # ------------------------------------------------- relative strength --
    def _f_rs_score(self) -> np.ndarray:
        """IBD-style blended momentum, weighted toward the recent quarter."""
        r3 = self.get("ret", days=63)
        r6 = self.get("ret", days=126)
        r12 = self.get("ret", days=252)
        parts, weights = [r3, r6, r12], [2.0, 1.0, 1.0]
        total = np.zeros_like(r3)
        wsum = np.zeros_like(r3)
        for part, w in zip(parts, weights):
            ok = np.isfinite(part)
            total = np.where(ok, total + w * np.nan_to_num(part), total)
            wsum = np.where(ok, wsum + w, wsum)
        return np.where(wsum > 0, total / np.where(wsum > 0, wsum, np.nan), np.nan)

    def _f_rs_rank(self) -> np.ndarray:
        """Cross-sectional percentile (1-99) of rs_score, computed per day.

        Ranking across the panel each day is what makes this point-in-time: the
        percentile a name held in 2016 is computed only from names that had
        data in 2016.
        """
        score = self.get("rs_score")
        return _df(score).rank(axis=1, pct=True).to_numpy() * 98.0 + 1.0

    def _f_momo_12m_1m(self) -> np.ndarray:
        """Classic cross-sectional momentum: 12-month return skipping the most
        recent month, which is contaminated by short-horizon reversal."""
        c = self.panel.close
        a, b = _shift(c, 21), _shift(c, 252)
        return a / np.where(b > 0, b, np.nan) - 1.0

    def _f_rs_line_high(self, window: int = 252) -> np.ndarray:
        """RS line (stock / benchmark) at or near its own N-day high."""
        if self._bench is None:
            return np.full((self.n, self.m), np.nan)
        bench = np.where(self._bench > 0, self._bench, np.nan)[:, None]
        rs = self.panel.close / bench
        hi = _roll_max(rs, window, min_periods=60)
        return (rs >= hi * 0.98).astype(np.float64)

    # ------------------------------------------------------- structure ----
    def _f_dist_from_sma(self, length: int = 50) -> np.ndarray:
        sma = self.get("sma", length=length)
        return (self.panel.close / np.where(sma > 0, sma, np.nan) - 1.0) * 100.0

    def _f_tightness(self) -> np.ndarray:
        """Volatility contraction: recent range relative to the base's range.

        Below 1 means the stock is coiling — the structural precondition every
        base-breakout method (VCP, cup-with-handle) is really describing.
        """
        short = _roll_mean(self.get("atr_pct", length=14), 20, min_periods=10)
        long = _roll_mean(self.get("atr_pct", length=14), 50, min_periods=25)
        return short / np.where(long > 0, long, np.nan)

    def _f_gap_pct(self) -> np.ndarray:
        """Overnight gap into today's open, as a % of the prior close. Used at
        fill time to reject a fill the live strategy would never have got."""
        prev_close = _shift(self.panel.close, 1)
        return (self.panel.open / np.where(prev_close > 0, prev_close, np.nan) - 1.0) * 100.0

    def _f_squeeze(self) -> np.ndarray:
        """Bollinger-in-Keltner squeeze: 20d band width at a 6-month low."""
        c = self.panel.close
        sd = _roll_std(c, 20)
        ma = _roll_mean(c, 20, min_periods=10)
        width = (2.0 * sd) / np.where(ma > 0, ma, np.nan)
        floor = _roll_min(width, 126, min_periods=40)
        return (width <= floor * 1.10).astype(np.float64)

    # ------------------------------------------- literature enhancements --
    def _f_info_discreteness(self, window: int = 252) -> np.ndarray:
        """Frog-in-the-Pan information discreteness (Da, Gurun & Warachka 2014).

            ID = sign(cumulative return) x (share of down days - share of up days)

        The hypothesis: a series of small, frequent moves attracts less attention
        than the same cumulative move delivered in a few jumps, so information
        that arrives *continuously* is underreacted to and its momentum persists.
        Empirically the gap is large — roughly 8.9% versus 2.9% over six months
        between continuous and discrete formation periods at the same cumulative
        return.

        LOW (negative) ID = continuous = the desirable end. The ranking layer
        therefore uses -ID.
        """
        r = self.get("ret", days=1)
        pos = (r > 0).astype(np.float64)
        neg = (r < 0).astype(np.float64)
        have = np.isfinite(r).astype(np.float64)
        n_pos = _roll_sum(pos, window, min_periods=window // 2)
        n_neg = _roll_sum(neg, window, min_periods=window // 2)
        n_all = _roll_sum(have, window, min_periods=window // 2)
        share = (n_neg - n_pos) / np.where(n_all > 0, n_all, np.nan)
        cum = self.get("ret", days=window)
        return np.sign(cum) * share

    def _f_residual_momentum(self, window: int = 252, skip: int = 21) -> np.ndarray:
        """Idiosyncratic momentum (Blitz, Huij & Martens 2011).

        Rank on the part of past return the market does NOT explain, scaled by
        its own volatility. Plain momentum loads heavily on whatever the market
        has been doing, which is precisely what makes it crash when the market
        reverses; stripping the market component keeps the stock-specific
        continuation and drops much of that exposure.

        Beta is estimated on a rolling window from daily returns, so it is
        point-in-time like everything else here.
        """
        if self._bench is None:
            return np.full((self.n, self.m), np.nan)
        r = self.get("ret", days=1)
        b = np.zeros_like(self._bench)
        b[1:] = self._bench[1:] / np.where(self._bench[:-1] > 0, self._bench[:-1], np.nan) - 1.0
        bm = np.nan_to_num(b, nan=0.0)[:, None]

        df_r = _df(r)
        df_m = pd.DataFrame(np.repeat(bm, self.m, axis=1))
        mp = max(60, window // 3)
        cov = (df_r * df_m).rolling(window, min_periods=mp).mean()             - df_r.rolling(window, min_periods=mp).mean() * df_m.rolling(window, min_periods=mp).mean()
        var = (df_m * df_m).rolling(window, min_periods=mp).mean()             - df_m.rolling(window, min_periods=mp).mean() ** 2
        beta = (cov / var.where(var.abs() > 1e-18)).to_numpy()

        resid = r - beta * bm
        # 12-1: skip the most recent month, which carries short-horizon reversal.
        cum = _roll_sum(np.nan_to_num(resid, nan=0.0), window - skip,
                        min_periods=(window - skip) // 2)
        cum = _shift(cum, skip)
        sd = _roll_std(resid, window - skip)
        # A stock that is purely the market re-levered has almost no residual
        # variance, so cum/sd is noise divided by noise and explodes — putting
        # exactly the names with NO idiosyncratic component at the top of the
        # ranking. Residual momentum is only defined where residual variance
        # exists, so the denominator is floored relative to total volatility.
        total_sd = _roll_std(r, window - skip)
        floor = 0.15 * total_sd
        sd_eff = np.fmax(sd, floor)
        return cum / np.where(sd_eff > 1e-12, sd_eff, np.nan)

    # ------------------------------------------------------ history len ---
    def _f_bars_available(self) -> np.ndarray:
        valid = np.isfinite(self.panel.close).astype(np.float64)
        return np.cumsum(valid, axis=0)


def benchmark_series(store, symbol: str, dates: np.ndarray) -> np.ndarray:
    """Benchmark closes aligned onto the panel's date grid (forward-filled over
    the index's own non-trading gaps, never over the panel's)."""
    df = store.load(symbol)
    if df is None:
        return np.full(len(dates), np.nan)
    s = df.set_index("date")["close"]
    grid = pd.DatetimeIndex(dates)
    return s.reindex(grid).ffill().to_numpy(dtype=np.float64)
