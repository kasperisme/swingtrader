"""The discriminator — what kind of shock opened this spread?

EGJ's taxonomy needs a per-leg information flag. The one that exists over the
whole panel, cleanly and point-in-time, is the **earnings announcement**: a
scheduled, exogenous, firm-specific information event. It is a strict subset of
"news", which biases the design in the safe direction — soft information leaking
into the no-news bucket makes the L bucket look MORE like the N bucket and
therefore works against H1, never for it.

Three flags are produced per event:

    n_legs_flagged   0, 1 or 2 legs with an announcement in [t-w, t+w]
    stale_flag       an announcement in [t-60, t-50] instead — the timing
                     placebo. Same names, same event type, wrong window: if
                     this separates the buckets too, the split is picking up
                     "firms that announce" rather than "a divergence caused by
                     an announcement".
    placebo_flag     a random label with the SAME marginal rate, drawn from a
                     fixed seed. The null the whole design must clear.

Regime L (transient liquidity) is the residual — no announcement on either leg —
exactly as the spec has it. Regime F (persistent flow) is NOT identified here:
it needs 13F breadth differentials or reconstitution events, neither of which is
wired up. Every event in this module is therefore L or N, and the findings
document says so rather than implying a three-way split was tested.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)


@dataclass
class RegimeSpec:
    news_window: int = 2                 # +/- sessions around the divergence
    stale_lag_start: int = 60            # the timing placebo window, in sessions
    stale_lag_end: int = 50              # ... [t-60, t-50]
    placebo_seed: int = 23


def announcement_grid(panel, earnings_dates: dict[str, list], window: int) -> np.ndarray:
    """(n_days, n_symbols) bool — an announcement within +/- `window` sessions.

    Announcement dates are mapped onto the session grid with `searchsorted`, so
    a release on a non-trading day attaches to the next session. The band is
    symmetric because the discriminator is measured ON the divergence day and
    must catch an announcement that has just landed as well as one about to.
    """
    n, m = panel.close.shape
    grid = np.zeros((n, m), dtype=bool)
    days = np.asarray(panel.dates, dtype="datetime64[D]")
    for j, sym in enumerate(panel.symbols):
        dts = earnings_dates.get(sym)
        if not dts:
            continue
        arr = np.array([np.datetime64(pd.Timestamp(d).date()) for d in dts],
                       dtype="datetime64[D]")
        pos = np.searchsorted(days, arr)
        for p in pos:
            lo, hi = max(0, int(p) - window), min(n, int(p) + window + 1)
            if lo < hi:
                grid[lo:hi, j] = True
    return grid


def _lagged_grid(grid: np.ndarray, lag_start: int, lag_end: int) -> np.ndarray:
    """True on day t when the announcement band was active in [t-lag_start, t-lag_end]."""
    n = grid.shape[0]
    out = np.zeros_like(grid)
    for t in range(n):
        lo, hi = t - lag_start, t - lag_end + 1
        lo, hi = max(0, lo), max(0, min(n, hi))
        if lo < hi:
            out[t] = grid[lo:hi].any(axis=0)
    return out


def classify(events, panel, earnings_dates: dict[str, list], spec: RegimeSpec) -> pd.DataFrame:
    """Attach the regime flags to an event frame."""
    df = events if isinstance(events, pd.DataFrame) else \
        pd.DataFrame([e.__dict__ for e in events])
    if df.empty:
        return df

    grid = announcement_grid(panel, earnings_dates, spec.news_window)
    stale = _lagged_grid(grid, spec.stale_lag_start, spec.stale_lag_end)
    col = {s: j for j, s in enumerate(panel.symbols)}

    ia = df["a"].map(col).to_numpy()
    ib = df["b"].map(col).to_numpy()
    t = df["day"].to_numpy()

    fa, fb = grid[t, ia], grid[t, ib]
    df["n_legs_flagged"] = (fa.astype(int) + fb.astype(int))
    df["regime"] = np.where(df["n_legs_flagged"] > 0, "N", "L")
    df["regime_detail"] = np.select(
        [df["n_legs_flagged"] == 0, df["n_legs_flagged"] == 1],
        ["L_no_news", "N_one_leg"], default="N_both_legs")
    df["stale_flag"] = (stale[t, ia] | stale[t, ib])

    # The placebo carries the SAME marginal rate as the real flag, so a
    # difference between buckets cannot be an artefact of unequal bucket sizes.
    rate = float((df["n_legs_flagged"] > 0).mean())
    rng = np.random.default_rng(spec.placebo_seed)
    df["placebo_flag"] = rng.random(len(df)) < rate

    return df


def coverage_report(panel, earnings_dates: dict[str, list], symbols: list[str]) -> dict:
    """Say out loud how much of the traded set actually has announcement data.

    Partial coverage is worse than none: the names WITHOUT data can only ever
    land in the L bucket, which manufactures exactly the H1 result being
    tested. `FormationSpec.require_earnings_coverage` exists to prevent it, and
    this is the number that proves it worked.
    """
    have = sum(1 for s in symbols if earnings_dates.get(s))
    n = max(1, len(symbols))
    counts = [len(earnings_dates.get(s) or []) for s in symbols]
    return {
        "symbols_traded": len(symbols),
        "with_announcement_dates": have,
        "coverage": round(have / n, 4),
        "median_announcements_per_name": float(np.median(counts)) if counts else 0.0,
        "clean": have == len(symbols),
    }
