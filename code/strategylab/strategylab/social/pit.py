"""Point-in-time reconstruction — what was knowable on a given date.

The whole narrative pipeline reads `date.today()` in a dozen places. To walk it
forward through history — build the baseline as of T, then look at what happened
after T — every one of those reads has to become "as of T", and every input has
to be filtered by **when it became knowable**, not by the period it describes.

Three traps, all of which silently produce a backtest that could not have been
traded:

* **Filing lag.** Crocs' FY2025 income statement describes the year ending
  2025-12-31 but was filed **2026-02-12**. An as-of date of 2026-01-15 that uses
  FY2025 is reading a document that did not exist. `fillingDate` is the key, not
  `date`, and it is why `financials_as_of` sorts on the former.
* **Restatement.** Vendor fundamentals are the CURRENT view of history. FMP does
  not expose the originally-reported figures, so a restated number is
  indistinguishable from the one the market saw. This is not fixable from this
  source and is recorded on the result rather than hidden.
* **Article timestamps.** `published_at` is trustworthy; `created_at` is when
  our ingester saw it, which for a backfill can be months later. Filtering on
  `COALESCE(published_at, created_at)` — as the rest of this package does for
  live use — would let a backfilled article leak into a past window. Here the
  filter is on `published_at` alone, and articles without one are excluded.

**What this does NOT make point-in-time: the model.** Timestamps discipline the
data; they do nothing about a language model whose training corpus already
contains the outcome. Any stage that *generates* or *judges* — the counterfactual
generator, the investigation probability — remains contaminated on any window
before the model's cutoff, and no amount of `as_of` plumbing changes that. The
stages that are genuinely testable historically are the arithmetic ones
(`implied`) and the ones that only read supplied text (`entail`). See
`research/` notes and `AsOf.contamination_note`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta

from ..data import fmp

log = logging.getLogger(__name__)

_V3 = "https://financialmodelingprep.com/api/v3"


@dataclass(frozen=True)
class AsOf:
    """A date, and an honest statement of what it can and cannot control."""

    on: date
    model_cutoff: date | None = None      # the generator's training cutoff

    @property
    def iso(self) -> str:
        return self.on.isoformat()

    def since(self, lookback_days: int) -> str:
        return (self.on - timedelta(days=lookback_days)).isoformat()

    @property
    def data_is_pit(self) -> bool:
        return True

    @property
    def generation_is_pit(self) -> bool:
        """False whenever the generator's training data postdates this date."""
        return bool(self.model_cutoff and self.model_cutoff <= self.on)

    @property
    def contamination_note(self) -> str:
        if self.generation_is_pit:
            return (f"as of {self.iso}: data and generation are both "
                    f"point-in-time (model cutoff {self.model_cutoff}).")
        return (f"as of {self.iso}: DATA is point-in-time, GENERATION IS NOT — "
                f"the model's training corpus"
                + (f" (cutoff {self.model_cutoff})" if self.model_cutoff else "")
                + " postdates this date and may already contain the outcome. "
                  "Arithmetic and text-reading stages are testable here; "
                  "generated theses and probabilities are not.")


# ----------------------------------------------------------------------
def _filed_on_or_before(rows: list[dict], as_of: date) -> list[dict]:
    """Statements available on `as_of`, newest filing first.

    Falls back to `date` + 75 days when a filing date is missing — a deliberate
    over-estimate of the lag so a missing field errs toward excluding data
    rather than admitting it early.
    """
    out = []
    for r in rows or []:
        fd = r.get("fillingDate") or r.get("acceptedDate")
        if fd:
            try:
                filed = date.fromisoformat(str(fd)[:10])
            except ValueError:
                continue
        else:
            try:
                filed = date.fromisoformat(str(r.get("date"))[:10]) + timedelta(days=75)
            except (ValueError, TypeError):
                continue
        if filed <= as_of:
            out.append({**r, "_filed": filed.isoformat()})
    return sorted(out, key=lambda r: r["_filed"], reverse=True)


