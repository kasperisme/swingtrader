"""Qualification screens — the stage before the strategy.

A pre-filter is a PRIOR, and it is deliberately placed outside the genome so
the search cannot switch it off. That distinction matters: given freedom, the
search dismantled four of the eight Minervini criteria, because on any finite
sample a constraint that costs candidates will usually look like it costs
return. Whether that reflects a real discovery or overfitting is not decidable
from the same data that produced it.

Fixing the screen buys two things:

  1. **A smaller hypothesis space.** The deflated Sharpe deflates against the
     expected best of N configurations. Committing to a screen on domain
     grounds removes dimensions from the search, so the same result clears a
     lower bar — a principled restriction is worth real statistical power.
  2. **A stated assumption.** "We only trade Stage-2 uptrends" is a claim
     someone can disagree with, which is better than a threshold that drifted
     to wherever the optimiser left it.

The cost is equally explicit: if the screen is wrong, no amount of downstream
search recovers what it excluded.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class PrefilterResult:
    mask: np.ndarray                       # (n_days, n_symbols) bool
    funnel: dict = field(default_factory=dict)
    name: str = "none"

    def summary(self) -> str:
        rows = [f"Pre-filter '{self.name}' — names surviving each criterion:"]
        for k, v in self.funnel.items():
            rows.append(f"   {k:<34} {v}")
        per_day = self.mask.sum(axis=1)
        live = per_day[per_day > 0]
        if live.size:
            rows.append(f"   {'qualified per day (median)':<34} {int(np.median(live))}")
            rows.append(f"   {'                   (min-max)':<34} "
                        f"{int(live.min())}-{int(live.max())}")
        return "\n".join(rows)


def _ge(mat: np.ndarray, thr: float) -> np.ndarray:
    """>= with NaN as FAIL — unknown must never qualify."""
    return np.greater_equal(mat, thr, out=np.zeros(mat.shape, dtype=bool),
                            where=np.isfinite(mat))


def _le(mat: np.ndarray, thr: float) -> np.ndarray:
    return np.less_equal(mat, thr, out=np.zeros(mat.shape, dtype=bool),
                         where=np.isfinite(mat))


# ----------------------------------------------------------------------
def minervini(bank, rs_min: float = 70.0, name: str = "minervini") -> PrefilterResult:
    """Minervini's Trend Template, all eight criteria, unmodified.

    1. price above the 150- and 200-day MA
    2. 150-day MA above the 200-day MA
    3. 200-day MA rising for at least a month
    4. 50-day MA above both the 150- and 200-day
    5. price above the 50-day MA
    6. price at least 30% above the 52-week low
    7. price within 25% of the 52-week high
    8. relative strength at or above the `rs_min` percentile

    Stated as published rather than parameterised: the point of a prior is that
    it is not tuned on the data it will be judged against.
    """
    close = bank.panel.close
    ok = np.isfinite(close)
    funnel: dict[str, int] = {"priced": int(ok.sum())}

    def step(label: str, cond: np.ndarray) -> None:
        nonlocal ok
        ok = ok & cond
        funnel[label] = int(ok.sum())

    sma50 = bank.get("sma", length=50)
    sma150 = bank.get("sma", length=150)
    sma200 = bank.get("sma", length=200)

    step("1. price > 150d and 200d MA", (close > sma150) & (close > sma200))
    step("2. 150d MA > 200d MA", sma150 > sma200)
    step("3. 200d MA rising 1 month", bank.get("sma_rising", length=200, days=20) > 0)
    step("4. 50d MA > 150d and 200d", (sma50 > sma150) & (sma50 > sma200))
    step("5. price > 50d MA", close > sma50)
    step("6. >= 30% above 52w low", _ge(bank.get("pct_above_52w_low"), 0.30))
    step("7. within 25% of 52w high", _le(bank.get("pct_below_52w_high"), 0.25))
    step(f"8. RS percentile >= {rs_min:.0f}", _ge(bank.get("rs_rank"), rs_min))
    return PrefilterResult(mask=ok, funnel=funnel, name=name)


def minervini_strict(bank) -> PrefilterResult:
    """The template with the RS bar at 80 rather than 70."""
    return minervini(bank, rs_min=80.0, name="minervini_strict")


def stage2(bank) -> PrefilterResult:
    """Weinstein Stage 2 — the advancing phase, and a looser prior.

    Price above a rising 30-week MA, and above its own 10-week MA. Fewer
    conditions than the trend template, so it qualifies far more names; useful
    as the middle point between `none` and `minervini`.
    """
    close = bank.panel.close
    ok = np.isfinite(close)
    funnel = {"priced": int(ok.sum())}

    sma150 = bank.get("sma", length=150)      # ~30 weeks
    sma50 = bank.get("sma", length=50)        # ~10 weeks
    for label, cond in (("price > 30w MA", close > sma150),
                        ("30w MA rising", bank.get("sma_rising", length=150, days=20) > 0),
                        ("price > 10w MA", close > sma50)):
        ok = ok & cond
        funnel[label] = int(ok.sum())
    return PrefilterResult(mask=ok, funnel=funnel, name="stage2")


def accumulation(bank) -> PrefilterResult:
    """Institutional footprint — evidence from VOLUME, not price structure.

    Deliberately orthogonal to the trend screens: a name can be in a textbook
    Stage-2 uptrend on no volume, or be under quiet accumulation before the
    trend is visible. An ensemble of nested trend screens degenerates; an
    ensemble of different evidence types does not.
    """
    close = bank.panel.close
    ok = np.isfinite(close)
    funnel = {"priced": int(ok.sum())}
    for label, cond in (
        ("up/down volume >= 1.15", _ge(bank.get("up_down_volume", length=50), 1.15)),
        ("volume expanding vs 50d", _ge(bank.get("volume_ratio", length=50), 1.0)),
    ):
        ok = ok & cond
        funnel[label] = int(ok.sum())
    return PrefilterResult(mask=ok, funnel=funnel, name="accumulation")


def contraction(bank) -> PrefilterResult:
    """Volatility contraction — the structural precondition every base-breakout
    method is really describing, measured independently of trend or volume."""
    close = bank.panel.close
    ok = np.isfinite(close)
    funnel = {"priced": int(ok.sum())}
    for label, cond in (
        ("ATR20% / ATR50% <= 0.95", _le(bank.get("tightness"), 0.95)),
        ("ADR% within 1.5-15", _ge(bank.get("adr_pct", length=20), 1.5)
         & _le(bank.get("adr_pct", length=20), 15.0)),
    ):
        ok = ok & cond
        funnel[label] = int(ok.sum())
    return PrefilterResult(mask=ok, funnel=funnel, name="contraction")


def near_high(bank) -> PrefilterResult:
    """Proximity to the 52-week high (George & Hwang) — a distinct predictor
    from past return, and the one most often confused with it."""
    close = bank.panel.close
    ok = np.isfinite(close) & _le(bank.get("pct_below_52w_high"), 0.15)
    return PrefilterResult(mask=ok, funnel={"priced": int(np.isfinite(close).sum()),
                                            "within 15% of 52w high": int(ok.sum())},
                           name="near_high")


def none(bank) -> PrefilterResult:
    close = bank.panel.close
    ok = np.isfinite(close)
    return PrefilterResult(mask=ok, funnel={"priced": int(ok.sum())}, name="none")


SCREENS = {
    "none": none,
    "stage2": stage2,
    "minervini": minervini,
    "minervini_strict": minervini_strict,
    "accumulation": accumulation,
    "contraction": contraction,
    "near_high": near_high,
}


def build(spec: str, bank) -> PrefilterResult:
    """Build one screen, or an ensemble of them.

        "minervini"                                  a single screen
        "all:minervini,accumulation"                 every screen must pass
        "any:stage2,near_high"                       at least one
        "2of3:stage2,accumulation,contraction"       k of n

    The k-of-n form is the interesting one, and it only means something when
    the screens measure DIFFERENT evidence — trend, volume and volatility
    structure. Combining nested screens (strict ⊂ minervini ⊂ stage2) just
    reproduces the tightest one while looking like an ensemble.
    """
    spec = (spec or "none").strip()
    if ":" not in spec:
        fn = SCREENS.get(spec)
        if fn is None:
            raise ValueError(f"unknown pre-filter '{spec}'; choose from {sorted(SCREENS)}")
        return fn(bank)

    mode, names = spec.split(":", 1)
    parts = [n.strip() for n in names.split(",") if n.strip()]
    if not parts:
        raise ValueError(f"pre-filter spec '{spec}' names no screens")
    results = [build(n, bank) for n in parts]
    stack = np.stack([r.mask for r in results], axis=0)
    votes = stack.sum(axis=0)

    mode = mode.strip().lower()
    if mode == "all":
        k = len(parts)
    elif mode == "any":
        k = 1
    elif "of" in mode:
        try:
            k = int(mode.split("of")[0])
        except ValueError as exc:
            raise ValueError(f"bad ensemble mode '{mode}' in '{spec}'") from exc
        if not 1 <= k <= len(parts):
            raise ValueError(f"'{mode}' needs 1..{len(parts)} in '{spec}'")
    else:
        raise ValueError(f"unknown ensemble mode '{mode}'; use all / any / KofN")

    mask = votes >= k
    funnel = {f"[{r.name}] qualified": int(r.mask.sum()) for r in results}
    funnel[f"ensemble {k} of {len(parts)}"] = int(mask.sum())
    # Overlap tells you whether the ensemble is doing anything: screens that
    # agree everywhere are one screen wearing three hats.
    if len(parts) > 1:
        both = int((votes == len(parts)).sum())
        anyv = int((votes >= 1).sum())
        funnel["agreement (all / any)"] = (f"{both}/{anyv} = "
                                           f"{both / max(anyv, 1):.0%}")
    return PrefilterResult(mask=mask, funnel=funnel, name=spec)
