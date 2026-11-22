"""Earnings quality: does reported profit turn into cash?

The narrative stress test (narrative.py) solves the growth a price needs under
a MARGIN. The consensus forward net margin is an accounting number: a company
whose profit is mostly accruals, one-off gains or paid in shares shows a high
margin, so its price "needs" little growth and it collects a large cushion it
has not earned. This module measures that gap from the last three annual
statements filed on or before the scoring date (point-in-time: a statement
filed after `as_of` is never used), and hands narrative.py a QUALITY-ADJUSTED
margin to solve under as well. The verdict rests on the smaller cushion.

    cash_conversion  sum(operating cash flow - stock-based comp) / sum(net income)
    quality_margin   consensus margin x clip(cash_conversion, 0.5, 1)
    hist_net_margin  mean reported net margin over up to 5 filed years (for the
                     mid-cycle rule on cyclicals in narrative.py)

Two guards the first version lacked (council round 3): a conversion below 50%
is usually a working-capital swing in one year (ARM FY25), so the mechanical
cut stops at half the margin and the flag goes to the earnings agent to judge;
and three years of net LOSSES leave nothing to convert, so the name is marked
`loss_making` and narrative.py caps it at fragile instead of silently keeping
the full consensus margin.

Why conversion and not the FCF margin. FCF subtracts capex, and capex is
investment, not bad earnings: solving under the FCF margin sends every
company in a build-out (FSLR's factories, AMZN's data centres, GM's loan
book) to "drowns" — the artefact the first stress run already hit. Earnings
QUALITY is whether reported profit arrives as operating cash; stock-based pay
is subtracted because it is added back to operating cash but is not cash.

    cash_margin    sum(FCF) / sum(revenue), last 3 fiscal years (shown, not used)
    cfo_to_ni      sum(operating cash flow) / sum(net income)  (NI > 0 only)
    accruals       (net income - operating cash flow) / avg total assets, latest year
    sbc_to_revenue sum(stock-based comp) / sum(revenue)
    share_growth   diluted share count, annualised over the years available
    one_off_share  non-operating income (ex interest) / pre-tax income, latest
                   year, gains only

Every input is a ratio, so the reporting currency (KRW, TWD, EUR...) cancels.
The thresholds are stated starting points, not values fitted to returns.
"""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path

from .snapshots import FMP_BASE, _fmp_key, _get

log = logging.getLogger(__name__)

YEARS = 3
HIST_YEARS = 5
MIN_CONVERSION = 0.5  # the mechanical cut never takes more than half the margin; deeper is the agent's call
CACHE_DAYS = 7  # annual statements change once a year; refetch weekly
CACHE_DIR = Path(__file__).resolve().parents[2] / "output" / "drawdown" / "statements"

#: (key, label, test) — a test that cannot be computed is skipped, not failed.
THRESHOLDS = {
    "cfo_to_ni": 0.8,        # below: profit is not arriving as cash
    "accruals": 0.10,        # above: earnings rest on accounting estimates
    "sbc_to_revenue": 0.10,  # above: margins flattered by paying staff in shares
    "share_growth": 0.03,    # above: per-share value diluted away
    "one_off_share": 0.25,   # above: one good year flatters the margin
}


# --- fetch (cached) ---------------------------------------------------------
def _cache_path(sym: str) -> Path:
    return CACHE_DIR / f"{sym.replace('/', '_')}.json"


def _fetch_one(sym: str, key: str) -> dict | None:
    path = _cache_path(sym)
    if path.exists():
        try:
            cached = json.loads(path.read_text())
            if date.fromisoformat(cached["fetched"]) >= date.today() - timedelta(days=CACHE_DAYS):
                return cached
        except Exception:  # noqa: BLE001 - a corrupt cache is just refetched
            pass
    try:
        out = {"fetched": date.today().isoformat()}
        for name, ep in (("cf", "cash-flow-statement"), ("inc", "income-statement"), ("bs", "balance-sheet-statement")):
            body = _get(f"{FMP_BASE}/{ep}", {"symbol": sym, "period": "annual", "limit": YEARS + 2, "apikey": key}).json()
            out[name] = body if isinstance(body, list) else []
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(out))
        return out
    except Exception as exc:  # noqa: BLE001
        log.warning("statements %s: %s", sym, exc)
        return None


def fetch_statements(symbols: list[str], workers: int = 6) -> dict[str, dict]:
    key = _fmp_key()
    with ThreadPoolExecutor(workers) as ex:
        return {s: st for s, st in zip(symbols, ex.map(lambda s: _fetch_one(s, key), symbols)) if st}


# --- assess (pure) ----------------------------------------------------------
def _filed(rows: list[dict], as_of: date) -> list[dict]:
    """Annual rows filed on or before as_of, newest first."""
    def filed_on(r):
        d = (r.get("filingDate") or r.get("acceptedDate") or r.get("date") or "")[:10]
        try:
            return date.fromisoformat(d)
        except ValueError:
            return None
    ok = [r for r in rows if (f := filed_on(r)) and f <= as_of]
    return sorted(ok, key=lambda r: r["date"], reverse=True)


def _by_date(rows: list[dict]) -> dict[str, dict]:
    return {r["date"]: r for r in rows}