def market_cap_as_of(ticker: str, as_of: date, window: int = 10) -> tuple[float | None, float | None]:
    """(market cap, price) on the last trading day at or before `as_of`."""
    frm = (as_of - timedelta(days=window)).isoformat()
    try:
        rows = fmp._get(f"{_V3}/historical-market-capitalization/{ticker}",
                        {"from": frm, "to": as_of.isoformat(), "limit": 60}) or []
    except Exception as exc:                                  # noqa: BLE001
        log.debug("historical market cap failed for %s: %s", ticker, exc)
        rows = []
    rows = [r for r in rows if str(r.get("date", ""))[:10] <= as_of.isoformat()]
    if not rows:
        return None, None
    rows.sort(key=lambda r: r["date"], reverse=True)
    mc = float(rows[0].get("marketCap") or 0) or None

    px = None
    try:
        p = fmp._get(f"{_V3}/historical-price-full/{ticker}",
                     {"from": frm, "to": as_of.isoformat()}) or {}
        hist = [h for h in (p.get("historical") or [])
                if str(h.get("date", ""))[:10] <= as_of.isoformat()]
        if hist:
            hist.sort(key=lambda h: h["date"], reverse=True)
            px = float(hist[0].get("close") or 0) or None
    except Exception as exc:                                  # noqa: BLE001
        log.debug("historical price failed for %s: %s", ticker, exc)
    return mc, px


def financials_as_of(ticker: str, as_of: date) -> dict:
    """Income statement, cash flow and balance sheet as filed by `as_of`.

    Returns the two most recent filed annual statements of each so growth rates
    can be computed from what was actually on file.
    """
    def get(ep, params=None):
        try:
            return fmp._get(f"{_V3}/{ep}", params or {}) or []
        except Exception as exc:                              # noqa: BLE001
            log.debug("%s failed for %s: %s", ep, ticker, exc)
            return []

    inc = _filed_on_or_before(
        get(f"income-statement/{ticker}", {"period": "annual", "limit": 12}), as_of)
    cfs = _filed_on_or_before(
        get(f"cash-flow-statement/{ticker}", {"period": "annual", "limit": 12}), as_of)
    bal = _filed_on_or_before(
        get(f"balance-sheet-statement/{ticker}", {"period": "annual", "limit": 12}), as_of)
    mc, px = market_cap_as_of(ticker, as_of)

    latest_bal = bal[0] if bal else {}
    debt = float(latest_bal.get("totalDebt") or 0) or None
    cash = float(latest_bal.get("cashAndCashEquivalents") or 0) or None
    ev = None
    if mc is not None:
        ev = mc + (debt or 0.0) - (cash or 0.0)

    return {"as_of": as_of.isoformat(), "income": inc[:2], "cashflow": cfs[:2],
            "balance": bal[:1], "market_cap": mc, "price": px,
            "total_debt": debt, "cash": cash, "enterprise_value": ev,
            "latest_filed": inc[0]["_filed"] if inc else None,
            "restatement_caveat": (
                "Vendor fundamentals are the CURRENT view of history; originally "
                "reported figures are not available from this source, so a "
                "restated number cannot be distinguished from what the market saw.")}


def segments_as_of(ticker: str, as_of: date, kind: str = "product") -> list:
    """Segment breakdown for the newest fiscal year already FILED at `as_of`.

    Segment endpoints carry no filing date, so the income statement's filing
    date for the same fiscal year is used as the proxy — the segment note is
    published inside that filing.
    """
    from .business import _segments
    years = _segments(ticker, kind)
    if not years:
        return []
    filed = financials_as_of(ticker, as_of)
    if not filed["income"]:
        return []
    fy = str(filed["income"][0].get("calendarYear") or "")[:4]
    # `_segments` returns newest-first by fiscal year; align on the filed year.
    try:
        rows = fmp._get(f"https://financialmodelingprep.com/api/v4/"
                        f"revenue-{kind}-segmentation",
                        {"symbol": ticker, "structure": "flat",
                         "period": "annual"}) or []
    except Exception:                                         # noqa: BLE001
        return years[0] if years else []
    for i, row in enumerate(rows):
        if isinstance(row, dict) and row and str(next(iter(row)))[:4] == fy:
            return years[i] if i < len(years) else []
    return []
