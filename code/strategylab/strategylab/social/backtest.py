"""Walk the baseline reconstruction forward through history.

The user's proposal, and it is the right one: build the picture as of date T
using only what was knowable then, walk forward, and see what happened. Standard
train/validate discipline, applied to unstructured data, with timestamps
preventing lookahead.

**But it only applies to part of the pipeline, and being clear about which part
is the whole value of doing it.** Timestamps make the DATA point-in-time. They
do nothing about a language model whose training corpus already contains the
outcome. So the stages split:

    TESTABLE HISTORICALLY          NOT TESTABLE HISTORICALLY
    implied()   pure arithmetic    generate()    model knows the outcome
    entail()    reads given text   priced_in()   partly model judgement
                                   investigate() model knows the outcome

This module tests the first column. It asks one question with no model in it:
**does the revenue path the price requires tell you anything about the forward
return?** If the reconstruction is picking up real mispricing, extreme implied
pessimism should be followed by better-than-implied outcomes.

That is a genuine, uncontaminated test, and it is also the foundation the rest
rests on — a counterfactual is only worth anything if the baseline it is
measured against is meaningful.

**What it cannot rule out.** Survivorship: FMP's fundamentals cover companies
that still exist. And the sample here is short — the point-in-time market-cap
series and filed statements only support a few non-overlapping annual windows,
so this is a handful of observations per name, not a factor study. Treat the
result as a sanity check on the reconstruction, not as evidence of an edge.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from datetime import date, timedelta

import numpy as np

from .implied import implied
from .pit import market_cap_as_of

log = logging.getLogger(__name__)


@dataclass
class Observation:
    ticker: str
    as_of: str
    price: float | None
    implied_cagr: float | None
    trailing_yoy: float | None
    fcf_margin: float | None
    fiscal_year: str
    fwd_price: float | None = None
    fwd_return: float | None = None
    horizon_days: int = 365

    def to_dict(self) -> dict:
        return asdict(self)


def observe(ticker: str, as_of: date, horizon_days: int = 365,
            discount_rate: float = 0.09) -> Observation | None:
    """One (ticker, date) observation: what the price required, and what followed."""
    try:
        r = implied(ticker, as_of=as_of, discount_rate=discount_rate)
    except Exception as exc:                                  # noqa: BLE001
        log.debug("implied failed %s %s: %s", ticker, as_of, exc)
        return None
    f = r.financials
    if f.price is None or r.implied_revenue_cagr is None:
        return None

    fwd_date = as_of + timedelta(days=horizon_days)
    if fwd_date > date.today():
        return None                       # no outcome yet; excluded, not zero-filled
    _, fwd_px = market_cap_as_of(ticker, fwd_date)
    obs = Observation(
        ticker=ticker, as_of=as_of.isoformat(), price=f.price,
        implied_cagr=r.implied_revenue_cagr, trailing_yoy=f.revenue_yoy,
        fcf_margin=f.fcf_margin, fiscal_year=f.fiscal_year,
        fwd_price=fwd_px, horizon_days=horizon_days)
    if fwd_px and f.price:
        obs.fwd_return = fwd_px / f.price - 1.0
    return obs


def run(tickers: list[str], dates: list[date], horizon_days: int = 365,
        log_fn=print) -> list[Observation]:
    out = []
    for i, t in enumerate(tickers, 1):
        for d in dates:
            o = observe(t, d, horizon_days)
            if o and o.fwd_return is not None:
                out.append(o)
        if i % 10 == 0:
            log_fn(f"   {i}/{len(tickers)} tickers, {len(out)} usable observations")
    return out


def summarise(obs: list[Observation], n_buckets: int = 4) -> dict:
    """Forward return by how pessimistic the price was.

    Sorted into buckets by implied CAGR. The hypothesis the reconstruction
    implies is monotonicity: the more decline a price demands, the more room
    there is to beat it. Reported with the spread and a t-statistic, and with
    the sample size in front of both, because a handful of overlapping annual
    observations cannot support much.
    """
    rows = [o for o in obs if o.implied_cagr is not None and o.fwd_return is not None]
    if len(rows) < 8:
        return {"n": len(rows), "note": "too few observations to bucket"}
    rows.sort(key=lambda o: o.implied_cagr)
    buckets, size = [], max(1, len(rows) // n_buckets)
    for b in range(n_buckets):
        lo = b * size
        hi = (b + 1) * size if b < n_buckets - 1 else len(rows)
        seg = rows[lo:hi]
        if not seg:
            continue
        rets = np.array([o.fwd_return for o in seg], dtype=float)
        buckets.append({
            "bucket": b + 1,
            "implied_cagr_range": [round(seg[0].implied_cagr, 4),
                                   round(seg[-1].implied_cagr, 4)],
            "n": len(seg), "mean_fwd_return": float(np.mean(rets)),
            "median_fwd_return": float(np.median(rets))})
    lo_b, hi_b = buckets[0], buckets[-1]
    a = np.array([o.fwd_return for o in rows[:size]], dtype=float)
    z = np.array([o.fwd_return for o in rows[-size:]], dtype=float)
    spread = float(np.mean(a) - np.mean(z))
    se = float(np.sqrt(np.var(a, ddof=1) / len(a) + np.var(z, ddof=1) / len(z)))
    ic = float(np.corrcoef([o.implied_cagr for o in rows],
                           [o.fwd_return for o in rows])[0, 1])
    return {"n": len(rows), "buckets": buckets,
            "most_pessimistic_minus_least": spread,
            "t_stat": (spread / se) if se > 0 else float("nan"),
            "rank_ic_implied_vs_fwd": ic,
            "distinct_tickers": len({o.ticker for o in rows}),
            "distinct_dates": sorted({o.as_of for o in rows}),
            "caveat": ("Observations overlap in time and share market beta, so the "
                       "t-statistic is optimistic. Sanity check on the "
                       "reconstruction, not evidence of an edge.")}


# ----------------------------------------------------------------------
# Testing the reconstruction itself, not the arithmetic behind it.
# ----------------------------------------------------------------------
@dataclass
class VoteObservation:
    """Where the price sat among published models, and what followed."""
    ticker: str
    as_of: str
    price: float
    n_targets: int
    median_gap: float          # price / median target - 1  — the core quantity
    dispersion: float          # (high - low) / median
    n_rejected_bull: int
    n_rejected_bear: int
    max_bull_move: float
    fwd_price: float | None = None
    fwd_return: float | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def observe_vote(ticker: str, as_of: date, all_targets: list,
                 horizon_days: int = 365, min_targets: int = 5
                 ) -> VoteObservation | None:
    """One (ticker, date) reading of the price-as-vote, with its outcome.

    `all_targets` is fetched once per ticker and filtered here by
    `publishedDate` — the whole point being that these rows are genuinely
    point-in-time, unlike the analyst-estimate rows whose closed-year values are
    converged actuals.

    No language model touches this. The quantity under test is arithmetic on
    other people's published numbers, which is why it can be walked forward at
    all: the generative stages cannot, and the leakage probe is what decides
    per-ticker whether they ever could.
    """
    window_start = as_of - timedelta(days=120)
    tg = [t for t in all_targets
          if window_start.isoformat() <= t.published <= as_of.isoformat()]
    if len(tg) < min_targets:
        return None
    _, price = market_cap_as_of(ticker, as_of)
    if not price:
        return None

    vals = np.array([t.target for t in tg], dtype=float)
    med = float(np.median(vals))
    if med <= 0:
        return None
    # Split-adjustment guard, same signature as elsewhere: a median sitting at a
    # clean integer multiple of the price is an unadjusted feed, not a view.
    ratio = med / price
    # Near-integer split factors are the common case, but not the only one:
    # O'Reilly's 15:1 split left a median target 16x the price, and Carvana
    # showed 4.5-6.7x. Checking only 2/3/4 let those through and they landed
    # in the extreme bucket of a backtest, where they looked like the signal.
    # A plain implausibility bound catches whatever the factor list misses.
    for f_ in (2.0, 3.0, 4.0, 5.0, 10.0, 15.0, 20.0,
               0.5, 1.0 / 3.0, 0.25, 0.2, 0.1):
        if abs(ratio / f_ - 1.0) <= 0.08:
            return None

    if ratio > 2.2 or ratio < 0.45:
        return None          # implausible even if it matches no split factor
    moves = vals / price - 1.0
    fwd_date = as_of + timedelta(days=horizon_days)
    if fwd_date > date.today():
        return None
    _, fwd_px = market_cap_as_of(ticker, fwd_date)
    obs = VoteObservation(
        ticker=ticker, as_of=as_of.isoformat(), price=price, n_targets=len(tg),
        median_gap=float(price / med - 1.0),
        dispersion=float((vals.max() - vals.min()) / med),
        n_rejected_bull=int(np.sum(moves >= 0.15)),
        n_rejected_bear=int(np.sum(moves <= -0.15)),
        max_bull_move=float(moves.max()))
    if fwd_px:
        obs.fwd_price = fwd_px
        obs.fwd_return = fwd_px / price - 1.0
    return obs


def run_vote(tickers: list[str], dates: list[date], horizon_days: int = 365,
             log_fn=print) -> list[VoteObservation]:
    from .analyst import targets as fetch_targets
    out = []
    for i, t in enumerate(tickers, 1):
        try:
            allt = fetch_targets(t, as_of=date.today(), window_days=3650)
        except Exception as exc:                              # noqa: BLE001
            log.debug("targets failed %s: %s", t, exc)
            continue
        for d in dates:
            o = observe_vote(t, d, allt, horizon_days)
            if o and o.fwd_return is not None:
                out.append(o)
        if i % 10 == 0:
            log_fn(f"   {i}/{len(tickers)} tickers, {len(out)} observations")
    return out


def summarise_vote(obs: list[VoteObservation], field_name: str = "median_gap",
                   n_buckets: int = 4) -> dict:
    """Forward return bucketed by one reading of the vote.

    The prior from the literature is unflattering and worth stating before
    looking: analyst target-implied upside is weakly to negatively predictive,
    and dispersion of opinion is negatively related to subsequent returns
    (Diether, Malloy & Scherbina). A positive result here would be surprising
    and should be treated as such.
    """
    rows = [o for o in obs if getattr(o, field_name) is not None
            and o.fwd_return is not None]
    if len(rows) < 12:
        return {"n": len(rows), "note": "too few observations"}
    rows.sort(key=lambda o: getattr(o, field_name))
    size = max(1, len(rows) // n_buckets)
    buckets = []
    for b in range(n_buckets):
        lo = b * size
        hi = (b + 1) * size if b < n_buckets - 1 else len(rows)
        seg = rows[lo:hi]
        if not seg:
            continue
        r = np.array([o.fwd_return for o in seg], dtype=float)
        buckets.append({"bucket": b + 1,
                        "range": [round(getattr(seg[0], field_name), 4),
                                  round(getattr(seg[-1], field_name), 4)],
                        "n": len(seg), "mean": float(np.mean(r)),
                        "median": float(np.median(r))})
    a = np.array([o.fwd_return for o in rows[:size]], dtype=float)
    z = np.array([o.fwd_return for o in rows[-size:]], dtype=float)
    spread = float(np.mean(z) - np.mean(a))
    se = float(np.sqrt(np.var(a, ddof=1) / len(a) + np.var(z, ddof=1) / len(z)))
    ic = float(np.corrcoef([getattr(o, field_name) for o in rows],
                           [o.fwd_return for o in rows])[0, 1])
    return {"field": field_name, "n": len(rows), "buckets": buckets,
            "top_minus_bottom": spread, "t_stat": (spread / se) if se > 0 else float("nan"),
            "ic": ic, "distinct_tickers": len({o.ticker for o in rows}),
            "dates": sorted({o.as_of for o in rows}),
            "caveat": ("Overlapping windows and shared market beta make the "
                       "t-statistic optimistic. Prior from the literature is that "
                       "target-implied upside and dispersion are weakly to "
                       "negatively predictive.")}
