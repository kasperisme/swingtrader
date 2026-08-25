"""What is priced in, stated properly — consensus first, then what's left over.

The first reconstruction solved one equation: hold today's FCF margin flat
forever and find the revenue CAGR that justifies the price. It produced a number
that swung nine points on Crocs across three dates because the FCF margin it
anchored on moved with working capital (20.6% -> 22.5% -> 16.3%). A quantity
that unstable cannot be the baseline a thesis is measured against.

Two things fix it, and the second is the one that was simply missing.

**Normalise the margin.** A single year's free cash flow is dominated by
inventory and payables swings. The median of the last several filed years is
what the business actually converts, and it is what belongs in a ten-year
projection.

**Use the consensus.** The most direct evidence of what is priced in is what
analysts publish, and the first version never looked at it. Crocs' consensus has
revenue at $4.10bn / $4.20bn / $4.18bn / $4.56bn through 2029 — roughly +3% a
year — while the price was said to require -2.1%. That gap is the interesting
object, and it was invisible while the model was solving for a single number in
a vacuum.

So the reconstruction becomes the expectations-investing shape: the explicit
forecast period is consensus, and the *residual* is solved for. Three lenses on
the same price, each answering a different question:

* `implied_fade` — accept consensus through the forecast horizon; what growth
  must follow to justify the price? Answers "what is assumed after the part
  analysts cover".
* `implied_discount_rate` — accept consensus AND a normal terminal fade; what
  cost of capital reconciles them to the price? A high number means the market
  is discounting consensus rather than disagreeing with it.
* `consensus_gap` — the plain difference between the consensus path and the
  path the price requires under fixed assumptions.

**Point-in-time warning, and it is severe.** FMP's analyst-estimate rows for
PAST fiscal years are not what analysts forecast at the time — they are the
converged end-of-period consensus. Measured on Crocs: FY2022 -0.2%, FY2023
-0.0%, FY2024 -0.7%, FY2025 -1.0% against actuals. A genuine year-ahead
consensus misses by several percent; these are the answer wearing a forecast's
label. `consensus()` therefore refuses to return rows for fiscal years already
closed at `as_of`, and any historical use of this module is limited to the
years still in the future at that date.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from datetime import date

import numpy as np

from ..data import fmp

log = logging.getLogger(__name__)

_V3 = "https://financialmodelingprep.com/api/v3"


@dataclass
class ConsensusPoint:
    fiscal_year: str
    revenue: float | None
    ebitda: float | None
    eps: float | None
    n_analysts: int | None


@dataclass
class Expectations:
    ticker: str
    price: float | None
    market_cap: float | None
    enterprise_value: float | None
    base_revenue: float | None
    base_fiscal_year: str
    fcf_margin_normalised: float | None
    fcf_margin_latest: float | None
    fcf_margin_years: int = 0
    consensus: list = field(default_factory=list)
    consensus_cagr: float | None = None
    implied_cagr_flat: float | None = None      # the old single-number lens
    implied_fade: float | None = None           # growth after the forecast horizon
    implied_discount_rate: float | None = None  # if consensus is taken at face value
    target_consensus: float | None = None
    target_flag: str = ""
    rating_counts: dict = field(default_factory=dict)
    pit_note: str = ""
    note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    def brief(self) -> str:
        out = [f"{self.ticker} — what the price assumes"]
        if self.price:
            out.append(f"  price ${self.price:,.2f}, EV ${(self.enterprise_value or 0)/1e9:.1f}bn, "
                       f"base FY{self.base_fiscal_year} revenue "
                       f"${(self.base_revenue or 0)/1e9:.2f}bn")
        if self.fcf_margin_normalised is not None:
            out.append(f"  FCF margin: {self.fcf_margin_normalised:.1%} normalised over "
                       f"{self.fcf_margin_years}y (latest year "
                       f"{(self.fcf_margin_latest or 0):.1%} — the single year is "
                       f"working-capital noise)")
        if self.consensus:
            path = ", ".join(f"FY{c.fiscal_year} ${c.revenue/1e9:.2f}bn"
                             for c in self.consensus if c.revenue)
            out.append(f"  CONSENSUS revenue: {path}")
            if self.consensus_cagr is not None:
                out.append(f"  consensus implies {self.consensus_cagr:+.1%} revenue CAGR "
                           f"over the forecast horizon")
        if self.implied_cagr_flat is not None:
            out.append(f"  price requires {self.implied_cagr_flat:+.1%} CAGR if the "
                       f"margin simply holds (no consensus used)")
        if self.implied_fade is not None:
            out.append(f"  => accepting consensus through the horizon, the price "
                       f"requires {self.implied_fade:+.1%} growth thereafter")
        elif self.consensus:
            out.append("  => NO plausible post-horizon growth (-12%..+15%) reconciles "
                       "consensus to this price; the disagreement is with the "
                       "consensus path itself, not with the tail")
        if self.implied_discount_rate is not None:
            out.append(f"  => accepting consensus AND a 2.5% terminal fade, the price "
                       f"implies a {self.implied_discount_rate:.1%} discount rate")
        if self.target_flag:
            out.append(f"  ! {self.target_flag}")
        if self.target_consensus and self.price:
            out.append(f"  sell-side target ${self.target_consensus:,.2f} "
                       f"({self.target_consensus/self.price-1:+.0%} vs price); "
                       f"ratings {self.rating_counts}")
        if self.note:
            out.append(f"  note: {self.note}")
        if self.pit_note:
            out.append(f"  PIT: {self.pit_note}")
        return "\n".join(out)


# ----------------------------------------------------------------------
def normalised_fcf_margin(incomes: list[dict], cashflows: list[dict],
                          years: int = 5) -> tuple[float | None, float | None, int]:
    """(median margin over `years`, latest-year margin, n years used).

    Median rather than mean: one bad working-capital year should not drag the
    anchor, and with four or five observations the median is the robust choice.
    """
    rev = {str(r.get("calendarYear")): float(r.get("revenue") or 0) for r in incomes}
    margins, latest = [], None
    for c in cashflows[:years]:
        fy = str(c.get("calendarYear"))
        r = rev.get(fy)
        f = float(c.get("freeCashFlow") or 0)
        if r and f:
            m = f / r
            margins.append(m)
            if latest is None:
                latest = m
    if not margins:
        return None, None, 0
    return float(np.median(margins)), latest, len(margins)


def consensus(ticker: str, as_of: date | None = None,
              horizon: int = 5) -> tuple[list[ConsensusPoint], str]:
    """Forward consensus, with closed fiscal years refused.

    See the module docstring: FMP's rows for fiscal years already ended are the
    converged figure, not the forecast, so admitting them into a historical
    window hands the model the answer.
    """
    try:
        rows = fmp._get(f"{_V3}/analyst-estimates/{ticker}",
                        {"period": "annual", "limit": 30}) or []
    except Exception as exc:                                  # noqa: BLE001
        log.debug("analyst estimates unavailable for %s: %s", ticker, exc)
        return [], "analyst estimates unavailable"
    cutoff = (as_of or date.today())
    out, dropped = [], 0
    for r in sorted(rows, key=lambda x: str(x.get("date", ""))):
        d = str(r.get("date", ""))[:10]
        if not d:
            continue
        try:
            fy_end = date.fromisoformat(d)
        except ValueError:
            continue
        if fy_end <= cutoff:
            dropped += 1
            continue                       # already closed -> converged, not a forecast
        out.append(ConsensusPoint(
            fiscal_year=d[:4],
            revenue=float(r.get("estimatedRevenueAvg") or 0) or None,
            ebitda=float(r.get("estimatedEbitdaAvg") or 0) or None,
            eps=float(r.get("estimatedEpsAvg") or 0) or None,
            n_analysts=r.get("numberAnalystEstimatedRevenue")))
    note = (f"{dropped} fiscal year(s) already closed at {cutoff} were DROPPED — "
            f"FMP reports those as converged actuals (measured error 0.0-1.0% on "
            f"CROX), not as the forecast that stood at the time.")
    return out[:horizon], note


def _pv(revenues: list[float], margin: float, r: float, g_term: float,
        extra_years: int, fade: float) -> float:
    """PV of an explicit revenue path, then `extra_years` at `fade`, then Gordon."""
    pv, t = 0.0, 0
    rev = 0.0
    for rev in revenues:
        t += 1
        pv += (rev * margin) / ((1.0 + r) ** t)
    for _ in range(extra_years):
        t += 1
        rev *= (1.0 + fade)
        pv += (rev * margin) / ((1.0 + r) ** t)
    if r <= g_term:
        return float("inf")
    pv += ((rev * margin * (1.0 + g_term)) / (r - g_term)) / ((1.0 + r) ** t)
    return pv


def _bisect(fn, lo: float, hi: float, target: float, iters: int = 80) -> float | None:
    """Solve fn(x) == target on [lo, hi], assuming fn is monotone increasing."""
    if fn(lo) > target or fn(hi) < target:
        return None
    for _ in range(iters):
        mid = (lo + hi) / 2.0
        if fn(mid) < target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def build(ticker: str, as_of: date | None = None, discount_rate: float = 0.09,
          terminal_growth: float = 0.025, total_years: int = 10) -> Expectations:
    """The full reconstruction: consensus where it exists, solved residual after."""
    from .implied import solve_implied_growth
    from .pit import financials_as_of

    d = financials_as_of(ticker, as_of or date.today())
    inc, cfs = d["income"], d["cashflow"]

    # Normalisation needs more history than the point-in-time helper returns,
    # so pull the deeper series and clip it to what was filed by `as_of`.
    try:
        from .pit import _filed_on_or_before
        deep_i = _filed_on_or_before(
            fmp._get(f"{_V3}/income-statement/{ticker}",
                     {"period": "annual", "limit": 12}) or [], as_of or date.today())
        deep_c = _filed_on_or_before(
            fmp._get(f"{_V3}/cash-flow-statement/{ticker}",
                     {"period": "annual", "limit": 12}) or [], as_of or date.today())
    except Exception:                                         # noqa: BLE001
        deep_i, deep_c = inc, cfs

    m_norm, m_latest, n_years = normalised_fcf_margin(deep_i, deep_c)
    base_rev = float(inc[0].get("revenue") or 0) if inc else None
    base_fy = str(inc[0].get("calendarYear") or "") if inc else ""
    ev = d["enterprise_value"]

    cons, pit_note = consensus(ticker, as_of)
    cons_cagr = None
    if len(cons) >= 2 and cons[0].revenue and cons[-1].revenue and base_rev:
        n = len(cons)
        cons_cagr = (cons[-1].revenue / base_rev) ** (1.0 / n) - 1.0

    flat = solve_implied_growth(ev or 0, base_rev or 0, m_norm or 0,
                                discount_rate, terminal_growth, total_years)

    fade = disc = None
    revs = [c.revenue for c in cons if c.revenue]
    if ev and revs and m_norm:
        extra = max(0, total_years - len(revs))
        # What growth AFTER the consensus horizon reconciles to the price?
        # Solved over a band that a real business could occupy. Outside it the
        # answer is not "growth of -12.8%" or "+30.7%", it is "no plausible path
        # after the forecast horizon reconciles consensus to this price" — which
        # is the more honest statement and the more useful one, because it says
        # the disagreement is with consensus itself rather than with the tail.
        fade = _bisect(
            lambda g: _pv(revs, m_norm, discount_rate, terminal_growth, extra, g),
            -0.12, 0.15, ev)
        # Or: accept consensus and a normal fade — what discount rate fits?
        # PV falls as r rises, so the search is on the negated function.
        disc_neg = _bisect(
            lambda r: -_pv(revs, m_norm, r, terminal_growth, extra, terminal_growth),
            terminal_growth + 0.005, 0.45, -ev)
        disc = disc_neg

    tgt = ratings = None
    tgt_flag = ""
    if as_of is None:              # sell-side snapshots have no history
        try:
            t = fmp._get("https://financialmodelingprep.com/api/v4/price-target-consensus",
                         {"symbol": ticker}) or []
            tgt = float((t[0] if t else {}).get("targetConsensus") or 0) or None
            # Sanity-check against the price. Monster returned a $97.45 consensus
            # target against a $47.79 price — a clean 2x, which is a stock split
            # the target feed has not been adjusted for, not a doubling call. A
            # target more than 2.5x or less than 0.4x the price is treated as a
            # split mismatch and dropped rather than reported as a view.
            if tgt and d["price"]:
                ratio = tgt / d["price"]
                # Test for a SPLIT FACTOR, not for an extreme ratio. Monster's
                # $97.45 target against a $47.79 price is 2.04x — within 2% of
                # exactly 2.0, which is a split the target feed has not adjusted
                # for. A blanket "too far from price" threshold misses it (2.04
                # is not obviously extreme) and would also reject a genuine
                # deep-value call. Proximity to an integer split factor is the
                # specific signature.
                for f_ in (2.0, 3.0, 4.0, 0.5, 1.0 / 3.0, 0.25):
                    if abs(ratio / f_ - 1.0) <= 0.08:
                        tgt_flag = (f"sell-side target ${tgt:,.2f} is {ratio:.2f}x the "
                                    f"${d['price']:,.2f} price — within 8% of a {f_:g}x "
                                    f"split factor, so almost certainly an unadjusted "
                                    f"target feed rather than a view; dropped.")
                        tgt = None
                        break
                else:
                    if ratio > 3.5 or ratio < 0.3:
                        tgt_flag = (f"sell-side target ${tgt:,.2f} is {ratio:.1f}x the "
                                    f"price — implausible; dropped.")
                        tgt = None
        except Exception:                                     # noqa: BLE001
            pass
        try:
            u = fmp._get("https://financialmodelingprep.com/api/v4/upgrades-downgrades-consensus",
                         {"symbol": ticker}) or []
            u0 = u[0] if u else {}
            ratings = {k: u0.get(k) for k in
                       ("strongBuy", "buy", "hold", "sell", "strongSell", "consensus")
                       if u0.get(k) is not None}
        except Exception:                                     # noqa: BLE001
            pass

    note = ""
    if cons_cagr is not None and flat is not None and cons_cagr - flat > 0.02:
        note = (f"consensus ({cons_cagr:+.1%}) is well above what the price requires "
                f"({flat:+.1%}) — the market is discounting the sell-side, not "
                f"agreeing with it.")
    elif cons_cagr is not None and flat is not None and flat - cons_cagr > 0.02:
        note = (f"the price requires MORE ({flat:+.1%}) than consensus expects "
                f"({cons_cagr:+.1%}) — expectations beyond the published forecast.")

    return Expectations(
        ticker=ticker, price=d["price"], market_cap=d["market_cap"],
        enterprise_value=ev, base_revenue=base_rev, base_fiscal_year=base_fy,
        fcf_margin_normalised=m_norm, fcf_margin_latest=m_latest,
        fcf_margin_years=n_years, consensus=cons, consensus_cagr=cons_cagr,
        implied_cagr_flat=flat, implied_fade=fade, implied_discount_rate=disc,
        target_consensus=tgt, target_flag=tgt_flag, rating_counts=ratings or {},
        pit_note=pit_note, note=note)
