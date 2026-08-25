"""Base detection, the breakout trigger, and the stop/target geometry.

Written as the trade is actually described rather than as a parameter surface:
price consolidates near its high, breaks the pivot on volume, the stop goes at
the support beneath the base, and the target sits two risk units above entry.

Two rules carry the honesty:

  * **The pivot excludes the current bar.** `FeatureBank.pivot_high` is shifted
    by one, so a breakout is measured against highs that were already set. A
    pivot that includes today can never be broken by today, and a breakout rule
    written against an inclusive rolling max either never fires or fires on
    every bar — the classic silent backtest bug.

  * **A setup with the stop too far away is not taken.** "Limited risk" is the
    Minervini rule and it is also what keeps the R-multiple meaningful: if the
    stop is 30% away, 2R is a 60% move and the trade is a different animal from
    one risking 5%. Setups outside the risk band are dropped, and how many are
    dropped is reported.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)


@dataclass
class SetupSpec:
    """The trade, fixed. Not a search space."""

    base_len: int = 40                   # bars the pivot high is measured over
    stop_lookback: int = 10              # bars the support (pivot low) is taken from
    min_risk_pct: float = 0.02           # a stop 0.5% away is noise, not support
    max_risk_pct: float = 0.10           # "limited risk" — Minervini's rule
    reward_multiple: float = 2.0         # take profit at 2R
    volume_mult: float = 1.3             # breakout needs volume confirmation
    require_volume: bool = True
    # Once a name triggers, it cannot trigger again until the trade resolves.
    # Without this a single breakout produces a new "setup" every day it stays
    # above the pivot, and the sample fills with the same trade counted 20 times.
    one_trade_per_name: bool = True
    max_hold: int = 60

    # --- which entry to test -------------------------------------------
    # "breakout" buys the break of the base pivot. "pullback" buys the reclaim
    # of a rising moving average after price has traded down to it.
    #
    # The pullback variant is not folklore-shopping: this study already found
    # that the breakout trigger UNDERPERFORMS a no-trigger control (31.3% vs
    # 34.3%) and that `reversal_5d` — buy after a quiet or down stretch — was the
    # strongest conditioner of the hit rate. Both say the same thing, and it is
    # the same thing the skip-month in 12-1 momentum encodes: within a name that
    # is already trending, recent strength is a negative signal.
    trigger: str = "breakout"
    ma_len: int = 21
    ma_rising_days: int = 20
    pullback_window: int = 10                   # bars before an unresolved trade is closed
    cost_bps_per_side: float = 13.0


@dataclass
class Setup:
    day: int
    col: int
    symbol: str
    date: str
    entry: float                         # open of day+1
    stop: float
    target: float
    risk_pct: float
    is_pseudo: bool = False


def _geometry(panel, bank, spec: SetupSpec):
    """Entry (next open), support-based stop and the 2R target, per bar."""
    open_ = panel.open
    nxt_open = np.vstack([open_[1:], np.full((1, open_.shape[1]), np.nan)])
    support = bank.get("pivot_low", lookback=spec.stop_lookback)
    with np.errstate(invalid="ignore", divide="ignore"):
        risk_pct = (nxt_open - support) / nxt_open
        target = nxt_open + spec.reward_multiple * (nxt_open - support)
    return nxt_open, support, risk_pct, target


def _breakout_trigger(panel, bank, mask: np.ndarray, spec: SetupSpec) -> np.ndarray:
    """Close above the base pivot, on volume, inside the universe."""
    close = panel.close
    pivot = bank.get("pivot_high", lookback=spec.base_len)
    trig = mask & np.isfinite(pivot) & (close > pivot)
    if spec.require_volume:
        vr = bank.get("volume_ratio", length=50)
        trig &= np.greater_equal(vr, spec.volume_mult,
                                 out=np.zeros(trig.shape, dtype=bool),
                                 where=np.isfinite(vr))
    return trig


def _pullback_trigger(panel, bank, mask: np.ndarray, spec: SetupSpec) -> np.ndarray:
    """Reclaim of a rising moving average after price traded down to it.

    Three conditions, in the order they must occur: the average is rising, price
    touched or closed below it inside the last `pullback_window` bars, and today
    closes back above it on an up day. The touch is measured on bars strictly
    BEFORE today (`_shift` by one), so the reclaim and the pullback cannot be the
    same bar — otherwise a single wide-range day that dips and recovers reads as
    a completed pullback.
    """
    close, low = panel.close, panel.low
    ma = bank.get("sma", length=spec.ma_len)
    prev_ma = np.vstack([np.full((spec.ma_rising_days, ma.shape[1]), np.nan),
                         ma[:-spec.ma_rising_days]])
    rising = np.isfinite(ma) & np.isfinite(prev_ma) & (ma > prev_ma)

    touched = np.isfinite(low) & np.isfinite(ma) & (low <= ma)
    w = spec.pullback_window
    n = touched.shape[0]
    touched_recently = np.zeros_like(touched)
    cs = np.cumsum(np.vstack([np.zeros((1, touched.shape[1])), touched.astype(float)]), axis=0)
    for t in range(w + 1, n):
        touched_recently[t] = (cs[t] - cs[t - w]) > 0        # bars t-w .. t-1

    prev_close = np.vstack([np.full((1, close.shape[1]), np.nan), close[:-1]])
    reclaim = (np.isfinite(close) & np.isfinite(ma) & (close > ma)
               & np.isfinite(prev_close) & (close > prev_close))
    return mask & rising & touched_recently & reclaim


def _trigger(panel, bank, mask: np.ndarray, spec: SetupSpec) -> np.ndarray:
    if spec.trigger == "pullback":
        return _pullback_trigger(panel, bank, mask, spec)
    if spec.trigger == "breakout":
        return _breakout_trigger(panel, bank, mask, spec)
    raise ValueError(f"unknown trigger {spec.trigger!r}")


def ma_test_count(panel, bank, spec: SetupSpec, lookback: int = 60) -> np.ndarray:
    """How many times the moving average has been tested before this bar.

    A trigger-level conditioner the no-trigger control cannot share, and the one
    the practitioner literature is most specific about: a first test of a rising
    average is held to be worth more than a third or fourth, because repeated
    selling has already eaten the support.
    """
    low = panel.low
    ma = bank.get("sma", length=spec.ma_len)
    touch = (np.isfinite(low) & np.isfinite(ma) & (low <= ma)).astype(float)
    # Distinct tests: a touch that follows at least one clear bar.
    prev = np.vstack([np.zeros((1, touch.shape[1])), touch[:-1]])
    fresh = touch * (1.0 - prev)
    cs = np.cumsum(np.vstack([np.zeros((1, fresh.shape[1])), fresh]), axis=0)
    out = np.full(low.shape, np.nan)
    for t in range(lookback + 1, low.shape[0]):
        out[t] = cs[t] - cs[t - lookback]        # tests in the prior `lookback` bars
    return out


def _collect(panel, cand: np.ndarray, nxt_open, support, risk_pct, target,
             spec: SetupSpec, is_pseudo: bool, resolve_len: np.ndarray | None = None):
    """Walk each name's candidate days, honouring one-trade-at-a-time."""
    n, m = cand.shape
    out: list[Setup] = []
    funnel = {"candidate bars": int(cand.sum()), "dropped_risk_band": 0,
              "dropped_unpriced": 0, "suppressed_already_open": 0}
    for j in range(m):
        days = np.flatnonzero(cand[:, j])
        if days.size == 0:
            continue
        busy_until = -1
        for t in days:
            if spec.one_trade_per_name and t <= busy_until:
                funnel["suppressed_already_open"] += 1
                continue
            e, s, r, g = nxt_open[t, j], support[t, j], risk_pct[t, j], target[t, j]
            if not (np.isfinite(e) and np.isfinite(s) and np.isfinite(r)):
                funnel["dropped_unpriced"] += 1
                continue
            if not (spec.min_risk_pct <= r <= spec.max_risk_pct):
                funnel["dropped_risk_band"] += 1
                continue
            out.append(Setup(day=int(t), col=int(j), symbol=panel.symbols[j],
                             date=str(panel.dates[t]), entry=float(e), stop=float(s),
                             target=float(g), risk_pct=float(r), is_pseudo=is_pseudo))
            busy_until = t + (int(resolve_len[len(out) - 1]) if resolve_len is not None
                              else spec.max_hold)
    funnel["setups"] = len(out)
    return out, funnel


