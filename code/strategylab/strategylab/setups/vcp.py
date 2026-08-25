"""Base structure — the Volatility Contraction Pattern, measured rather than assumed.

Everything the setup study has tested so far describes the NAME (rs_rank,
momentum, reversal) or the MARKET (regime). Neither can time a trigger, and both
were shown not to: name-level conditioners lifted the pseudo-setup control by
exactly as much as the real book, and 95% of setups already occur with the
benchmark above its 200-day average because the universe screen is itself a
regime filter.

What has never been measured is the shape of the base the price broke out of.
Minervini's actual claim is not "price cleared the pivot" — it is that a
tradeable base shows a *sequence of progressively shallower pullbacks on
progressively lighter volume*, and that the break comes out of the tightest
contraction. The trigger used up to now (`close > 40-bar pivot high` plus a
volume filter) throws all of that away.

These features reconstruct it. They are deliberately literal: pullback depths in
sequence, volume through the base rather than on the break day, how many times
the pivot was rejected, and how far the break extended. Whether any of it
separates a good breakout from a bad one is the open question — and two things
already measured point the wrong way, since breakout-day volume and base
tightness both correlate NEGATIVELY with the hit rate. Go in expecting a null.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd
from scipy import stats

log = logging.getLogger(__name__)

FEATURES = [
    "n_contractions", "contraction_ratio", "contraction_slope",
    "base_depth", "base_duration", "days_since_base_high",
    "volume_dryup", "volume_trend", "pivot_tests",
    "final_tightness", "prior_leg", "breakout_extension",
    # The structure half of the pattern, missing from the first version.
    "higher_lows_share", "higher_lows_slope", "higher_highs_share",
    "higher_highs_slope", "lows_all_higher", "base_drift",
]

DESCRIPTIONS = {
    "n_contractions": "number of distinct pullbacks inside the base",
    "contraction_ratio": "last pullback depth / first — below 1 is a true VCP",
    "contraction_slope": "rank correlation of pullback depth with sequence order",
    "base_depth": "peak-to-trough depth of the whole base",
    "base_duration": "bars from the base high to the breakout",
    "days_since_base_high": "recency of the pivot being tested",
    "volume_dryup": "volume in the last third of the base / the first third",
    "volume_trend": "rank correlation of daily volume with time through the base",
    "pivot_tests": "bars that reached within 2% of the pivot without closing above",
    "final_tightness": "range of the last 5 bars / average range of the base",
    "prior_leg": "the advance that built the base, measured before it",
    "breakout_extension": "how far above the pivot the trigger day closed",
    "higher_lows_share": "share of consecutive swing lows that rose",
    "higher_lows_slope": "rank correlation of swing-low level with sequence order",
    "higher_highs_share": "share of consecutive swing highs that rose",
    "higher_highs_slope": "rank correlation of swing-high level with sequence order",
    "lows_all_higher": "strict Minervini condition: EVERY low above the previous",
    "base_drift": "net price change through the base — a consolidation ends near "
                  "where it began, a trend does not",
}


def _swings(high: np.ndarray, low: np.ndarray, k: int = 2):
    """Alternating swing highs and lows inside a window.

    A bar is a swing high when its high is the maximum of the +/-k bars around
    it. The alternation pass matters: without it a cluster of adjacent highs
    counts as several separate contractions and `n_contractions` measures noise
    rather than structure.
    """
    n = len(high)
    if n < 2 * k + 3:
        return []
    pts = []
    for i in range(k, n - k):
        w_hi = high[i - k:i + k + 1]
        w_lo = low[i - k:i + k + 1]
        if np.isfinite(w_hi).all() and high[i] >= w_hi.max():
            pts.append((i, "H", float(high[i])))
        elif np.isfinite(w_lo).all() and low[i] <= w_lo.min():
            pts.append((i, "L", float(low[i])))
    out = []
    for p in pts:
        if not out:
            out.append(p)
            continue
        if p[1] == out[-1][1]:
            # Same kind twice: keep the more extreme one.
            better = p[2] > out[-1][2] if p[1] == "H" else p[2] < out[-1][2]
            if better:
                out[-1] = p
        else:
            out.append(p)
    return out


def _structure(swings) -> dict:
    """Are the lows making higher lows, and the highs higher highs?

    The contraction ladder alone is NOT a VCP. A sequence of progressively
    shallower pullbacks whose lows are DESCENDING is a descending triangle — a
    distribution pattern that breaks down. What makes it a volatility
    contraction is that each pullback bottoms ABOVE the previous one: demand is
    absorbing supply at successively higher prices.

    Measuring depths without measuring the lows was the original omission here,
    and it admits the mirror image of the pattern it is meant to find.
    """
    lows = [(i, v) for i, k, v in swings if k == "L"]
    highs = [(i, v) for i, k, v in swings if k == "H"]

    def ascending(seq):
        if len(seq) < 2:
            return np.nan, np.nan
        vals = [v for _, v in seq]
        pairs = [(b > a) for a, b in zip(vals, vals[1:])]
        share = float(np.mean(pairs))
        slope = float(stats.spearmanr(np.arange(len(vals)), vals).statistic) \
            if len(vals) >= 3 else (1.0 if pairs[0] else -1.0)
        return share, slope

    lo_share, lo_slope = ascending(lows)
    hi_share, hi_slope = ascending(highs)
    return {
        "higher_lows_share": lo_share,
        "higher_lows_slope": lo_slope,
        "higher_highs_share": hi_share,
        "higher_highs_slope": hi_slope,
        "n_lows": len(lows),
        # The strict Minervini condition: EVERY low above the one before it.
        "lows_all_higher": float(lo_share == 1.0) if np.isfinite(lo_share) else np.nan,
    }


def _pullbacks(swings) -> list[float]:
    """Depth of each high→low leg, as a fraction of the high."""
    depths = []
    for a, b in zip(swings, swings[1:]):
        if a[1] == "H" and b[1] == "L" and a[2] > 0:
            depths.append(float((a[2] - b[2]) / a[2]))
    return [d for d in depths if np.isfinite(d) and d >= 0]


def base_features(panel, setups, base_len: int = 40, prior_len: int = 60,
                  swing_k: int = 2) -> pd.DataFrame:
    """One row of base-structure features per setup, measured strictly before
    the trigger day's close (the breakout bar itself contributes only
    `breakout_extension`)."""
    high, low, close, vol = panel.high, panel.low, panel.close, panel.volume
    rows = []
    for s in setups:
        j, t = s.col, s.day
        lo = t - base_len
        if lo < prior_len:
            continue
        h = high[lo:t, j]
        l = low[lo:t, j]
        c = close[lo:t, j]
        v = vol[lo:t, j]
        if not (np.isfinite(h).sum() > base_len * 0.8 and np.isfinite(v).sum() > base_len * 0.8):
            continue

        pivot = float(np.nanmax(h))
        trough = float(np.nanmin(l))
        sw = _swings(h, l, k=swing_k)
        depths = _pullbacks(sw)

        n_c = len(depths)
        ratio = float(depths[-1] / depths[0]) if n_c >= 2 and depths[0] > 0 else np.nan
        slope = float(stats.spearmanr(np.arange(n_c), depths).statistic) \
            if n_c >= 3 else np.nan

        third = max(3, base_len // 3)
        v_first = float(np.nanmean(v[:third]))
        v_last = float(np.nanmean(v[-third:]))
        dryup = float(v_last / v_first) if v_first > 0 else np.nan
        fin = np.isfinite(v)
        vtrend = float(stats.spearmanr(np.arange(fin.sum()), v[fin]).statistic) \
            if fin.sum() >= 10 else np.nan

        near = np.isfinite(h) & (h >= pivot * 0.98)
        above = np.isfinite(c) & (c > pivot)
        tests = int((near & ~above).sum())

        rng_all = np.nanmean(h - l)
        rng_end = np.nanmean(h[-5:] - l[-5:])
        tight = float(rng_end / rng_all) if rng_all > 0 else np.nan

        idx_hi = int(np.nanargmax(h)) if np.isfinite(h).any() else 0
        since_hi = int(len(h) - idx_hi)

        p0, p1 = close[lo - prior_len, j], close[lo, j]
        prior = float(p1 / p0 - 1.0) if np.isfinite(p0) and np.isfinite(p1) and p0 > 0 else np.nan

        ext = float(close[t, j] / pivot - 1.0) if pivot > 0 and np.isfinite(close[t, j]) \
            else np.nan

        c0, c1 = close[lo, j], close[t - 1, j]
        drift = float(c1 / c0 - 1.0) if np.isfinite(c0) and np.isfinite(c1) and c0 > 0 \
            else np.nan
        struct = _structure(sw)

        rows.append({
            "symbol": s.symbol, "date": s.date, "day": int(t), "col": int(j),
            "n_contractions": n_c,
            "contraction_ratio": ratio,
            "contraction_slope": slope,
            "base_depth": float((pivot - trough) / pivot) if pivot > 0 else np.nan,
            "base_duration": int(base_len),
            "days_since_base_high": since_hi,
            "volume_dryup": dryup,
            "volume_trend": vtrend,
            "pivot_tests": tests,
            "final_tightness": tight,
            "prior_leg": prior,
            "breakout_extension": ext,
            "base_drift": drift,
            **struct,
        })
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------
# A second-generation detector, rebuilt against the published criteria.
#
# The first version had four substantive errors, all found by drawing the
# charts rather than by reading the numbers:
#
#   1. FIXED 40-BAR WINDOW. Real bases run from about five weeks to six months.
#      A fixed window truncates the long ones and manufactures structure inside
#      the short ones. The detector now SEARCHES candidate lengths and keeps the
#      window that best fits.
#   2. RANK-CORRELATION TIGHTENING. `contraction_slope` accepted 21% -> 4% -> 6%
#      -> 3% as "progressively tighter" because the ranks trend down. The
#      criterion is that each pullback is smaller than the one before it, so it
#      is now checked pairwise.
#   3. NO ABSOLUTE DEPTHS. Published examples run 25% -> 15% -> 7%: the first
#      contraction is deep because sellers are still active, the last is tight
#      because the float is in strong hands. A ladder of 5% -> 3% -> 0% has the
#      right shape and none of the meaning, and the old `ratio < 0.6` admitted
#      it. Both ends are now bounded.
#   4. NO PRIOR ADVANCE. A VCP is a rest after a run. Without requiring one, the
#      detector finds contractions in stocks that have gone nowhere.
#
# Swing detection also moves from k=2 to k=3: a +/-2 bar window finds micro
# pivots, and the contractions being counted are meant to be real pullbacks.
# ----------------------------------------------------------------------

BASE_LENGTHS = (25, 40, 60, 90, 130)



class VCPSpec:
    """Published criteria, stated as numbers so they can be argued with."""

    def __init__(self, min_contractions=2, max_contractions=6,
                 min_first_depth=0.10, max_last_depth=0.10, max_ratio=0.50,
                 tighten_tolerance=1.02, require_all_higher_lows=True,
                 min_prior_advance=0.25, max_base_drift=0.15,
                 max_dist_from_pivot=0.08, max_volume_dryup=0.90, swing_k=3):
        self.min_contractions = min_contractions
        self.max_contractions = max_contractions
        self.min_first_depth = min_first_depth      # sellers were still active
        self.max_last_depth = max_last_depth        # the float is in strong hands
        self.max_ratio = max_ratio                  # last/first, roughly halving
        self.tighten_tolerance = tighten_tolerance  # each <= previous * this
        self.require_all_higher_lows = require_all_higher_lows
        self.min_prior_advance = min_prior_advance  # a VCP is a rest after a run
        self.max_base_drift = max_base_drift
        self.max_dist_from_pivot = max_dist_from_pivot   # coiled, not adrift
        self.max_volume_dryup = max_volume_dryup
        self.swing_k = swing_k


def score_base(high, low, close, volume, prior_close, spec):
    """Judge one candidate window against every criterion, and say which failed.

    Returns `valid`, a quality `score` used to choose between windows, and the
    individual failures — a screen that cannot say WHY it rejected something is
    impossible to debug against a chart.
    """
    out = {"valid": False, "score": -1.0, "fails": []}
    if len(high) < 15 or not np.isfinite(high).all() or not np.isfinite(low).all():
        out["fails"].append("window incomplete")
        return out

    sw = _swings(high, low, k=spec.swing_k)
    depths = [d for d in _pullbacks(sw) if d > 0.005]   # a 0% "contraction" is not one
    n = len(depths)
    out["n_contractions"] = n
    out["depths"] = [round(d, 4) for d in depths]

    if not (spec.min_contractions <= n <= spec.max_contractions):
        out["fails"].append("n_contractions=%d" % n)
    if n >= 1 and depths[0] < spec.min_first_depth:
        out["fails"].append("first depth %.1f%% too shallow" % (100 * depths[0]))
    if n >= 1 and depths[-1] > spec.max_last_depth:
        out["fails"].append("last depth %.1f%% too loose" % (100 * depths[-1]))
    if n >= 2:
        ratio = depths[-1] / depths[0]
        out["ratio"] = ratio
        if ratio > spec.max_ratio:
            out["fails"].append("last/first %.2f" % ratio)
        # Pairwise tightening, not a rank correlation.
        if any(b > a * spec.tighten_tolerance for a, b in zip(depths, depths[1:])):
            out["fails"].append("not monotonically tightening")

    st = _structure(sw)
    out.update(st)
    if spec.require_all_higher_lows and st.get("lows_all_higher") != 1.0:
        out["fails"].append("lows not all higher")

    pivot = float(np.nanmax(high))
    trough = float(np.nanmin(low))
    out["base_depth"] = (pivot - trough) / pivot if pivot > 0 else np.nan
    drift = close[-1] / close[0] - 1.0 if close[0] > 0 else np.nan
    out["base_drift"] = drift
    if np.isfinite(drift) and abs(drift) > spec.max_base_drift:
        out["fails"].append("drift %+.0f%%" % (100 * drift))

    dist = (pivot - close[-1]) / pivot if pivot > 0 else np.nan
    out["dist_from_pivot"] = dist
    if np.isfinite(dist) and dist > spec.max_dist_from_pivot:
        out["fails"].append("%.0f%% below pivot at base end" % (100 * dist))

    third = max(3, len(volume) // 3)
    v1, v2 = float(np.nanmean(volume[:third])), float(np.nanmean(volume[-third:]))
    dry = v2 / v1 if v1 > 0 else np.nan
    out["volume_dryup"] = dry
    if np.isfinite(dry) and dry > spec.max_volume_dryup:
        out["fails"].append("volume dry-up %.2f" % dry)

    if np.isfinite(prior_close) and prior_close > 0:
        adv = close[0] / prior_close - 1.0
        out["prior_advance"] = adv
        if adv < spec.min_prior_advance:
            out["fails"].append("prior advance %+.0f%%" % (100 * adv))
    else:
        out["fails"].append("prior advance unknown")

    out["valid"] = len(out["fails"]) == 0
    if out["valid"]:
        # Prefer more contractions, a tighter finish, a deeper dry-up.
        out["score"] = n + (1.0 - out.get("ratio", 1.0)) + (1.0 - min(dry, 1.0))
    return out


def find_vcp(panel, day, col, spec, lengths=BASE_LENGTHS, prior_len=120):
    """Search candidate base lengths and return the best-fitting VCP, if any.

    Fixing the window was the largest single error in the first detector: a base
    that took four months cannot be seen through a forty-bar hole, and a
    forty-bar hole placed on a trending stock will always contain something that
    resembles a contraction.
    """
    h, l = panel.high[:, col], panel.low[:, col]
    c, v = panel.close[:, col], panel.volume[:, col]
    best = None
    for L in lengths:
        b0 = day - L
        if b0 - prior_len < 0:
            continue
        r = score_base(h[b0:day], l[b0:day], c[b0:day], v[b0:day],
                       c[b0 - prior_len], spec)
        r["base_len"] = L
        r["b0"] = b0
        if r["valid"] and (best is None or r["score"] > best["score"]):
            best = r
    return best
