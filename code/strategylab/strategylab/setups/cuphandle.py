"""Cup-with-handle detection, built to the published geometry.

The contraction-ladder detector in `vcp.py` looks for one thing: pullbacks
getting smaller. That is a *property* several base patterns happen to share, not
a pattern in itself, which is why it finds shapes that tighten without being
bases. A cup-with-handle is a specific shape with specific proportions, and the
proportions are what make it identifiable:

    left rim ── the high the advance stalled at
       cup   ── a rounded decline of 12-33%, U-shaped not V, over 7-65 weeks
    right rim ── recovery back to within a few percent of the left rim
     handle   ── a shallow drift of 4 days to 4 weeks, no deeper than 15% and
                 no more than half the cup, sitting in the UPPER HALF of the cup
     pivot    ── the handle high; the buy point is a close above it

Two checks carry most of the discriminating power and neither exists in the
ladder detector:

  **U versus V.** A V-shaped recovery is a failed decline, not accumulation.
  Measured here as the share of cup bars spending time in the lower third — a
  rounded bottom lingers there, a spike does not.

  **Handle position.** A handle in the lower half of the cup means the stock
  could not hold its recovery, which is the opposite of what the pattern is
  supposed to indicate. The published rule is explicit that it belongs in the
  upper half.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np

log = logging.getLogger(__name__)


@dataclass
class CupSpec:
    """O'Neil's published proportions, as numbers."""

    # --- cup -----------------------------------------------------------
    min_cup_depth: float = 0.12          # shallower is not a base
    max_cup_depth: float = 0.35          # deeper is damage, not a rest
    min_cup_bars: int = 35               # ~7 weeks
    max_cup_bars: int = 325              # ~65 weeks
    rim_tolerance: float = 0.08          # right rim within this of the left
    min_round_share: float = 0.20        # U not V: share of cup bars low down
    # --- handle --------------------------------------------------------
    min_handle_bars: int = 4
    max_handle_bars: int = 25            # ~4-5 weeks
    max_handle_depth: float = 0.15
    max_handle_frac_of_cup: float = 0.50
    min_handle_position: float = 0.50    # handle low in the UPPER half of the cup
    max_handle_drift: float = 0.02       # drifts lower or sideways, not up
    # --- context -------------------------------------------------------
    min_prior_advance: float = 0.25
    prior_len: int = 120
    max_handle_volume_ratio: float = 0.90    # dry-up through the handle
    min_breakout_volume: float = 1.30


@dataclass
class Cup:
    left_idx: int
    bottom_idx: int
    right_idx: int
    handle_low_idx: int
    trigger: int
    cup_depth: float
    cup_bars: int
    rim_diff: float
    round_share: float
    handle_depth: float
    handle_bars: int
    handle_position: float
    handle_drift: float
    handle_volume_ratio: float
    prior_advance: float
    pivot: float
    fails: list = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not self.fails

    def to_dict(self) -> dict:
        d = dict(self.__dict__)
        d["valid"] = self.valid
        return d


def _round_share(low: np.ndarray, bottom: float, rim: float) -> float:
    """Share of cup bars whose low sits in the bottom third of the cup range.

    The U/V discriminator. A rounded base spends real time near its low; a V
    touches it once and leaves.
    """
    rng = rim - bottom
    if not np.isfinite(rng) or rng <= 0:
        return 0.0
    thresh = bottom + rng / 3.0
    return float(np.mean(low <= thresh))


def find_cup(panel, day: int, col: int, spec: CupSpec) -> Cup | None:
    """Reconstruct the cup and handle ending at the breakout bar `day`.

    Works backwards from the trigger, which is the only direction that is
    well-posed: the pivot is known (the handle high being broken), and the
    structure to its left either fits the proportions or does not.
    """
    h, l = panel.high[:, col], panel.low[:, col]
    c, v = panel.close[:, col], panel.volume[:, col]
    n = len(h)
    if day <= spec.max_cup_bars + spec.prior_len or day >= n:
        return None

    # --- the handle: the pivot is the recent high being broken -----------
    win = h[day - spec.max_handle_bars:day]
    if not np.isfinite(win).all() or win.size == 0:
        return None
    right_idx = day - spec.max_handle_bars + int(np.argmax(win))
    handle_bars = day - right_idx
    if not (spec.min_handle_bars <= handle_bars <= spec.max_handle_bars):
        return None
    pivot = float(h[right_idx])
    hl = l[right_idx:day]
    if hl.size == 0 or not np.isfinite(hl).all():
        return None
    handle_low_idx = right_idx + int(np.argmin(hl))
    handle_low = float(l[handle_low_idx])
    handle_depth = (pivot - handle_low) / pivot if pivot > 0 else np.nan

    # --- the cup: search left for a rim at a similar height --------------
    best = None
    for cup_bars in range(spec.min_cup_bars, spec.max_cup_bars + 1, 5):
        left_idx = right_idx - cup_bars
        if left_idx - spec.prior_len < 0:
            break
        seg_h = h[left_idx:right_idx]
        seg_l = l[left_idx:right_idx]
        if seg_h.size < 10 or not np.isfinite(seg_h).all() or not np.isfinite(seg_l).all():
            continue
        left_rim = float(h[left_idx])
        # The left rim must be the local high of its own neighbourhood, else
        # any bar on the way down qualifies.
        if left_rim < np.nanmax(seg_h[:max(3, cup_bars // 6)]):
            continue
        rim_diff = abs(pivot - left_rim) / left_rim if left_rim > 0 else np.nan
        if not np.isfinite(rim_diff) or rim_diff > spec.rim_tolerance:
            continue
        bottom_idx = left_idx + int(np.argmin(seg_l))
        bottom = float(l[bottom_idx])
        depth = (left_rim - bottom) / left_rim if left_rim > 0 else np.nan
        if not (spec.min_cup_depth <= depth <= spec.max_cup_depth):
            continue
        rs = _round_share(seg_l, bottom, left_rim)
        cand = (rs, cup_bars, left_idx, bottom_idx, left_rim, bottom, depth, rim_diff)
        if best is None or rs > best[0]:
            best = cand
    if best is None:
        return None
    rs, cup_bars, left_idx, bottom_idx, left_rim, bottom, depth, rim_diff = best

    cup_range = left_rim - bottom
    handle_pos = (handle_low - bottom) / cup_range if cup_range > 0 else np.nan
    drift = (c[day - 1] / c[right_idx] - 1.0) if c[right_idx] > 0 else np.nan
    v_cup = float(np.nanmean(v[left_idx:right_idx]))
    v_handle = float(np.nanmean(v[right_idx:day]))
    vr = v_handle / v_cup if v_cup > 0 else np.nan
    prior = (c[left_idx] / c[left_idx - spec.prior_len] - 1.0) \
        if c[left_idx - spec.prior_len] > 0 else np.nan

    fails = []
    if handle_depth > spec.max_handle_depth:
        fails.append("handle %.0f%% deep" % (100 * handle_depth))
    if handle_depth > spec.max_handle_frac_of_cup * depth:
        fails.append("handle > half the cup")
    if not np.isfinite(handle_pos) or handle_pos < spec.min_handle_position:
        fails.append("handle in lower half of cup")
    if np.isfinite(drift) and drift > spec.max_handle_drift:
        fails.append("handle drifts up")
    if rs < spec.min_round_share:
        fails.append("V-shaped, not rounded (%.0f%%)" % (100 * rs))
    if np.isfinite(vr) and vr > spec.max_handle_volume_ratio:
        fails.append("no handle volume dry-up (%.2f)" % vr)
    if not np.isfinite(prior) or prior < spec.min_prior_advance:
        fails.append("prior advance %s" % ("unknown" if not np.isfinite(prior)
                                           else "%+.0f%%" % (100 * prior)))

    return Cup(left_idx=left_idx, bottom_idx=bottom_idx, right_idx=right_idx,
               handle_low_idx=handle_low_idx, trigger=day, cup_depth=depth,
               cup_bars=cup_bars, rim_diff=rim_diff, round_share=rs,
               handle_depth=handle_depth, handle_bars=handle_bars,
               handle_position=handle_pos, handle_drift=drift,
               handle_volume_ratio=vr, prior_advance=prior, pivot=pivot,
               fails=fails)
