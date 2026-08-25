"""Which barrier is hit first — the binary outcome the whole study turns on.

Daily bars cannot say whether the high or the low came first within a session.
When one bar spans both the stop and the target, this books the LOSS, matching
`backtest.py`. That is not conservatism for its own sake: the opposite
convention manufactures a higher hit rate out of nothing but bar resolution, and
on a 2R target the difference is worth several percentage points of p — larger
than any effect being measured.

Gaps are handled explicitly too. A gap through the stop fills at the open, not
at the stop price, so the loss can exceed 1R. Ignoring that is how backtests
report a maximum loss they could never have achieved.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)


@dataclass
class OutcomeSpec:
    max_hold: int = 60
    cost_bps_per_side: float = 13.0
    # Both barriers inside one bar: book the loss.
    ambiguous_bar_is_loss: bool = True

    # --- the trailing variant -------------------------------------------
    # Reaching the target CONVERTS the trade instead of closing it: the stop
    # moves to a moving average and the position runs until price closes below
    # it. This is the rule as actually traded, and the fixed-target study
    # pointed straight at it — 26% of trades timed out unresolved earning
    # +0.50R, which is drift the 2R cap was throwing away.
    trail_on_target: bool = False
    trail_ma_len: int = 21
    # Losers stay capped at `max_hold`; a converted winner may run much longer.
    # That asymmetry IS the strategy ("cut losses short, let winners run"), so
    # it is correct here — but it is also exactly the kind of asymmetry that
    # flatters a backtest, so the control is resolved under the identical rule.
    max_trail_hold: int = 252


@dataclass
class Outcome:
    hit_target: bool
    hit_stop: bool
    resolved: bool
    days_held: int
    exit_price: float
    exit_reason: str
    r_multiple: float
    r_net: float
    mae_r: float
    mfe_r: float


def resolve_setups(panel, setups, spec: OutcomeSpec, trail_ma=None) -> pd.DataFrame:
    """Walk each setup forward to the first barrier touch.

    With `trail_on_target`, touching the target does not close the trade: the
    stop moves to `trail_ma` and the position runs until a close below it, which
    fills at the next open.
    """
    high, low, close, open_ = panel.high, panel.low, panel.close, panel.open
    n = panel.close.shape[0]
    if spec.trail_on_target and trail_ma is None:
        raise ValueError("trail_on_target requires the trail_ma matrix")
    rows = []

    for s in setups:
        j = s.col
        entry_day = s.day + 1
        if entry_day >= n:
            continue
        risk = s.entry - s.stop
        if not (risk > 0):
            continue
        last = min(n - 1, entry_day + spec.max_hold)
        stop_ceiling = min(n - 1, entry_day + spec.max_hold + spec.max_trail_hold)

        hit_t = hit_s = False
        trailing = False
        exit_price = np.nan
        exit_day = last
        reason = "timeout"
        mae = 0.0
        mfe = 0.0
        u = entry_day

        while u <= (stop_ceiling if trailing else last):
            o, h, l, c = open_[u, j], high[u, j], low[u, j], close[u, j]
            if not (np.isfinite(h) and np.isfinite(l)):
                u += 1
                continue
            mae = min(mae, (l - s.entry) / risk)
            mfe = max(mfe, (h - s.entry) / risk)

            if trailing:
                ma = trail_ma[u, j]
                # Never let the trail sit below the original support stop.
                floor = s.stop if not np.isfinite(ma) else max(float(ma), s.stop)
                if np.isfinite(o) and o <= floor:
                    exit_price, exit_day, reason = o, u, "trail_gap"
                    break
                if np.isfinite(c) and c < floor:
                    nxt = min(n - 1, u + 1)
                    px = open_[nxt, j]
                    exit_price = float(px) if np.isfinite(px) else float(c)
                    exit_day, reason = nxt, "trail_ma"
                    break
                u += 1
                continue

            if np.isfinite(o) and o <= s.stop:
                hit_s, exit_price, exit_day, reason = True, o, u, "stop_gap"
                break
            if np.isfinite(o) and o >= s.target:
                hit_t = True
                if spec.trail_on_target:
                    trailing = True
                    u += 1
                    continue
                exit_price, exit_day, reason = o, u, "target_gap"
                break
            touch_stop = l <= s.stop
            touch_target = h >= s.target
            if touch_stop and touch_target:
                if spec.ambiguous_bar_is_loss:
                    hit_s, exit_price, exit_day, reason = True, s.stop, u, "stop_ambiguous"
                    break
                hit_t = True
                if spec.trail_on_target:
                    trailing = True
                    u += 1
                    continue
                exit_price, exit_day, reason = s.target, u, "target_ambiguous"
                break
            if touch_stop:
                hit_s, exit_price, exit_day, reason = True, s.stop, u, "stop"
                break
            if touch_target:
                hit_t = True
                if spec.trail_on_target:
                    trailing = True
                    u += 1
                    continue
                exit_price, exit_day, reason = s.target, u, "target"
                break
            u += 1

        if not np.isfinite(exit_price):
            exit_day = min(stop_ceiling if trailing else last, n - 1)
            px = close[exit_day, j]
            if not np.isfinite(px):
                continue
            exit_price = px
            reason = "trail_timeout" if trailing else "timeout"

        r = (exit_price - s.entry) / risk
        # Costs are charged on notional and converted to R: a 26bp round trip on
        # a position risking 5% of price is 0.052R, not 0.0026R. Expressing them
        # in R is the only way they are comparable to the 2:1 payoff.
        cost_r = (2.0 * spec.cost_bps_per_side * 1e-4) / s.risk_pct
        rows.append({
            "symbol": s.symbol, "date": s.date, "day": s.day, "col": j,
            "entry": s.entry, "stop": s.stop, "target": s.target,
            "risk_pct": s.risk_pct, "is_pseudo": s.is_pseudo,
            "hit_target": bool(hit_t), "hit_stop": bool(hit_s),
            "trailed": bool(trailing),
            "resolved": bool(hit_t or hit_s),
            "days_held": int(exit_day - entry_day + 1),
            "exit_price": float(exit_price), "exit_reason": reason,
            "r_multiple": float(r), "r_net": float(r - cost_r),
            "cost_r": float(cost_r),
            "pct_return": float(exit_price / s.entry - 1.0),
            "mae_r": float(mae), "mfe_r": float(mfe),
        })
    return pd.DataFrame(rows)
