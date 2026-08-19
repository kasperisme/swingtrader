"""Genome -> signals.

Turns a genome into the four matrices the simulator needs:

    eligible  (n,m) bool   — may be held today
    trigger   (n,m) bool   — fires an order to be filled at tomorrow's open
    score     (n,m) float  — ranking, used when candidates exceed free slots
    regime_ok (n,)   bool  — the market permits new risk today

Everything is computed on closes at t. The one-bar gap between signal and fill
is enforced in `backtest.py`, not here, so this module can stay declarative.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .features import FeatureBank
from .genome import SECTOR_PRESETS, Genome


def _pct_rank(mat: np.ndarray) -> np.ndarray:
    """Cross-sectional percentile per day, in [0,1]. Ranking rather than
    z-scoring keeps a single blown-up name from dominating the composite."""
    return pd.DataFrame(mat).rank(axis=1, pct=True).to_numpy()


def _ge(mat: np.ndarray, thr: float) -> np.ndarray:
    """>= with NaN treated as FAIL.

    Direction matters: unknown must never pass a gate, or a name with missing
    fundamentals sails through the fundamental screen and the backtest quietly
    measures a different strategy than the one written down.
    """
    return np.greater_equal(mat, thr, out=np.zeros(mat.shape, dtype=bool), where=np.isfinite(mat))


def _le(mat: np.ndarray, thr: float) -> np.ndarray:
    return np.less_equal(mat, thr, out=np.zeros(mat.shape, dtype=bool), where=np.isfinite(mat))


class Signals:
    __slots__ = ("eligible", "trigger", "score", "regime_ok", "atr", "stop_ma",
                 "exit_ma", "gap_pct", "gate_pass_counts", "n_days", "n_symbols",
                 "short_eligible", "short_trigger", "short_score")

    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


def build_signals(g: Genome, bank: FeatureBank, sectors: list[str],
                  bench_close: np.ndarray | None = None,
                  prefilter: np.ndarray | None = None) -> Signals:
    n, m = bank.n, bank.m
    p = bank.panel
    close = p.close

    # ---------------------------------------------------------- universe --
    tradable = np.isfinite(close)
    if prefilter is not None:
        # Applied first and unconditionally. Nothing in the genome can widen
        # it — the screen is a stated assumption, not a searchable one.
        tradable &= prefilter
    tradable &= _ge(close, g["universe.min_price"])
    tradable &= _ge(bank.get("dollar_volume_20d"), g["universe.min_dollar_vol_20d"])
    tradable &= _ge(bank.get("bars_available"), g["universe.min_history_days"])

    excluded = SECTOR_PRESETS.get(g["universe.exclude_sectors"], set())
    if excluded:
        sector_ok = np.array([s not in excluded for s in sectors], dtype=bool)
        tradable &= sector_ok[None, :]

    # Cap by liquidity rank so `max_names` means "the N most tradable today",
    # not "the first N alphabetically".
    max_names = int(g["universe.max_names"])
    if max_names < m:
        dv = np.where(tradable, bank.get("dollar_volume_20d"), np.nan)
        rank_desc = pd.DataFrame(-dv).rank(axis=1, method="first").to_numpy()
        tradable &= (rank_desc <= max_names)

    # ------------------------------------------------------------- gates --
    gate_counts: dict[str, int] = {}
    ok = tradable.copy()

    def apply(name: str, mask: np.ndarray) -> None:
        nonlocal ok
        ok = ok & mask
        gate_counts[name] = int(ok.sum())

    if g["gates.price_over_sma200"]:
        apply("price>sma200", close > bank.get("sma", length=200))
    if g["gates.price_over_sma150"]:
        apply("price>sma150", close > bank.get("sma", length=150))
    if g["gates.price_over_sma50"]:
        apply("price>sma50", close > bank.get("sma", length=50))
    if g["gates.sma_stack"]:
        s50, s150, s200 = (bank.get("sma", length=k) for k in (50, 150, 200))
        apply("sma_stack", (s50 > s150) & (s150 > s200))
    if int(g["gates.sma200_slope_days"]) > 0:
        apply("sma200_rising",
              bank.get("sma_rising", length=200, days=int(g["gates.sma200_slope_days"])) > 0)
    apply("above_52w_low", _ge(bank.get("pct_above_52w_low"), g["gates.min_pct_above_52w_low"]))
    apply("near_52w_high", _le(bank.get("pct_below_52w_high"), g["gates.max_pct_below_52w_high"]))
    if int(g["gates.rs_rank_min"]) > 0:
        apply("rs_rank", _ge(bank.get("rs_rank"), float(g["gates.rs_rank_min"])))

    adr = bank.get("adr_pct", length=20)
    apply("adr_band", _ge(adr, g["gates.adr_min"]) & _le(adr, g["gates.adr_max"]))
    apply("accumulation", _ge(bank.get("up_down_volume", length=50), g["gates.min_up_down_vol"]))
    if g["gates.rs_line_new_high"] and bench_close is not None:
        apply("rs_line_high", bank.get("rs_line_high") > 0)
    apply("not_extended", _le(bank.get("dist_from_sma", length=50), g["gates.max_dist_from_sma50"]))
    if g["gates.min_base_tightness"] > 0.01:
        apply("tightness", _le(bank.get("tightness"), 1.0 - g["gates.min_base_tightness"]))
    if g["gates.max_info_discreteness"] < 0.29:
        apply("continuous_info", _le(bank.get("info_discreteness"),
                                     g["gates.max_info_discreteness"]))

    # ------------------------------------------- alternative-data overlays --
    if g["gates.use_fundamentals"]:
        eps = bank.extra.get("eps_yoy")
        rev = bank.extra.get("rev_yoy")
        beats = bank.extra.get("beat_streak")
        if eps is not None:
            apply("eps_growth", _ge(eps, g["gates.fund_min_eps_yoy"]))
        if rev is not None:
            apply("rev_growth", _ge(rev, g["gates.fund_min_rev_yoy"]))
        if beats is not None and int(g["gates.fund_min_beats"]) > 0:
            apply("eps_beats", _ge(beats, float(g["gates.fund_min_beats"])))

    if g["gates.use_news"]:
        sent = bank.extra.get("news_sentiment")
        cnt = bank.extra.get("news_articles")
        if sent is not None:
            apply("news_sentiment", _ge(sent, g["gates.news_min_sentiment"]))
        if cnt is not None and int(g["gates.news_min_articles"]) > 0:
            apply("news_coverage", _ge(cnt, float(g["gates.news_min_articles"])))

    eligible = ok

    # ------------------------------------------------------------ regime --
    regime_ok = np.ones(n, dtype=bool)
    if g["regime.enabled"] and bench_close is not None and np.isfinite(bench_close).any():
        b = pd.Series(bench_close)
        ma = b.rolling(int(g["regime.ma_len"]), min_periods=int(g["regime.ma_len"]) // 2).mean()
        regime_ok = (b > ma).to_numpy(dtype=bool) & np.isfinite(ma.to_numpy())
        slope_days = int(g["regime.slope_days"])
        if slope_days > 0:
            regime_ok &= (ma > ma.shift(slope_days)).fillna(False).to_numpy()
    if g["regime.breadth_enabled"]:
        above = (close > bank.get("sma", length=50))
        have = np.isfinite(close) & np.isfinite(bank.get("sma", length=50))
        denom = have.sum(axis=1)
        breadth = np.where(denom > 0, (above & have).sum(axis=1) / np.maximum(denom, 1), np.nan)
        regime_ok = regime_ok & np.greater_equal(
            breadth, g["regime.breadth_min"],
            out=np.zeros(n, dtype=bool), where=np.isfinite(breadth))

    # ----------------------------------------------------------- trigger --
    etype = g["entry.type"]
    vol_ok = _ge(bank.get("volume_ratio", length=50), g["entry.vol_confirm_ratio"])

    if etype == "breakout_pivot":
        lb = int(g["entry.pivot_lookback"])
        pivot = bank.get("pivot_high", lookback=lb)
        buf = 1.0 + g["entry.breakout_buffer_pct"] / 100.0
        above = close > pivot * buf
        prev_above = np.vstack([np.zeros((1, m), dtype=bool), above[:-1]])
        ext = (close / np.where(pivot > 0, pivot, np.nan) - 1.0) * 100.0
        # A fresh cross, not merely "currently above" — otherwise the rule
        # re-fires every day the stock stays extended.
        trigger = above & (~prev_above) & vol_ok & _le(ext, g["entry.max_extension_pct"])

    elif etype == "pullback_to_ma":
        ma = bank.get("sma", length=int(g["entry.pullback_ma_len"]))
        band = g["entry.pullback_band_pct"] / 100.0
        near = np.abs(close / np.where(ma > 0, ma, np.nan) - 1.0) <= band
        reclaim = (close > ma) & (np.vstack([np.zeros((1, m), dtype=bool), (close <= ma)[:-1]]))
        trigger = (near | reclaim) & (bank.get("ret", days=1) > 0)
        trigger = np.nan_to_num(trigger, nan=False).astype(bool)

    elif etype == "volatility_squeeze":
        sq = bank.get("squeeze") > 0
        trigger = sq & (close > bank.get("sma", length=20)) & vol_ok

    else:  # rank_only — the portfolio layer decides purely on ranking
        trigger = np.ones((n, m), dtype=bool)

    trigger = trigger & eligible

    # ------------------------------------------------------------- score --
    score = np.zeros((n, m), dtype=np.float64)
    weights = {
        "rank.w_rs": lambda: _pct_rank(bank.get("rs_rank")),
        "rank.w_momo_3m": lambda: _pct_rank(bank.get("ret", days=63)),
        "rank.w_momo_12m_1m": lambda: _pct_rank(bank.get("momo_12m_1m")),
        "rank.w_vol_surge": lambda: _pct_rank(bank.get("volume_ratio", length=50)),
        "rank.w_tightness": lambda: 1.0 - _pct_rank(bank.get("tightness")),
        "rank.w_low_vol": lambda: 1.0 - _pct_rank(bank.get("realized_vol", length=20)),
        "rank.w_proximity_high": lambda: 1.0 - _pct_rank(bank.get("pct_below_52w_high")),
        "rank.w_news": lambda: _pct_rank(bank.extra["news_sentiment"])
        if "news_sentiment" in bank.extra else None,
        # Low ID = continuous information = the desirable end, hence 1 - rank.
        "rank.w_continuity": lambda: 1.0 - _pct_rank(bank.get("info_discreteness")),
        "rank.w_residual_momo": lambda: _pct_rank(bank.get("residual_momentum")),
    }
    wsum = 0.0
    for key, fn in weights.items():
        w = float(g[key])
        if w < 1e-6:
            continue
        comp = fn()
        if comp is None:
            continue
        score += w * np.nan_to_num(comp, nan=0.0)
        wsum += w
    if wsum > 0:
        score /= wsum
    # Ranking only ever compares scores, so float32 is more than enough
    # precision and halves the memory the per-genome signal cache holds.
    score = score.astype(np.float32)

    # ------------------------------------------------------ short sleeve --
    # The mirror of the long template, but deliberately NOT a pure inversion:
    # shorts carry unbounded loss and squeeze risk, so the price and liquidity
    # floors are stricter and a separate "already heavily shorted" guard exists.
    if g["short.enabled"]:
        s_ok = np.isfinite(close)
        if prefilter is not None:
            # Shorts qualify on the MIRROR of the screen: a long-side trend
            # filter must not gate the short book, or the sleeve can only ever
            # short names that look like longs.
            s_ok &= ~prefilter
        s_ok &= _ge(close, g["short.min_price"])
        s_ok &= _ge(bank.get("dollar_volume_20d"), g["short.min_dollar_vol"])
        s_ok &= _ge(bank.get("bars_available"), g["universe.min_history_days"])
        if excluded:
            s_ok &= sector_ok[None, :]

        if g["short.price_under_sma200"]:
            s_ok &= close < bank.get("sma", length=200)
        if g["short.price_under_sma50"]:
            s_ok &= close < bank.get("sma", length=50)
        if g["short.sma_stack_down"]:
            s50, s150, s200 = (bank.get("sma", length=k) for k in (50, 150, 200))
            s_ok &= (s50 < s150) & (s150 < s200)
        s_ok &= _le(bank.get("rs_rank"), float(g["short.rs_rank_max"]))
        s_ok &= _le(bank.get("pct_above_52w_low"), g["short.max_pct_above_52w_low"])
        s_ok &= _ge(bank.get("pct_below_52w_high"), g["short.min_pct_below_52w_high"])
        s_ok &= _le(bank.get("up_down_volume", length=50), g["short.max_up_down_vol"])
        # Squeeze guard. True short interest is not in this dataset, so turnover
        # stands in for crowding: a name whose float turns over unusually fast is
        # where a short squeeze does its damage. A proxy, and labelled as one.
        s_ok &= _le(bank.get("volume_ratio", length=50), 1.0 + g["short.max_short_interest"] * 5)

        stype = g["short.entry_type"]
        if stype == "breakdown_pivot":
            lb = int(g["short.pivot_lookback"])
            pivot_lo = bank.get("pivot_low", lookback=lb)
            below = close < pivot_lo
            prev_below = np.vstack([np.zeros((1, m), dtype=bool), below[:-1]])
            s_trigger = below & (~prev_below)
        elif stype == "failed_rally":
            ma = bank.get("sma", length=50)
            # Rallied into the falling 50-day and rolled over: the classic
            # short entry, and the one with a well-defined stop.
            near = (close > ma * 0.97) & (close < ma * 1.03)
            prev_near = np.vstack([np.zeros((1, m), dtype=bool), near[:-1]])
            s_trigger = prev_near & (bank.get("ret", days=1) < 0)
            s_trigger = np.nan_to_num(s_trigger, nan=False).astype(bool)
        else:
            s_trigger = np.ones((n, m), dtype=bool)

        short_eligible = s_ok
        short_trigger = s_trigger & s_ok
        # Rank shorts by weakness: the inverse of the long composite.
        short_score = (1.0 - _pct_rank(bank.get("rs_rank"))).astype(np.float32)
    else:
        short_eligible = np.zeros((n, m), dtype=bool)
        short_trigger = np.zeros((n, m), dtype=bool)
        short_score = np.zeros((n, m), dtype=np.float32)

    return Signals(
        eligible=eligible,
        trigger=trigger,
        score=score,
        short_eligible=short_eligible,
        short_trigger=short_trigger,
        short_score=short_score,
        regime_ok=regime_ok,
        atr=bank.get("atr", length=14),
        stop_ma=bank.get("sma", length=int(g["exit.stop_ma_len"])),
        exit_ma=bank.get("sma", length=int(g["exit.exit_sma_len"])),
        gap_pct=bank.get("gap_pct"),
        gate_pass_counts=gate_counts,
        n_days=n,
        n_symbols=m,
    )
