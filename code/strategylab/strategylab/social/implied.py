"""What the price already assumes — the null, reconstructed from the market.

The first version of this pipeline took "the narrative" to be the set of
sentences the financial press had written. That turned out to be the wrong null,
and the failure was visible in the output: five of six Crocs theses matched the
single circulating claim "Crocs is considered fairly valued at $125", and every
Starbucks thesis came back priced-in against loosely-related sentences about
Refreshers. Semantic similarity to journalism measures whether a topic has been
*mentioned*. It cannot measure whether a magnitude has been *assumed*.

The price can. A share price is a statement about the future with a number
attached, and it can be inverted: given what the company earns today and what
the market is paying, what growth and margin path is being taken for granted?
That reconstruction — not the press coverage — is the thing a thesis has to
differ from, and the comparison becomes arithmetic rather than embedding
similarity:

    thesis:   "Beverage growth goes from ~3% to 5-6%"
    implied:  "the price assumes ~2.4% revenue CAGR"
    -> NOT priced in, and by a stateable margin

**This is a reverse DCF, and its assumptions are choices.** Discount rate,
terminal growth and horizon are inputs, not facts, and moving them moves the
answer. They are therefore explicit, defaulted conservatively, and returned with
the result so any implied number is read next to what produced it. The output is
not "the correct expected growth rate" — it is "the growth rate this price
requires under stated assumptions", which is a much weaker and much more honest
claim.

**What it cannot do.** It assumes today's free-cash-flow margin persists, so a
company in the middle of a margin reset (Crocs' HEYDUDE, Starbucks' labour
reinvestment) will have its implied growth understated or overstated depending
on direction. `margin_sensitivity()` reports how much the answer moves under a
different margin, so the reader sees the fragility rather than a single number.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field

from ..data import fmp

log = logging.getLogger(__name__)

_V3 = "https://financialmodelingprep.com/api/v3"


@dataclass
class Financials:
    ticker: str
    price: float | None = None
    market_cap: float | None = None
    enterprise_value: float | None = None
    total_debt: float | None = None
    cash: float | None = None
    revenue: float | None = None
    revenue_yoy: float | None = None
    free_cash_flow: float | None = None
    fcf_margin: float | None = None
    operating_margin: float | None = None
    pe: float | None = None
    ev_sales: float | None = None
    ev_ebitda: float | None = None
    fcf_yield: float | None = None
    fiscal_year: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ImpliedExpectations:
    ticker: str
    financials: Financials
    discount_rate: float
    terminal_growth: float
    horizon_years: int
    implied_revenue_cagr: float | None = None
    implied_fcf_margin_at_zero_growth: float | None = None
    sensitivity: dict = field(default_factory=dict)
    note: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["financials"] = self.financials.to_dict()
        return d

    def brief(self) -> str:
        f = self.financials
        out = [f"{self.ticker} — what the price assumes",
               f"  price ${f.price:,.2f}, market cap ${(f.market_cap or 0)/1e9:.1f}bn, "
               f"EV ${(f.enterprise_value or 0)/1e9:.1f}bn"]
        if f.revenue:
            out.append(f"  FY{f.fiscal_year} revenue ${f.revenue/1e9:.2f}bn "
                       f"({f.revenue_yoy:+.1%} YoY), FCF ${(f.free_cash_flow or 0)/1e9:.2f}bn "
                       f"({(f.fcf_margin or 0):.1%} margin)")
        mult = []
        if f.pe:
            mult.append(f"P/E {f.pe:.1f}x")
        if f.ev_sales:
            mult.append(f"EV/Sales {f.ev_sales:.2f}x")
        if f.ev_ebitda:
            mult.append(f"EV/EBITDA {f.ev_ebitda:.1f}x")
        if f.fcf_yield:
            mult.append(f"FCF yield {f.fcf_yield:.1%}")
        if mult:
            out.append("  " + ", ".join(mult))
        if self.implied_revenue_cagr is not None:
            out.append(f"  => at {self.discount_rate:.1%} discount, "
                       f"{self.terminal_growth:.1%} terminal growth, "
                       f"{self.horizon_years}y horizon and a flat "
                       f"{(f.fcf_margin or 0):.1%} FCF margin, this price requires "
                       f"revenue CAGR of {self.implied_revenue_cagr:+.1%}")
        if self.sensitivity:
            out.append("  sensitivity of that CAGR:")
            for k, v in self.sensitivity.items():
                out.append(f"    {k}: {v:+.1%}" if v is not None else f"    {k}: n/a")
        if self.note:
            out.append(f"  note: {self.note}")
        return "\n".join(out)


# ----------------------------------------------------------------------
def _dcf_value(revenue: float, fcf_margin: float, growth: float, r: float,
               g_term: float, years: int) -> float:
    """PV of a growing FCF stream plus a Gordon terminal value."""
    pv, rev = 0.0, revenue
    for t in range(1, years + 1):
        rev *= (1.0 + growth)
        pv += (rev * fcf_margin) / ((1.0 + r) ** t)
    terminal_fcf = rev * fcf_margin * (1.0 + g_term)
    if r <= g_term:
        return float("inf")
    pv += (terminal_fcf / (r - g_term)) / ((1.0 + r) ** years)
    return pv


def solve_implied_growth(ev: float, revenue: float, fcf_margin: float,
                         r: float, g_term: float, years: int) -> float | None:
    """Bisect for the revenue CAGR whose DCF equals today's enterprise value.

    Bounded to [-30%, +60%]. A solution outside that band means the model does
    not describe the security — a company with negative free cash flow cannot
    be valued this way at all — and None is returned rather than a clipped
    number that would look like an answer.
    """
    if not (ev and revenue and fcf_margin) or fcf_margin <= 0 or r <= g_term:
        return None
    lo, hi = -0.30, 0.60
    if _dcf_value(revenue, fcf_margin, lo, r, g_term, years) > ev:
        return None                      # even shrinking 30%/yr is worth more
    if _dcf_value(revenue, fcf_margin, hi, r, g_term, years) < ev:
        return None                      # even 60%/yr is not enough
    for _ in range(80):
        mid = (lo + hi) / 2.0
        if _dcf_value(revenue, fcf_margin, mid, r, g_term, years) < ev:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def fetch_financials_as_of(ticker: str, as_of) -> Financials:
    """Financials as FILED at `as_of` — the point-in-time path.

    Separate from `fetch_financials` rather than a flag on it because the two
    read different endpoints: the live path uses TTM key-metrics, which have no
    history and would silently import today's numbers into a past window.
    """
    from .pit import financials_as_of
    d = financials_as_of(ticker, as_of)
    inc = d["income"]
    i = inc[0] if inc else {}
    c = d["cashflow"][0] if d["cashflow"] else {}
    rev = float(i.get("revenue") or 0) or None
    revyoy = None
    if rev and len(inc) > 1:
        prior = float(inc[1].get("revenue") or 0)
        revyoy = (rev / prior - 1.0) if prior else None
    fcf = float(c.get("freeCashFlow") or 0) or None
    ebitda = float(i.get("ebitda") or 0) or None
    return Financials(
        ticker=ticker, price=d["price"], market_cap=d["market_cap"],
        enterprise_value=d["enterprise_value"], total_debt=d["total_debt"],
        cash=d["cash"], revenue=rev, revenue_yoy=revyoy, free_cash_flow=fcf,
        fcf_margin=(fcf / rev) if (fcf and rev) else None,
        operating_margin=(float(i.get("operatingIncome") or 0) / rev) if rev else None,
        pe=None,
        ev_sales=(d["enterprise_value"] / rev) if (d["enterprise_value"] and rev) else None,
        ev_ebitda=(d["enterprise_value"] / ebitda)
        if (d["enterprise_value"] and ebitda) else None,
        fcf_yield=(fcf / d["market_cap"]) if (fcf and d["market_cap"]) else None,
        fiscal_year=str(i.get("calendarYear") or i.get("date", ""))[:4])


def fetch_financials(ticker: str) -> Financials:
    def get(ep, params=None):
        try:
            return fmp._get(f"{_V3}/{ep}", params or {}) or []
        except Exception as exc:                              # noqa: BLE001
            log.debug("%s failed for %s: %s", ep, ticker, exc)
            return []

    km = get(f"key-metrics-ttm/{ticker}")
    ev_rows = get(f"enterprise-values/{ticker}", {"limit": 1})
    inc = get(f"income-statement/{ticker}", {"period": "annual", "limit": 2})
    cf = get(f"cash-flow-statement/{ticker}", {"period": "annual", "limit": 1})
    prof = get(f"profile/{ticker}")

    k = km[0] if km else {}
    e = ev_rows[0] if ev_rows else {}
    i = inc[0] if inc else {}
    c = cf[0] if cf else {}
    p = prof[0] if prof else {}

    rev = float(i.get("revenue") or 0) or None
    revyoy = None
    if rev and len(inc) > 1:
        prior = float(inc[1].get("revenue") or 0)
        revyoy = (rev / prior - 1.0) if prior else None
    fcf = float(c.get("freeCashFlow") or 0) or None
    return Financials(
        ticker=ticker,
        price=float(p.get("price") or 0) or None,
        # profile FIRST: `enterprise-values` is a dated annual snapshot, so its
        # marketCapitalization is the value at last fiscal year end. Preferring
        # it printed a $4.6bn market cap next to a current $7.4bn TTM EV and a
        # $122 price — internally inconsistent, and the kind of thing that
        # quietly poisons a ratio. The profile endpoint is live.
        market_cap=float(p.get("mktCap") or e.get("marketCapitalization") or 0) or None,
        enterprise_value=float(k.get("enterpriseValueTTM")
                               or e.get("enterpriseValue") or 0) or None,
        total_debt=float(e.get("addTotalDebt") or 0) or None,
        cash=float(e.get("minusCashAndCashEquivalents") or 0) or None,
        revenue=rev, revenue_yoy=revyoy, free_cash_flow=fcf,
        fcf_margin=(fcf / rev) if (fcf and rev) else None,
        operating_margin=(float(i.get("operatingIncome") or 0) / rev) if rev else None,
        pe=float(k.get("peRatioTTM") or 0) or None,
        ev_sales=float(k.get("evToSalesTTM") or 0) or None,
        ev_ebitda=float(k.get("enterpriseValueOverEBITDATTM") or 0) or None,
        fcf_yield=float(k.get("freeCashFlowYieldTTM") or 0) or None,
        fiscal_year=str(i.get("calendarYear") or i.get("date", ""))[:4])


def implied(ticker: str, discount_rate: float = 0.09,
            terminal_growth: float = 0.025, horizon_years: int = 10,
            fin: Financials | None = None, as_of=None) -> ImpliedExpectations:
    """What the price requires. Pass `as_of` (a date) to reconstruct it
    historically from statements filed by then — the arithmetic here is the one
    stage of the pipeline a backtest can honestly validate, because it contains
    no model judgement to contaminate."""
    if fin is None:
        f = fetch_financials_as_of(ticker, as_of) if as_of else fetch_financials(ticker)
    else:
        f = fin
    cagr = solve_implied_growth(f.enterprise_value or 0, f.revenue or 0,
                                f.fcf_margin or 0, discount_rate,
                                terminal_growth, horizon_years)

    # What FCF margin would justify the price with NO growth at all? The second
    # lens on the same question, and the more useful one when a company is
    # mid-reset: it separates "the market expects growth" from "the market
    # expects margin recovery", which the growth number alone conflates.
    m0 = None
    if f.enterprise_value and f.revenue:
        base = _dcf_value(f.revenue, 1.0, 0.0, discount_rate, terminal_growth,
                          horizon_years)
        m0 = (f.enterprise_value / base) if base else None

    sens = {}
    if f.revenue and f.fcf_margin:
        for label, (r_, g_, m_) in {
            "at 8% discount": (0.08, terminal_growth, f.fcf_margin),
            "at 10% discount": (0.10, terminal_growth, f.fcf_margin),
            "if FCF margin 20% lower": (discount_rate, terminal_growth,
                                        f.fcf_margin * 0.8),
            "if FCF margin 20% higher": (discount_rate, terminal_growth,
                                         f.fcf_margin * 1.2),
        }.items():
            sens[label] = solve_implied_growth(f.enterprise_value or 0, f.revenue,
                                               m_, r_, g_, horizon_years)

    note = ""
    if cagr is None:
        note = ("no solution in [-30%, +60%] — the flat-FCF-margin model does not "
                "describe this security (negative or unstable free cash flow).")
    elif f.revenue_yoy is not None and cagr < f.revenue_yoy - 0.05:
        note = (f"the price requires materially LESS growth ({cagr:+.1%}) than the "
                f"company just delivered ({f.revenue_yoy:+.1%}) — the market is "
                f"pricing deceleration.")
    elif f.revenue_yoy is not None and cagr > f.revenue_yoy + 0.05:
        note = (f"the price requires materially MORE growth ({cagr:+.1%}) than the "
                f"company just delivered ({f.revenue_yoy:+.1%}) — the market is "
                f"pricing acceleration.")
    return ImpliedExpectations(
        ticker=ticker, financials=f, discount_rate=discount_rate,
        terminal_growth=terminal_growth, horizon_years=horizon_years,
        implied_revenue_cagr=cagr, implied_fcf_margin_at_zero_growth=m0,
        sensitivity=sens, note=note)