def _num(r: dict | None, k: str) -> float | None:
    v = (r or {}).get(k)
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _full_year_revenue(inc: list[dict]) -> float | None:
    """Revenue of the latest FULL fiscal year. A fiscal-year change files a short
    transition period (FERG: 8.75B for Aug-Jun against ~30B a year), which must not
    pass for a year in the currency and perimeter checks."""
    for i, r in enumerate(inc):
        nxt = inc[i + 1] if i + 1 < len(inc) else None
        if nxt:
            gap = (date.fromisoformat(str(r["date"])[:10]) - date.fromisoformat(str(nxt["date"])[:10])).days
            rv, nv = _num(r, "revenue"), _num(nxt, "revenue")
            if gap < 300 or (rv is not None and nv and rv < 0.5 * nv):   # short period, or a stub filed as a year
                continue
        return _num(r, "revenue")
    return None


def assess(st: dict | None, as_of: date, consensus_margin: float | None = None) -> dict:
    """Quality metrics and flags for one company. Never raises; missing data -> 'unknown'."""
    empty = {"quality": "unknown", "quality_flags": [], "cash_margin": None, "cfo_to_ni": None, "accruals": None,
             "cash_conversion": None, "quality_margin": None, "hist_net_margin": None, "loss_making": False,
             "sbc_to_revenue": None, "share_growth": None, "one_off_share": None, "quality_years": 0,
             "reported_currency": None, "revenue_last": None, "share_step": None}
    if not st:
        return empty
    cf, inc, bs = (_filed(st.get(k) or [], as_of) for k in ("cf", "inc", "bs"))
    inc_d, bs_d = _by_date(inc), _by_date(bs)
    years = [r for r in cf if r["date"] in inc_d][:YEARS]
    if not years:
        return empty
    rev = sum(_num(inc_d[r["date"]], "revenue") or 0 for r in years)
    fcf_vals = [_num(r, "freeCashFlow") for r in years]
    fcf = sum((v if v is not None else (_num(r, "operatingCashFlow") or 0) + (_num(r, "capitalExpenditure") or 0))
              for v, r in zip(fcf_vals, years))
    cfo = sum(_num(r, "operatingCashFlow") or 0 for r in years)
    ni = sum(_num(inc_d[r["date"]], "netIncome") or 0 for r in years)
    sbc = sum(_num(r, "stockBasedCompensation") or 0 for r in years)
    out = dict(empty, quality_years=len(years))
    out["reported_currency"] = (inc[0].get("reportedCurrency") if inc else None)
    out["revenue_last"] = _full_year_revenue(inc)
    if rev > 0:
        out["cash_margin"] = fcf / rev
        out["sbc_to_revenue"] = sbc / rev
    if ni > 0:
        out["cfo_to_ni"] = cfo / ni
        out["cash_conversion"] = (cfo - sbc) / ni
        if consensus_margin is not None:
            out["quality_margin"] = consensus_margin * max(MIN_CONVERSION, min(1.0, out["cash_conversion"]))
    else:
        out["loss_making"] = True
    hist = [(_num(r, "netIncome"), _num(r, "revenue")) for r in inc[:HIST_YEARS]]
    hist = [n / v for n, v in hist if n is not None and v]
    if hist:
        out["hist_net_margin"] = sum(hist) / len(hist)
    latest = years[0]
    ta_now = _num(bs_d.get(latest["date"]), "totalAssets")
    prior_bs = [b for b in bs if b["date"] < latest["date"]]
    ta_prev = _num(prior_bs[0], "totalAssets") if prior_bs else None
    avg_ta = (ta_now + ta_prev) / 2 if ta_now and ta_prev else ta_now
    ni_l, cfo_l = _num(inc_d[latest["date"]], "netIncome"), _num(latest, "operatingCashFlow")
    if avg_ta and ni_l is not None and cfo_l is not None:
        out["accruals"] = (ni_l - cfo_l) / avg_ta
    shs = [(_num(inc_d[r["date"]], "weightedAverageShsOutDil") or _num(inc_d[r["date"]], "weightedAverageShsOut")) for r in years]
    if len(shs) >= 2 and shs[0] and shs[-1] and shs[-1] > 0:
        out["share_growth"] = (shs[0] / shs[-1]) ** (1 / (len(shs) - 1)) - 1
        steps = [a / b - 1 for a, b in zip(shs, shs[1:]) if a and b and b > 0]
        out["share_step"] = max(steps) if steps else None
    pretax = _num(inc_d[latest["date"]], "incomeBeforeTax")
    nonop = _num(inc_d[latest["date"]], "nonOperatingIncomeExcludingInterest")
    if pretax and pretax > 0 and nonop is not None:
        out["one_off_share"] = max(0.0, nonop) / pretax

    t = THRESHOLDS
    checks = [
        ("profit not turning into cash", out["cfo_to_ni"] is not None and out["cfo_to_ni"] < t["cfo_to_ni"]),
        ("negative net income over 3 years", ni <= 0),
        ("high accruals", out["accruals"] is not None and out["accruals"] > t["accruals"]),
        ("heavy stock-based pay", out["sbc_to_revenue"] is not None and out["sbc_to_revenue"] > t["sbc_to_revenue"]),
        ("share count diluting", out["share_growth"] is not None and out["share_growth"] > t["share_growth"]),
        ("one-off gains flatter profit", out["one_off_share"] is not None and out["one_off_share"] > t["one_off_share"]),
        ("negative free cash flow over 3 years", out["cash_margin"] is not None and out["cash_margin"] <= 0),
        ("conversion below 50%: mechanical cut capped, judge it",
         out["cash_conversion"] is not None and out["cash_conversion"] < MIN_CONVERSION),
    ]
    flags = [label for label, on in checks if on]
    out["quality_flags"] = flags
    out["quality"] = "clean" if not flags else "watch" if len(flags) == 1 else "weak"
    return out
