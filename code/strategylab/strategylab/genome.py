"""The strategy genome — the full action space of the search.

A genome is a flat dict of dotted keys. Flat beats nested: every optimiser in
the lab (LLM patches, TPE, mutation, crossover) works on `key -> value` pairs,
and a flat space makes dimension-wise density estimation and patching total.

Every dimension declares its own type, bounds and (for numerics) whether it is
naturally log-scaled. Bounds are hard, so a hallucinated LLM value is clipped,
never crashed on.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
from dataclasses import dataclass
from typing import Any, Iterable


# ----------------------------------------------------------------------
# Dimension types
# ----------------------------------------------------------------------
@dataclass(frozen=True)
class Real:
    lo: float
    hi: float
    log: bool = False
    doc: str = ""
    kind: str = "real"

    def clip(self, v: Any) -> float:
        try:
            v = float(v)
        except (TypeError, ValueError):
            return self.lo
        if math.isnan(v):
            return self.lo
        return min(self.hi, max(self.lo, v))

    def sample(self, rng: random.Random) -> float:
        if self.log:
            return float(math.exp(rng.uniform(math.log(self.lo), math.log(self.hi))))
        return float(rng.uniform(self.lo, self.hi))

    def unit(self, v: float) -> float:
        """Map to [0,1] for distance and density work."""
        if self.log:
            lo, hi, v = math.log(self.lo), math.log(self.hi), math.log(max(float(v), self.lo))
        else:
            lo, hi, v = self.lo, self.hi, float(v)
        return 0.0 if hi == lo else min(1.0, max(0.0, (v - lo) / (hi - lo)))

    def from_unit(self, u: float) -> float:
        u = min(1.0, max(0.0, u))
        if self.log:
            v = math.exp(math.log(self.lo) + u * (math.log(self.hi) - math.log(self.lo)))
        else:
            v = self.lo + u * (self.hi - self.lo)
        # exp(log(...)) round-trips a hair outside the bounds at the endpoints,
        # which then gets clipped somewhere downstream — and a value that is
        # clipped at an unpredictable moment breaks hash stability.
        return float(min(self.hi, max(self.lo, v)))


@dataclass(frozen=True)
class Integer:
    lo: int
    hi: int
    doc: str = ""
    kind: str = "int"

    def clip(self, v: Any) -> int:
        try:
            v = int(round(float(v)))
        except (TypeError, ValueError):
            return self.lo
        return min(self.hi, max(self.lo, v))

    def sample(self, rng: random.Random) -> int:
        return rng.randint(self.lo, self.hi)

    def unit(self, v: int) -> float:
        if self.hi == self.lo:
            return 0.0
        return min(1.0, max(0.0, (float(v) - self.lo) / (self.hi - self.lo)))

    def from_unit(self, u: float) -> int:
        u = min(1.0, max(0.0, u))
        return int(round(self.lo + u * (self.hi - self.lo)))


@dataclass(frozen=True)
class Boolean:
    doc: str = ""
    kind: str = "bool"

    def clip(self, v: Any) -> bool:
        if isinstance(v, str):
            return v.strip().lower() in {"1", "true", "yes", "on"}
        return bool(v)

    def sample(self, rng: random.Random) -> bool:
        return rng.random() < 0.5

    def unit(self, v: bool) -> float:
        return 1.0 if v else 0.0

    def from_unit(self, u: float) -> bool:
        return u >= 0.5


@dataclass(frozen=True)
class Choice:
    options: tuple
    doc: str = ""
    kind: str = "cat"

    def clip(self, v: Any) -> Any:
        return v if v in self.options else self.options[0]

    def sample(self, rng: random.Random) -> Any:
        return rng.choice(list(self.options))

    def unit(self, v: Any) -> float:
        try:
            i = self.options.index(v)
        except ValueError:
            i = 0
        return i / max(1, len(self.options) - 1)

    def from_unit(self, u: float) -> Any:
        i = int(round(min(1.0, max(0.0, u)) * (len(self.options) - 1)))
        return self.options[i]


Dim = Real | Integer | Boolean | Choice


# ----------------------------------------------------------------------
# The search space, grouped by the decision each block makes.
# ----------------------------------------------------------------------
SPACE: dict[str, Dim] = {
    # ---------- what we are allowed to trade -----------------------------
    "universe.source": Choice(("nyse_nasdaq", "sp500", "liquid_mid_large"),
                              doc="Base listing set before liquidity filters."),
    "universe.min_price": Real(2.0, 60.0, log=True,
                               doc="Minimum prior close. Filters penny noise and bad fills."),
    "universe.min_dollar_vol_20d": Real(5e5, 5e7, log=True,
                                        doc="Min 20d median dollar volume — the real capacity constraint."),
    "universe.max_names": Integer(150, 3000, doc="Cap on eligible names per day, ranked by dollar volume."),
    "universe.exclude_sectors": Choice(("none", "no_financials", "no_energy",
                                        "no_utilities_reits", "growth_sectors_only"),
                                       doc="Sector exclusion preset."),
    "universe.min_history_days": Integer(120, 400, doc="Bars of history required before a name is tradable."),

    # ---------- when we are allowed to trade at all ----------------------
    "regime.enabled": Boolean(doc="Gate new entries on a market-regime filter."),
    "regime.benchmark": Choice(("SPY", "QQQ"), doc="Regime reference index."),
    "regime.ma_len": Integer(20, 250, doc="Index must be above this SMA to open new risk."),
    "regime.slope_days": Integer(0, 60, doc="Index SMA must also be rising over N days. 0 = off."),
    "regime.breadth_enabled": Boolean(doc="Additionally require market breadth."),
    "regime.breadth_min": Real(0.15, 0.75, doc="Min share of the universe above its own SMA50."),

    # ---------- eligibility: the NIS / Minervini template, parameterised --
    "gates.price_over_sma200": Boolean(doc="Close > SMA200."),
    "gates.price_over_sma150": Boolean(doc="Close > SMA150."),
    "gates.price_over_sma50": Boolean(doc="Close > SMA50 (drops pullbacks)."),
    "gates.sma_stack": Boolean(doc="SMA50 > SMA150 > SMA200."),
    "gates.sma200_slope_days": Integer(0, 60, doc="SMA200 rising over N days. 0 = off."),
    "gates.min_pct_above_52w_low": Real(0.0, 1.20, doc="Close >= (1+x) * 52w low."),
    "gates.max_pct_below_52w_high": Real(0.03, 0.60, doc="Close within x of the 52w high."),
    "gates.rs_rank_min": Integer(0, 95, doc="Min cross-sectional relative-strength percentile."),
    "gates.adr_min": Real(0.3, 6.0, doc="Min 20d average daily range %."),
    "gates.adr_max": Real(3.0, 25.0, doc="Max 20d average daily range %."),
    "gates.min_up_down_vol": Real(0.5, 2.2, doc="50d up-volume / down-volume (accumulation)."),
    "gates.rs_line_new_high": Boolean(doc="Require the RS line near its own 52w high."),
    "gates.max_dist_from_sma50": Real(2.0, 60.0, doc="Max % extension above SMA50 (chase guard)."),
    "gates.min_base_tightness": Real(0.0, 1.0,
                                     doc="Volatility contraction: require ATR20%/ATR50% <= 1-x."),
    "gates.max_info_discreteness": Real(-0.15, 0.30,
                                        doc="Admit only names whose information arrived "
                                            "continuously (low ID). 0.30 = effectively off."),

    # ---------- eligibility: alternative data (optional overlays) --------
    "gates.use_fundamentals": Boolean(doc="Point-in-time growth overlay, aligned on SEC filing dates."),
    "gates.fund_min_eps_yoy": Real(-0.30, 0.80, doc="Min YoY quarterly EPS growth."),
    "gates.fund_min_rev_yoy": Real(-0.30, 0.60, doc="Min YoY quarterly revenue growth."),
    "gates.fund_min_beats": Integer(0, 4, doc="Consecutive quarterly EPS beats required."),
    "gates.use_news": Boolean(doc="News-impact overlay (proprietary sentiment; recent history only)."),
    "gates.news_lookback_days": Integer(3, 45, doc="Sentiment aggregation window."),
    "gates.news_min_sentiment": Real(-1.0, 0.8, doc="Min mean scored sentiment over the window."),
    "gates.news_min_articles": Integer(0, 15, doc="Min scored articles in the window (coverage floor)."),

    # ---------- the trigger ---------------------------------------------
    "entry.type": Choice(("breakout_pivot", "pullback_to_ma", "rank_only", "volatility_squeeze"),
                         doc="What actually fires the order."),
    "entry.pivot_lookback": Integer(10, 120, doc="Bars defining the pivot high."),
    "entry.breakout_buffer_pct": Real(0.0, 3.0, doc="Close must exceed the pivot by x%."),
    "entry.max_extension_pct": Real(0.5, 20.0, doc="Reject if already x% beyond the pivot."),
    "entry.vol_confirm_ratio": Real(0.7, 3.0, doc="Entry-day volume / 50d average."),
    "entry.max_gap_pct": Real(0.5, 20.0, doc="Skip the fill if the open gaps more than x%."),
    "entry.pullback_ma_len": Integer(10, 50, doc="MA used by the pullback trigger."),
    "entry.pullback_band_pct": Real(0.5, 10.0, doc="Proximity band around that MA."),

    # ---------- ranking: which candidates get the capital -----------------
    "rank.w_rs": Real(0.0, 1.0, doc="Weight: relative-strength percentile."),
    "rank.w_momo_3m": Real(0.0, 1.0, doc="Weight: 63-day return."),
    "rank.w_momo_12m_1m": Real(0.0, 1.0, doc="Weight: classic 12-1 momentum."),
    "rank.w_vol_surge": Real(0.0, 1.0, doc="Weight: entry-day volume surge."),
    "rank.w_tightness": Real(0.0, 1.0, doc="Weight: base tightness (low recent ATR%)."),
    "rank.w_low_vol": Real(0.0, 1.0, doc="Weight: low realised volatility (defensive tilt)."),
    "rank.w_news": Real(0.0, 1.0, doc="Weight: news sentiment (needs the news overlay data)."),
    "rank.w_proximity_high": Real(0.0, 1.0, doc="Weight: closeness to the 52w high."),
    # Literature enhancements — see README.
    "rank.w_continuity": Real(0.0, 1.0,
                              doc="Weight: Frog-in-the-Pan continuity (-ID). Continuous "
                                  "information underreacts and persists (Da/Gurun/Warachka)."),
    "rank.w_residual_momo": Real(0.0, 1.0,
                                 doc="Weight: idiosyncratic momentum, market component "
                                     "stripped out (Blitz/Huij/Martens)."),

    # ---------- exits: where most of the Sharpe actually lives ------------
    "exit.stop_type": Choice(("atr", "pct", "ma", "chandelier"), doc="Initial stop construction."),
    "exit.stop_atr_mult": Real(0.75, 6.0, doc="Initial stop = entry - k * ATR14."),
    "exit.stop_pct": Real(2.0, 25.0, doc="Initial stop = entry * (1 - x%)."),
    "exit.stop_ma_len": Integer(10, 100, doc="Initial stop = a close below this MA."),
    "exit.target_r": Real(0.0, 10.0, doc="Fixed profit target in R. 0 = no target."),
    "exit.trail_enabled": Boolean(doc="Trail the stop once in profit."),
    "exit.trail_after_r": Real(0.0, 4.0, doc="Start trailing after x R of open profit."),
    "exit.trail_atr_mult": Real(1.0, 8.0, doc="Trailing distance in ATR14."),
    "exit.breakeven_after_r": Real(0.0, 3.0, doc="Move the stop to breakeven after x R. 0 = off."),
    "exit.max_hold_days": Integer(3, 160, doc="Hard time stop."),
    "exit.time_stop_days": Integer(0, 40, doc="Soft time-stop window. 0 = off."),
    "exit.time_stop_min_r": Real(-1.0, 1.5, doc="Exit at the soft window if open P&L < x R."),
    "exit.regime_exit": Boolean(doc="Close everything when the regime filter turns off."),
    "exit.exit_on_sma_break": Boolean(doc="Exit on a close below the trend MA."),
    "exit.exit_sma_len": Integer(10, 200, doc="MA used by that exit."),

    # ---------- the short sleeve -------------------------------------------
    # A long-only book can only stand aside in a bear regime, and standing
    # aside earns nothing. The short side is what turns a dead fold into a
    # contributing one — at the cost of borrow, a bounded-profit/unbounded-loss
    # payoff, and squeeze risk that the gates below exist to avoid.
    "short.enabled": Boolean(doc="Trade a short sleeve alongside the long book."),
    "short.max_positions": Integer(0, 15, doc="Concurrent short positions."),
    "short.max_gross": Real(0.0, 0.6, doc="Cap on short exposure as a share of equity."),
    "short.borrow_bps_annual": Real(25.0, 600.0,
                                    doc="Assumed annual borrow cost. Hard-to-borrow names cost far more."),
    "short.max_short_interest": Real(0.05, 0.40,
                                     doc="Skip names already heavily shorted — squeeze risk (proxied by turnover)."),

    # Short eligibility: the mirror of the long trend template.
    "short.price_under_sma200": Boolean(doc="Close < SMA200."),
    "short.price_under_sma50": Boolean(doc="Close < SMA50."),
    "short.sma_stack_down": Boolean(doc="SMA50 < SMA150 < SMA200."),
    "short.rs_rank_max": Integer(5, 60, doc="Max relative-strength percentile (weakness)."),
    "short.max_pct_above_52w_low": Real(0.05, 1.00, doc="Close within x of the 52w low."),
    "short.min_pct_below_52w_high": Real(0.10, 0.80, doc="Close at least x below the 52w high."),
    "short.max_up_down_vol": Real(0.4, 1.3, doc="50d up/down volume below this = distribution."),
    "short.min_price": Real(5.0, 40.0, doc="Higher floor than the long side: cheap shorts squeeze."),
    "short.min_dollar_vol": Real(2e6, 1e8, log=True, doc="Borrowability proxy — thin names are unborrowable."),

    # Short trigger and exits.
    "short.entry_type": Choice(("breakdown_pivot", "failed_rally", "rank_only"),
                               doc="What fires the short."),
    "short.pivot_lookback": Integer(10, 120, doc="Bars defining the pivot low."),
    "short.stop_atr_mult": Real(0.75, 6.0, doc="Initial stop ABOVE entry, in ATR14."),
    "short.target_r": Real(0.0, 8.0, doc="Profit target in R. 0 = none."),
    "short.max_hold_days": Integer(3, 120, doc="Hard time stop for shorts."),
    "short.trail_enabled": Boolean(doc="Ratchet the short stop downward once in profit."),
    "short.trail_atr_mult": Real(1.0, 8.0, doc="Trailing distance in ATR14."),
    "short.cover_on_regime": Boolean(doc="Cover everything when the regime filter turns back ON."),

    # ---------- portfolio construction ------------------------------------
    "pf.max_positions": Integer(3, 30, doc="Concurrent position cap."),
    "pf.sizing": Choice(("risk_atr", "equal_weight", "vol_target"), doc="Position-sizing rule."),
    "pf.risk_pct": Real(0.15, 3.0, doc="Equity risked per trade (risk_atr sizing), %."),
    "pf.target_vol_annual": Real(0.10, 0.60, doc="Per-name annualised vol target (vol_target sizing)."),
    "pf.max_weight": Real(0.04, 0.50, doc="Cap on any single position's weight."),
    "pf.max_new_per_day": Integer(1, 12, doc="New entries allowed per session."),
    "pf.max_sector_positions": Integer(1, 12, doc="Concurrent positions per sector."),
    "pf.max_gross_exposure": Real(0.30, 1.00, doc="Cap on total invested capital."),

    # Risk-managed momentum (Barroso & Santa-Clara 2015). Momentum's own
    # volatility is highly predictable, so scaling exposure by its inverse
    # nearly doubled the Sharpe in their sample (0.53 -> 0.97) and cut excess
    # kurtosis from 18.2 to 2.7. This is a PORTFOLIO-level overlay, distinct
    # from `pf.sizing = vol_target`, which sizes each name by its own vol.
    "pf.vol_scaling": Boolean(doc="Scale the whole book by target vol / realised strategy vol."),
    "pf.vol_target_portfolio": Real(0.05, 0.35, doc="Target annualised portfolio volatility."),
    "pf.vol_lookback": Integer(40, 252, doc="Window for realised strategy volatility."),
    "pf.vol_scale_cap": Real(1.0, 3.0, doc="Cap on the scaling multiplier (leverage limit)."),
}


# Knobs that only matter when a switch is on. Used by the complexity penalty
# (an inactive knob is free) and by the LLM prompt, so it does not waste
# proposals tuning dead parameters.
CONDITIONAL: dict[str, tuple[str, Any]] = {
    "regime.ma_len": ("regime.enabled", True),
    "regime.slope_days": ("regime.enabled", True),
    "regime.benchmark": ("regime.enabled", True),
    "regime.breadth_min": ("regime.breadth_enabled", True),
    "gates.fund_min_eps_yoy": ("gates.use_fundamentals", True),
    "gates.fund_min_rev_yoy": ("gates.use_fundamentals", True),
    "gates.fund_min_beats": ("gates.use_fundamentals", True),
    "gates.news_lookback_days": ("gates.use_news", True),
    "gates.news_min_sentiment": ("gates.use_news", True),
    "gates.news_min_articles": ("gates.use_news", True),
    "entry.pivot_lookback": ("entry.type", "breakout_pivot"),
    "entry.breakout_buffer_pct": ("entry.type", "breakout_pivot"),
    "entry.pullback_ma_len": ("entry.type", "pullback_to_ma"),
    "entry.pullback_band_pct": ("entry.type", "pullback_to_ma"),
    "exit.stop_atr_mult": ("exit.stop_type", "atr"),
    "exit.stop_pct": ("exit.stop_type", "pct"),
    "exit.stop_ma_len": ("exit.stop_type", "ma"),
    "exit.trail_after_r": ("exit.trail_enabled", True),
    "exit.trail_atr_mult": ("exit.trail_enabled", True),
    "exit.exit_sma_len": ("exit.exit_on_sma_break", True),
    "pf.risk_pct": ("pf.sizing", "risk_atr"),
    "pf.target_vol_annual": ("pf.sizing", "vol_target"),
    "pf.vol_target_portfolio": ("pf.vol_scaling", True),
    "pf.vol_lookback": ("pf.vol_scaling", True),
    "pf.vol_scale_cap": ("pf.vol_scaling", True),
    **{k: ("short.enabled", True) for k in (
        "short.max_positions", "short.max_gross", "short.borrow_bps_annual",
        "short.max_short_interest", "short.price_under_sma200",
        "short.price_under_sma50", "short.sma_stack_down", "short.rs_rank_max",
        "short.max_pct_above_52w_low", "short.min_pct_below_52w_high",
        "short.max_up_down_vol", "short.min_price", "short.min_dollar_vol",
        "short.entry_type", "short.stop_atr_mult", "short.target_r",
        "short.max_hold_days", "short.trail_enabled", "short.trail_atr_mult",
        "short.cover_on_regime")},
    "short.pivot_lookback": ("short.entry_type", "breakdown_pivot"),
}

# Blocks group related keys so a mutation is a coherent idea rather than one
# random scalar nudge. The bandit in search.py learns which blocks pay off.
BLOCKS: dict[str, list[str]] = {}
for _k in SPACE:
    BLOCKS.setdefault(_k.split(".")[0], []).append(_k)


# ----------------------------------------------------------------------
# Seed genome = the incumbent NIS Momentum screen expressed in the genome
# language, traded with a plain ATR stop. This is the baseline the search must
# beat, and it is what makes the whole exercise measurable.
# ----------------------------------------------------------------------
DEFAULTS: dict[str, Any] = {
    "universe.source": "nyse_nasdaq",
    "universe.min_price": 10.0,
    "universe.min_dollar_vol_20d": 5e6,
    "universe.max_names": 1500,
    "universe.exclude_sectors": "none",
    "universe.min_history_days": 250,

    "regime.enabled": True,
    "regime.benchmark": "SPY",
    "regime.ma_len": 200,
    "regime.slope_days": 0,
    "regime.breadth_enabled": False,
    "regime.breadth_min": 0.40,

    "gates.price_over_sma200": True,
    "gates.price_over_sma150": True,
    "gates.price_over_sma50": True,
    "gates.sma_stack": True,
    "gates.sma200_slope_days": 20,
    "gates.min_pct_above_52w_low": 0.25,
    "gates.max_pct_below_52w_high": 0.25,
    "gates.rs_rank_min": 80,
    "gates.adr_min": 1.5,
    "gates.adr_max": 15.0,
    "gates.min_up_down_vol": 1.0,
    "gates.rs_line_new_high": False,
    "gates.max_dist_from_sma50": 30.0,
    "gates.min_base_tightness": 0.0,

    "gates.use_fundamentals": False,
    "gates.fund_min_eps_yoy": 0.0,
    "gates.fund_min_rev_yoy": 0.0,
    "gates.fund_min_beats": 3,
    "gates.use_news": False,
    "gates.news_lookback_days": 10,
    "gates.news_min_sentiment": 0.0,
    "gates.news_min_articles": 1,

    "entry.type": "breakout_pivot",
    "entry.pivot_lookback": 50,
    "entry.breakout_buffer_pct": 0.0,
    "entry.max_extension_pct": 5.0,
    "entry.vol_confirm_ratio": 1.4,
    "entry.max_gap_pct": 6.0,
    "entry.pullback_ma_len": 21,
    "entry.pullback_band_pct": 3.0,

    "rank.w_rs": 1.0,
    "rank.w_momo_3m": 0.0,
    "rank.w_momo_12m_1m": 0.0,
    "rank.w_vol_surge": 0.0,
    "rank.w_tightness": 0.0,
    "rank.w_low_vol": 0.0,
    "rank.w_news": 0.0,
    "rank.w_proximity_high": 0.0,

    "exit.stop_type": "atr",
    "exit.stop_atr_mult": 2.5,
    "exit.stop_pct": 8.0,
    "exit.stop_ma_len": 21,
    "exit.target_r": 0.0,
    "exit.trail_enabled": True,
    "exit.trail_after_r": 1.0,
    "exit.trail_atr_mult": 3.0,
    "exit.breakeven_after_r": 0.0,
    "exit.max_hold_days": 60,
    "exit.time_stop_days": 0,
    "exit.time_stop_min_r": 0.0,
    "exit.regime_exit": False,
    "exit.exit_on_sma_break": False,
    "exit.exit_sma_len": 50,

    "pf.max_positions": 10,
    "pf.sizing": "risk_atr",
    "pf.risk_pct": 1.0,
    "pf.target_vol_annual": 0.25,
    "pf.max_weight": 0.20,
    "pf.max_new_per_day": 3,
    "pf.max_sector_positions": 4,
    "pf.max_gross_exposure": 1.00,
    "pf.vol_scaling": False,
    "pf.vol_target_portfolio": 0.12,     # the paper's target
    "pf.vol_lookback": 126,              # ~6 months, as in the paper
    "pf.vol_scale_cap": 2.0,

    "rank.w_continuity": 0.0,
    "rank.w_residual_momo": 0.0,
    "gates.max_info_discreteness": 0.30,   # off

    # Off by default: the incumbent is long-only, and the baseline has to stay
    # the baseline for the comparison to mean anything.
    "short.enabled": False,
    "short.max_positions": 5,
    "short.max_gross": 0.30,
    "short.borrow_bps_annual": 100.0,
    "short.max_short_interest": 0.20,
    "short.price_under_sma200": True,
    "short.price_under_sma50": True,
    "short.sma_stack_down": True,
    "short.rs_rank_max": 20,
    "short.max_pct_above_52w_low": 0.35,
    "short.min_pct_below_52w_high": 0.30,
    "short.max_up_down_vol": 0.90,
    "short.min_price": 10.0,
    "short.min_dollar_vol": 2e7,
    "short.entry_type": "breakdown_pivot",
    "short.pivot_lookback": 50,
    "short.stop_atr_mult": 2.5,
    "short.target_r": 2.0,
    "short.max_hold_days": 40,
    "short.trail_enabled": True,
    "short.trail_atr_mult": 3.0,
    "short.cover_on_regime": True,
}

_missing = set(DEFAULTS) ^ set(SPACE)
assert not _missing, f"DEFAULTS/SPACE mismatch: {sorted(_missing)}"


class Genome(dict):
    """A validated point in SPACE. Always complete, always in bounds."""

    def __init__(self, values: dict | None = None):
        super().__init__()
        base = dict(DEFAULTS)
        if values:
            base.update({k: v for k, v in values.items() if k in SPACE})
        for k, dim in SPACE.items():
            self[k] = dim.clip(base[k])
        self.repair()

    # -- invariants the search must not be able to violate ---------------
    def repair(self) -> "Genome":
        if self["gates.adr_max"] <= self["gates.adr_min"]:
            self["gates.adr_max"] = min(25.0, self["gates.adr_min"] + 2.0)
        if self["exit.trail_atr_mult"] < self["exit.stop_atr_mult"] * 0.4:
            self["exit.trail_atr_mult"] = self["exit.stop_atr_mult"] * 0.4
        if self["exit.time_stop_days"] >= self["exit.max_hold_days"]:
            self["exit.time_stop_days"] = 0
        if self["pf.max_sector_positions"] > self["pf.max_positions"]:
            self["pf.max_sector_positions"] = self["pf.max_positions"]
        # Otherwise the portfolio could never approach its own exposure cap.
        if self["pf.max_weight"] * self["pf.max_positions"] < 0.35:
            self["pf.max_weight"] = min(0.50, 0.35 / max(1, self["pf.max_positions"]) + 0.05)
        if sum(self[k] for k in SPACE if k.startswith("rank.w_")) <= 1e-9:
            self["rank.w_rs"] = 1.0
        if self["short.enabled"]:
            if self["short.max_positions"] < 1:
                self["short.max_positions"] = 1
            if self["short.max_gross"] < 0.02:
                self["short.max_gross"] = 0.02
            if self["short.trail_atr_mult"] < self["short.stop_atr_mult"] * 0.4:
                self["short.trail_atr_mult"] = self["short.stop_atr_mult"] * 0.4
            # A short book cannot exceed the total gross budget.
            if self["short.max_gross"] > self["pf.max_gross_exposure"]:
                self["short.max_gross"] = self["pf.max_gross_exposure"]
        return self

    # -- identity ---------------------------------------------------------
    def canonical(self) -> str:
        """Stable serialisation. Floats are rounded so two numerically
        indistinguishable genomes share a hash — which is what keeps the
        duplicate detector, and therefore the DSR trial count, honest."""
        out = {}
        for k in sorted(SPACE):
            v = self[k]
            out[k] = round(v, 4) if isinstance(v, float) else v
        return json.dumps(out, sort_keys=True, separators=(",", ":"))

    @property
    def hash(self) -> str:
        return hashlib.sha1(self.canonical().encode()).hexdigest()[:16]

    def active_keys(self) -> list[str]:
        out = []
        for k in SPACE:
            cond = CONDITIONAL.get(k)
            if cond and self.get(cond[0]) != cond[1]:
                continue
            out.append(k)
        return out

    def complexity(self) -> float:
        """Effective degrees of freedom in use. Boolean gates that are off, and
        knobs behind an off switch, are free."""
        n = 0.0
        for k in self.active_keys():
            dim, v = SPACE[k], self[k]
            if isinstance(dim, Boolean):
                n += 1.0 if v else 0.0
            elif isinstance(dim, Real) and abs(v - DEFAULTS[k]) < 1e-9:
                n += 0.5
            else:
                n += 1.0
        for k in SPACE:
            if k.startswith("rank.w_") and self[k] < 0.02:
                n -= 0.5
        return max(0.0, n)

    def patched(self, patch: dict | None) -> "Genome":
        g = Genome(dict(self))
        for k, v in (patch or {}).items():
            if k in SPACE:
                g[k] = SPACE[k].clip(v)
        return g.repair()

    def diff(self, other: "Genome") -> dict:
        return {k: (other[k], self[k]) for k in SPACE if other[k] != self[k]}

    def to_unit_vector(self) -> list[float]:
        return [SPACE[k].unit(self[k]) for k in sorted(SPACE)]

    def describe_diff(self, other: "Genome") -> str:
        d = self.diff(other)
        if not d:
            return "(identical)"
        parts = []
        for k, (was, now) in sorted(d.items()):
            fw = f"{was:.4g}" if isinstance(was, float) else str(was)
            fn = f"{now:.4g}" if isinstance(now, float) else str(now)
            parts.append(f"{k}: {fw} -> {fn}")
        return "; ".join(parts)


def default_genome() -> Genome:
    """The incumbent NIS Momentum rules — the search's starting point."""
    return Genome(DEFAULTS)