def detect_setups(panel, bank, mask: np.ndarray, spec: SetupSpec):
    """Every qualifying breakout in the pinned universe."""
    nxt_open, support, risk_pct, target = _geometry(panel, bank, spec)
    trig = _trigger(panel, bank, mask, spec)
    return _collect(panel, trig, nxt_open, support, risk_pct, target, spec,
                    is_pseudo=False)


def pseudo_setups(panel, bank, mask: np.ndarray, spec: SetupSpec, seed: int = 61):
    """THE control: same universe, same day, same geometry — no trigger.

    For each real breakout on day D, one name is drawn from the qualified names
    that did NOT trigger that day, and the identical stop/target arithmetic is
    applied to it. Whatever hit rate that produces is what "buy a momentum name
    and risk 1 to make 2" delivers on its own.

    Without it a 40% hit rate reads as a good setup when it may be nothing more
    than the drift and volatility of names already screened for being in strong
    uptrends. The breakout has to beat its own universe, not a coin.
    """
    rng = np.random.default_rng(seed)
    nxt_open, support, risk_pct, target = _geometry(panel, bank, spec)
    trig = _trigger(panel, bank, mask, spec)

    viable = (mask & np.isfinite(nxt_open) & np.isfinite(support)
              & (risk_pct >= spec.min_risk_pct) & (risk_pct <= spec.max_risk_pct))
    cand = np.zeros_like(trig)
    per_day = trig.sum(axis=1)
    for t in np.flatnonzero(per_day):
        pool = np.flatnonzero(viable[t] & ~trig[t])
        if pool.size == 0:
            continue
        pick = rng.choice(pool, size=min(int(per_day[t]), pool.size), replace=False)
        cand[t, pick] = True
    return _collect(panel, cand, nxt_open, support, risk_pct, target, spec,
                    is_pseudo=True)


def setups_frame(setups: list[Setup]) -> pd.DataFrame:
    return pd.DataFrame([s.__dict__ for s in setups])
