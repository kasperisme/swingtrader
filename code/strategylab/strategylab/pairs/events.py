"""Divergence events and what happened next.

The forward-control structure the flow Stage-1 lacked is built in here: the
*discriminator* is measured on the divergence day and everything scored below
is measured strictly after it. Nothing on the right-hand side of an H1 test
shares a return with anything on the left.

Execution follows the lab convention: a signal computed on the close of day t
is filled at the OPEN of day t+1, both legs. A pair whose entry or exit open is
missing on either leg is dropped rather than filled forward — a synthetic price
is exactly the kind of small lie that shows up later as alpha.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

from .anchor import anchored_z

log = logging.getLogger(__name__)


@dataclass
class EventSpec:
    z_entry: float = 2.0
    z_rearm: float = 0.5                 # a pair may diverge again only after
                                         # the spread comes back inside this
    horizon: int = 60                    # trading days a divergence is followed
    short_horizon: int = 20              # secondary, pre-registered
    z_soft: float = 1.0                  # the "halved, not crossed" outcome
    # Frictions, per side, per leg, on the traded notional. Deliberately the
    # same numbers `LabConfig.Costs` charges the equity book.
    cost_bps_per_side: float = 13.0
    # NOT modelled: borrow. The short leg of a flow-driven divergence is often a
    # crowded, hard-to-borrow name and the fee can run to hundreds of bps. Every
    # net return here is therefore an upper bound; the H1 contrast is a
    # difference between buckets and is far less exposed to it.


@dataclass
class DivergenceEvent:
    window: int
    pair: str
    a: str
    b: str
    industry: str
    beta: float
    half_life: float
    adf_t: float
    etf_overlap: float
    day: int                             # panel row index of the divergence close
    date: str
    entry_day: int                       # panel row of the fill (open)
    z_entry: float
    side: int                            # +1 short-the-spread, -1 long-the-spread
    converged: bool                      # z crossed zero within `horizon`
    converged_short: bool                # ... within `short_horizon`
    converged_soft: bool                 # |z| fell below `z_soft` within `horizon`
    days_to_converge: float              # NaN when censored
    # Restricted mean survival time: days to convergence, with censored events
    # set to the full horizon. Comparing mean `days_to_converge` across buckets
    # conditions on the outcome — the slowest N-bucket divergences are exactly
    # the ones that never converge and so drop out of that average, biasing it
    # toward the null. RMST keeps them.
    rmst_days: float
    exit_day: int
    holding_days: int
    gross_return: float                  # of unit gross notional
    net_return: float
    max_adverse_z: float                 # furthest |z| reached after entry
    widening: float                      # max_adverse_z - |z_entry|, >= 0
    z_exit: float
    # Realised daily volatility of z over the measurement horizon, and the
    # horizon actually available. Together with z_entry these give the
    # driftless first-passage probability for this event, which is the
    # benchmark the frozen anchor is scored against.
    z_vol_post: float
    horizon_used: int


def _spread_z(pair, close: np.ndarray) -> np.ndarray:
    """z of the log spread over the whole panel, using FORMATION mu/sigma."""
    a = np.log(np.where(close[:, pair.ia] > 0, close[:, pair.ia], np.nan))
    b = np.log(np.where(close[:, pair.ib] > 0, close[:, pair.ib], np.nan))
    s = a - pair.alpha - pair.beta * b
    return (s - pair.mu) / pair.sigma


def _first_cross(z: np.ndarray, side: int, start: int, stop: int,
                 level: float = 0.0) -> int:
    """First index in (start, stop] where the spread has come back to `level`.

    `side = +1` means the spread was rich, so convergence is z <= level.
    """
    seg = z[start + 1: stop + 1]
    if seg.size == 0:
        return -1
    hit = np.flatnonzero(np.isfinite(seg) & (side * seg <= level))
    return int(start + 1 + hit[0]) if hit.size else -1


def scan_convergence(z: np.ndarray, t0: int, t1: int, spec: EventSpec,
                     n: int | None = None) -> list[dict]:
    """The event scanner, on a z path alone. THE shared core.

    `collect_events` calls this and then prices the trades; the synthetic null
    calls it and stops here. One implementation, so a null can never accidentally
    be measured with different rules from the book it is the null for.

    Returns one dict per divergence: entry index, side, and the convergence
    outcomes over `spec.horizon` sessions.
    """
    n = int(n if n is not None else len(z))
    out: list[dict] = []
    armed = True
    t = t0
    while t < t1:
        zt = z[t]
        if not np.isfinite(zt):
            t += 1
            continue
        if not armed:
            if abs(zt) < spec.z_rearm:
                armed = True
            t += 1
            continue
        if abs(zt) < spec.z_entry:
            t += 1
            continue

        side = 1 if zt > 0 else -1
        stop = min(n - 1, t + spec.horizon)
        if t + 1 > stop:
            break
        conv = _first_cross(z, side, t, stop)
        conv_short = _first_cross(z, side, t, min(stop, t + spec.short_horizon))
        conv_soft = _first_cross(z, side, t, stop, level=spec.z_soft)
        converged = conv > 0
        out.append({
            "day": int(t), "side": int(side), "z_entry": float(zt),
            "stop": int(stop), "conv": int(conv), "converged": bool(converged),
            "converged_short": bool(conv_short > 0),
            "converged_soft": bool(conv_soft > 0),
            "days_to_converge": float(conv - t) if converged else float("nan"),
            "rmst_days": float(conv - t) if converged else float(stop - t),
        })
        armed = False
        t += 1
    return out


def collect_events(panel, pairs, spec: EventSpec,
                   anchor=None) -> list[DivergenceEvent]:
    """Every divergence in every pair's own trading window.

    Outcomes are measured over `spec.horizon` sessions from the divergence,
    which may run PAST the end of the trading window. That is deliberate: a
    fixed measurement horizon keeps the L and N buckets comparable, whereas
    truncating at the window boundary would censor late-window events
    differentially. It does not leak — the formation estimates are still only
    from before the window, and no pair is re-formed on the extra days.
    """
    close, open_ = panel.close, panel.open
    dates = panel.dates
    n = len(dates)
    out: list[DivergenceEvent] = []

    for p in pairs:
        z = _spread_z(p, close) if anchor is None else anchored_z(p, close, anchor)
        t0, t1 = _window_bounds(p, panel)
        if t0 is None:
            continue
        for ev in scan_convergence(z, t0, t1, spec, n=n):
            t, side = ev["day"], ev["side"]
            zt = ev["z_entry"]
            entry = t + 1
            stop = ev["stop"]
            pa, pb = open_[entry, p.ia], open_[entry, p.ib]
            if not (np.isfinite(pa) and np.isfinite(pb)):
                continue

            conv = ev["conv"]
            converged = ev["converged"]
            exit_signal = conv if converged else stop
            exit_fill = min(n - 1, exit_signal + 1)
            qa, qb = open_[exit_fill, p.ia], open_[exit_fill, p.ib]
            if not (np.isfinite(qa) and np.isfinite(qb)):
                # Walk back to the last jointly-priced session rather than
                # inventing a fill.
                back = np.flatnonzero(np.isfinite(open_[entry:exit_fill + 1, p.ia])
                                      & np.isfinite(open_[entry:exit_fill + 1, p.ib]))
                if back.size < 2:
                    continue
                exit_fill = int(entry + back[-1])
                qa, qb = open_[exit_fill, p.ia], open_[exit_fill, p.ib]

            ra, rb = qa / pa - 1.0, qb / pb - 1.0
            gross_notional = 1.0 + abs(p.beta)
            spread_ret = (ra - p.beta * rb) / gross_notional
            gross = -side * spread_ret
            # Round trip, both legs, on unit gross notional.
            net = gross - 2.0 * spec.cost_bps_per_side * 1e-4

            seg = z[t + 1: exit_signal + 1]
            seg = seg[np.isfinite(seg)]
            adverse = float(np.max(side * seg)) if seg.size else float(side * zt)
            max_adverse_z = max(abs(zt), adverse)

            # Measured over the FULL horizon regardless of when the trade
            # closed, so the benchmark is not conditioned on the outcome.
            full = z[t: stop + 1]
            full = full[np.isfinite(full)]
            z_vol = float(np.diff(full).std(ddof=1)) if full.size > 2 else float("nan")

            out.append(DivergenceEvent(
                window=p.window, pair=p.key(), a=p.a, b=p.b, industry=p.industry,
                beta=p.beta, half_life=p.half_life, adf_t=p.adf_t,
                etf_overlap=p.etf_overlap,
                day=int(t), date=str(dates[t]), entry_day=int(entry),
                z_entry=float(zt), side=int(side), converged=bool(converged),
                converged_short=bool(ev["converged_short"]),
                converged_soft=bool(ev["converged_soft"]),
                days_to_converge=ev["days_to_converge"],
                rmst_days=ev["rmst_days"],
                exit_day=int(exit_fill), holding_days=int(exit_fill - entry),
                gross_return=float(gross), net_return=float(net),
                max_adverse_z=float(max_adverse_z),
                widening=float(max(0.0, max_adverse_z - abs(zt))),
                z_exit=float(z[exit_signal]) if np.isfinite(z[exit_signal]) else float("nan"),
                z_vol_post=z_vol, horizon_used=int(max(1, full.size - 1)),
            ))
    return out


def _window_bounds(pair, panel) -> tuple[int | None, int]:
    """Panel row indices of the pair's trading window."""
    try:
        t0 = panel.date_index(pair.trade_start)
        t1 = panel.date_index(pair.trade_end) + 1
    except Exception:
        return None, 0
    if t0 >= len(panel.dates):
        return None, 0
    return t0, min(len(panel.dates), t1)


def events_frame(events: list[DivergenceEvent]):
    import pandas as pd
    return pd.DataFrame([e.__dict__ for e in events])