def random_genome(rng: random.Random) -> Genome:
    return Genome({k: dim.sample(rng) for k, dim in SPACE.items()})


def space_spec(keys: Iterable[str] | None = None) -> list[dict]:
    """Machine-readable space description — handed to the LLM policy."""
    out = []
    for k in (keys or SPACE):
        d = SPACE[k]
        row: dict[str, Any] = {"key": k, "type": d.kind, "doc": d.doc, "default": DEFAULTS[k]}
        if isinstance(d, (Real, Integer)):
            row["min"], row["max"] = d.lo, d.hi
            if isinstance(d, Real) and d.log:
                row["scale"] = "log"
        elif isinstance(d, Choice):
            row["options"] = list(d.options)
        cond = CONDITIONAL.get(k)
        if cond:
            row["active_when"] = f"{cond[0]} == {cond[1]}"
        out.append(row)
    return out


SECTOR_PRESETS: dict[str, set[str]] = {
    "none": set(),
    "no_financials": {"Financial Services", "Financials"},
    "no_energy": {"Energy", "Basic Materials"},
    "no_utilities_reits": {"Utilities", "Real Estate"},
    "growth_sectors_only": {"Utilities", "Real Estate", "Energy",
                            "Consumer Defensive", "Basic Materials",
                            "Financial Services", "Financials"},
}
