"""Narrative stress test: whose priced-in story survives the correction.

Question: for every name with a priced-in reconstruction, does the growth its
share price REQUIRES still fit inside what analysts FORECAST once a correction
cuts those forecasts?

Why not a return forecast. The priced-in pipeline's own walk-forward
(strategylab/research/PRICED-IN-FINDINGS.md §6) found implied CAGR is not a
return signal (most-pessimistic bucket minus least: -10.5%, t = -1.09), and
the judged `priced_in_pct` layer failed its accuracy test (§6.1). So this
module uses only the grounded and assumption-sensitive tiers, and it states a
DESCRIPTION that can be checked as estimates move:

    required  = 10y revenue CAGR the price needs (reverse DCF re-solved at
                today's close; same flat FCF margin / discount / terminal
                growth the reconstruction used)
    supported = 3y consensus revenue CAGR from today's estimate snapshot,
                faded linearly to terminal growth over years 4-10 so it is
                measured on the same 10-year footing
    breakeven = how many points of 3y consensus growth can be cut before
                supported < required

    on_top    breakeven >= bust cut and analysts' median target >= +15%
    holds     breakeven >= FLUSH_CUT
    (bust cut = max(BUST_CUT, half the 3y consensus): a name whose consensus
    calls for +60% loses far more than 10 points in a bust)
    fragile   0 <= breakeven < FLUSH_CUT, or short of consensus at 9% but not at 8%
    drowns    breakeven < 0 at the name's own cost of equity AND one point lower
              (CAPM on the 10y yield, clipped 6-11%: a flat 9% made every slow
              grower drown whatever the correction did)

Earnings quality (quality.py). The margin is the lever: an accounting margin
built on accruals, one-offs or share-based pay makes the price "need" little
growth. So every name is solved twice: at the consensus net margin, and at
that margin cut by how much reported profit failed to arrive as operating
cash (net of stock-based pay) over the last 3 filed years. The group rests on
the SMALLER cushion (`margin_basis` says which). A 'weak' quality grade (2+
red flags) can never be on_top. Capex is NOT a quality failure, so the FCF
margin is shown but never solved under.

FLUSH_CUT / BUST_CUT are stated assumptions, not fitted values. Nothing here
is evidence that the groups will outperform; the sealed list exists so that
can be measured (`grade` once the horizons pass).
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from . import quality as eq
from .events import check as evcheck
from .snapshots import FMP_BASE, ET, _fmp_key, _get, market_date

log = logging.getLogger(__name__)

HORIZON = 10
FLUSH_CUT = 0.03   # 3pp off 3y consensus growth: a flush (2020, Aug 2024)
BUST_CUT = 0.10    # 10pp: a bust (2001, 2008, 2022 tech)
TOP_UPSIDE = 0.15
ERP = 0.045        # equity risk premium for the CAPM cost of equity
R_MIN, R_MAX = 0.06, 0.11
R_FALLBACK_RF = 0.045
ROBUST_STEP = 0.01  # a drowns verdict must also hold one point lower
MIDCYCLE_TRIGGER = 1.25
CYCLICAL_SECTORS = {"Basic Materials", "Energy"}
CYCLICAL_INDUSTRIES = {
    "Semiconductors", "Computer Hardware", "Hardware, Equipment & Parts", "Auto - Manufacturers", "Auto - Parts",
    "Agricultural - Machinery", "Airlines, Airports & Air Services", "Residential Construction",
    "Construction Materials", "Industrial Materials", "Solar", "Marine Shipping", "Trucking", "Steel", "Aluminum",
    "Copper", "Chemicals", "Chemicals - Specialty", "Paper, Lumber & Forest Products", "Packaging & Containers",
    "Auto - Recreational Vehicles", "Furnishings, Fixtures & Appliances"}
EPICENTER = ["NVDA", "AVGO", "AMD", "TSM", "ASML", "MU", "MSFT", "GOOGL", "AMZN", "META", "ORCL"]
LINK_TYPES = ("supplier", "customer", "partner")
LINK_MIN_ARTICLES = 3
OUT_ROOT = Path(__file__).resolve().parents[2] / "output" / "drawdown" / "narrative"


# --- arithmetic (mirrors strategylab/social/implied.py) -----------------------
def dcf_value(revenue: float, margin: float, g: float, r: float, gt: float, years: int = HORIZON) -> float:
    pv, rev = 0.0, revenue
    for t in range(1, years + 1):
        rev *= 1 + g
        pv += rev * margin / (1 + r) ** t
    return pv + rev * margin * (1 + gt) / (r - gt) / (1 + r) ** years


def solve_growth(ev: float, revenue: float, margin: float, r: float, gt: float, clamp: bool = False) -> float | None:
    """Growth that makes the DCF equal `ev`. Outside -30%..+60% it returns None,
    or with `clamp` the bound itself (used for the cash-margin solve, where
    "needs more than +60%" is an answer, not missing data)."""
    if not (ev and revenue and margin) or ev <= 0 or margin <= 0 or r <= gt:
        return None
    lo, hi = -0.30, 0.60
    if dcf_value(revenue, margin, lo, r, gt) > ev:
        return lo if clamp else None
    if dcf_value(revenue, margin, hi, r, gt) < ev:
        return hi if clamp else None
    for _ in range(80):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if dcf_value(revenue, margin, mid, r, gt) < ev else (lo, mid)
    return (lo + hi) / 2


def faded_cagr(g3: float, gt: float, years: int = HORIZON) -> float:
    """3 years at g3, then a straight-line fade to gt by year `years`."""
    level = (1 + g3) ** 3
    steps = years - 3
    for i in range(1, steps + 1):
        level *= 1 + g3 + (gt - g3) * i / steps
    return level ** (1 / years) - 1 if level > 0 else -1.0


def breakeven_cut(g3: float, gt: float, required: float) -> float:
    """Largest cut h to g3 with faded_cagr(g3 - h) >= required (negative = already short)."""
    lo, hi = -0.60, 0.60
    for _ in range(80):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if faded_cagr(g3 - mid, gt) >= required else (lo, mid)
    return (lo + hi) / 2


def consensus_cagr(rows: list[dict], snapshot: date) -> tuple[float | None, int]:
    """Revenue CAGR from the last reported year to the farthest forward year (<= 3)."""
    rows = sorted((r for r in rows if r.get("revenue_avg")), key=lambda r: r["fiscal_date"])
    past = [r for r in rows if date.fromisoformat(r["fiscal_date"]) <= snapshot]
    fwd = [r for r in rows if date.fromisoformat(r["fiscal_date"]) > snapshot][:3]
    if not past or not fwd:
        return None, 0
    b, f = past[-1], fwd[-1]
    n = round((date.fromisoformat(f["fiscal_date"]) - date.fromisoformat(b["fiscal_date"])).days / 365.25)
    if n < 1 or b["revenue_avg"] <= 0 or f["revenue_avg"] <= 0:
        return None, 0
    return (f["revenue_avg"] / b["revenue_avg"]) ** (1 / n) - 1, n


def base_revenue(rows: list[dict], snapshot: date) -> float | None:
    past = sorted((r for r in rows if r.get("revenue_avg") and date.fromisoformat(r["fiscal_date"]) <= snapshot),
                  key=lambda r: r["fiscal_date"])
    return float(past[-1]["revenue_avg"]) if past else None


def consensus_margin(rows: list[dict], snapshot: date) -> float | None:
    """Net margin consensus expects in the farthest forward year (<= 3): the FCF-margin proxy."""
    fwd = sorted((r for r in rows if r.get("revenue_avg") and r.get("net_income_avg") is not None
                  and date.fromisoformat(r["fiscal_date"]) > snapshot), key=lambda r: r["fiscal_date"])[:3]
    if not fwd or fwd[-1]["revenue_avg"] <= 0:
        return None
    m = fwd[-1]["net_income_avg"] / fwd[-1]["revenue_avg"]
    return m if m > 0 else None


def required_now(p: dict, price_now: float, mcap_now: float | None, revenue: float | None,
                 margin: float | None = None, solve_r: float | None = None, clamp: bool = False,
                 method: str | None = None) -> tuple[float | None, str]:
    """Growth today's price requires, solved under `margin` (consensus forward NET margin).

    method "equity" (the default whenever the caller has a same-currency market cap):
    net income is the owners' cash flow, after interest, so it is valued against the
    MARKET CAP at the cost of equity. Council 4 (forensic) found the old basis set a
    net margin against an enterprise value rebuilt from the stored model, which made
    the implied net debt up: FERG $143.5B against $6.0B on its balance sheet, AVGO
    $1,022B against $49B, and a debt charge levied twice on every indebted name.

    Any other method is the legacy basis, kept for non-USD reporters (whose market
    cap would need an FX rate) and so solve dicts sealed before this change still
    re-solve to the numbers they were judged on."""
    if method == "equity":
        if not revenue:
            return None, "no_revenue"
        if not mcap_now or mcap_now <= 0:
            return None, "no_market_cap"
        return solve_growth(mcap_now, revenue, margin, solve_r, p.get("terminal_growth"), clamp=clamp), "equity"
    g0, m, r, gt, p0 = (p.get(k) for k in ("implied_revenue_cagr", "fcf_margin", "discount_rate", "terminal_growth", "price"))
    if None in (g0, m, r, gt, p0) or m <= 0 or not p0:
        return None, "no_cash_flow_model"
    if not revenue:
        return None, "no_revenue"
    ev0 = dcf_value(revenue, m, g0, r, gt)
    method = "net_debt_fixed"
    mcap0 = mcap_now * p0 / price_now if mcap_now else None
    if mcap0 and 0.2 <= mcap0 / ev0 <= 3.0:
        ev_now = ev0 + (mcap_now - mcap0)
    else:  # currency mismatch or bad cap: assume EV moves with the price
        ev_now, method = ev0 * price_now / p0, "ev_scaled"
    return solve_growth(ev_now, revenue, margin or m, solve_r or r, gt, clamp=clamp), method


def cost_of_equity(rf: float | None, beta: float | None) -> float:
    """CAPM, clipped to R_MIN..R_MAX. Missing beta -> 1.0; missing rf -> R_FALLBACK_RF."""
    b = beta if beta is not None and 0 < beta < 4 else 1.0
    return min(R_MAX, max(R_MIN, (rf if rf is not None else R_FALLBACK_RF) + b * ERP))


def midcycle_margin(ticker: dict, consensus: float, hist: float | None) -> float | None:
    """Cyclical industries only: when consensus runs well above the 5-year reported
    average, solve halfway between them. A rule floor; the agents refine it."""
    cyclical = (ticker.get("sector") in CYCLICAL_SECTORS) or (ticker.get("industry") in CYCLICAL_INDUSTRIES)
    if not cyclical or hist is None or consensus is None:
        return None
    if consensus <= max(hist, 0.0) * MIDCYCLE_TRIGGER:
        return None
    return (consensus + max(hist, 0.0)) / 2


# --- inputs ----------------------------------------------------------------
def _all(q, page: int = 1000) -> list[dict]:
    out, start = [], 0
    while True:
        rows = q.range(start, start + page - 1).execute().data or []
        out += rows
        if len(rows) < page:
            return out
        start += page


def load_inputs(sb) -> dict:
    st = sb.schema("swingtrader")
    pi = _all(st.table("research_priced_in").select(
        "ticker,as_of,price,implied_revenue_cagr,discount_rate,terminal_growth,fcf_margin,"
        "n_targets,target_low,target_high,target_median,n_endorsed,n_rejected_bull,n_rejected_bear,"
        "summary_json").order("ticker").order("as_of", desc=True))
    latest: dict[str, dict] = {}
    for r in pi:
        latest.setdefault(r["ticker"], r)
    syms = sorted(latest)
    tick = {}
    for i in range(0, len(syms), 200):
        for r in st.table("tickers").select("symbol,company_name,sector,industry,market_cap,price,beta").in_("symbol", syms[i:i + 200]).execute().data or []:
            tick.setdefault(r["symbol"], r)
    snap = st.table("drawdown_snapshot_runs").select("snapshot_date").eq("status", "complete").order("snapshot_date", desc=True).limit(1).execute().data
    snap_date = snap[0]["snapshot_date"] if snap else None
    est: dict[str, list[dict]] = defaultdict(list)
    if snap_date:
        for i in range(0, len(syms), 150):
            for r in _all(st.table("drawdown_estimate_snapshots").select("symbol,fiscal_date,revenue_avg,eps_avg,net_income_avg,num_analysts_revenue")
                          .eq("snapshot_date", snap_date).in_("symbol", syms[i:i + 150])):
                est[r["symbol"]].append(r)
    links: dict[str, dict] = defaultdict(lambda: {"articles": 0, "with": set()})
    for col_self, col_other in (("from_ticker", "to_ticker"), ("to_ticker", "from_ticker")):
        for r in _all(st.table("ticker_relationship_edges").select(f"{col_self},{col_other},rel_type,article_count")
                      .in_(col_other, EPICENTER).in_("rel_type", list(LINK_TYPES))):
            me = r[col_self]
            if me in EPICENTER:
                continue
            links[me]["articles"] += r.get("article_count") or 0
            links[me]["with"].add(r[col_other])
    rf_row = st.table("drawdown_macro_snapshots").select("value,obs_date").eq("series_id", "FRED:DGS10") \
        .order("obs_date", desc=True).limit(1).execute().data
    rf = float(rf_row[0]["value"]) / 100 if rf_row and rf_row[0].get("value") is not None else None
    return {"priced_in": latest, "tickers": tick, "estimates": est, "snapshot_date": snap_date, "links": links,
            "rf": rf, "rf_date": rf_row[0]["obs_date"] if rf_row else None}


def fetch_prices(symbols: list[str], since: date, workers: int = 6) -> tuple[dict[str, list[dict]], list[str]]:
    key = _fmp_key()

    def one(sym):
        try:
            r = _get(f"{FMP_BASE}/historical-price-eod/light", {"symbol": sym, "from": since.isoformat(), "apikey": key})
            body = r.json()
            return sym, sorted(body, key=lambda x: x["date"]) if isinstance(body, list) and body else None
        except Exception as exc:  # noqa: BLE001
            log.warning("price %s: %s", sym, exc)
            return sym, None

    out, failed = {}, []
    with ThreadPoolExecutor(workers) as ex:
        for sym, bars in ex.map(one, symbols):
            (out.__setitem__(sym, bars) if bars else failed.append(sym))
    return out, failed


# --- scoring ---------------------------------------------------------------
@dataclass
class Row:
    ticker: str
    company: str | None
    sector: str | None
    group: str
    reason: str
    price: float | None
    close_date: str | None
    drawdown_from_peak: float | None
    move_since_model: float | None
    required_cagr: float | None
    consensus_3y: float | None
    supported_cagr: float | None
    breakeven_cut: float | None
    margin_used: float | None
    upside_to_median: float | None
    n_targets: int | None
    targets_predate_drop: bool
    model_as_of: str
    epicenter: bool
    epicenter_linked: bool
    linked_with: str
    beta: float | None
    flags: str
    exposure: str
    crux: str | None
    position: str | None = None
    pays_for: list | None = None
    declines: list | None = None
    thesis: str | None = None
    breaks_if: str | None = None
    rank: int | None = None
    # earnings quality (quality.py): the verdict rests on the smaller cushion
    margin_basis: str | None = None        # 'consensus' | 'quality': which margin decided the group
    breakeven_consensus: float | None = None
    breakeven_quality: float | None = None
    quality_margin: float | None = None    # consensus margin x min(1, cash conversion)
    cash_conversion: float | None = None   # (operating cash flow - SBC) / net income, 3y
    cash_margin: float | None = None       # 3y FCF / revenue: shown, not used (capex is not bad earnings)
    consensus_margin: float | None = None
    quality: str = "unknown"               # clean | watch | weak | unknown
    quality_flags: str = ""
    cfo_to_ni: float | None = None
    accruals: float | None = None
    sbc_to_revenue: float | None = None
    share_growth: float | None = None
    one_off_share: float | None = None
    quality_years: int = 0
    cost_of_equity: float | None = None
    midcycle_margin: float | None = None
    hist_net_margin: float | None = None
    loss_making: bool = False
    sector_pct: float | None = None
    value_basis: str | None = None         # 'equity' (net margin vs market cap) | legacy EV method
    events: str = ""                       # corporate events (events.py) found before any agent ran
    # Everything needed to re-solve this name under a different margin, cut or
    # discount rate (judge.py's what-if). Not written to the database.
    solve: dict | None = None


def hypothesis(group: str, sym: str, px: float, req: float, g3: float, supported: float, be: float, bust: float,
               upside: float | None, n_targets: int | None, margin: float, stale_targets: bool,
               linked: bool, epicenter: bool) -> tuple[str, str]:
    """The narrative in plain words, composed from the numbers only (no model)."""
    need = f"At ${px:,.2f} the price needs revenue to grow {req:+.1%} a year for ten years at a {margin:.0%} margin"
    have = f"analysts forecast {g3:+.1%} a year for the next three"
    floor = g3 - be
    if group in ("on_top", "holds"):
        cushion = (f"Analysts could cut that forecast by {be * 100:.0f} points and the price would still be paid for"
                   + (f", more than a bust-sized cut of {bust * 100:.0f} points." if be >= bust else
                      f", which survives a correction-sized cut but not a bust-sized one ({bust * 100:.0f} points)."))
        rec = ""
        if upside is not None:
            rec = (f" Recovery case: the median of {n_targets} analyst targets sits {upside:+.0%} above the price"
                   + (" (targets set before the drop)." if stale_targets else "."))
        expo = (" It is part of the epicenter, so it will swing with it during the correction even if the story holds."
                if epicenter else " Its business is linked to the epicenter, so expect it to fall with it before the story is tested."
                if linked else "")
        return f"{need}; {have}. {cushion}{rec}{expo}", f"3-year consensus revenue growth falls below {floor:+.1%}"
    if group == "fragile":
        return (f"{need}; {have}. The story is only just paid for: a cut of {max(be, 0) * 100:.0f} points or a higher "
                f"discount rate leaves the price short."), f"3-year consensus revenue growth falls below {floor:+.1%}"
    return (f"{need}; {have}, which supports only {supported:+.1%} once it fades. The price already assumes "
            f"{-be * 100:.0f} points more growth than analysts forecast, before any cut the correction brings."
            f"{' Its business is linked to the epicenter, so a cut there lands here too.' if linked else ''}"), \
        f"already short; it holds only if 3-year consensus rises above {floor:+.1%}"


def _close_on(bars: list[dict], d: str) -> float | None:
    prior = [b for b in bars if b["date"] <= d]
    return float(prior[-1]["price"]) if prior else None


def score(inputs: dict, prices: dict[str, list[dict]], drop_date: date, as_of: date | None = None) -> list[Row]:
    snap = date.fromisoformat(inputs["snapshot_date"])
    as_of = as_of or market_date()
    out = []
    for sym, p in inputs["priced_in"].items():
        t = inputs["tickers"].get(sym, {})
        bars = prices.get(sym)
        link = inputs["links"].get(sym)
        linked = bool(link and link["articles"] >= LINK_MIN_ARTICLES)
        base = dict(ticker=sym, company=t.get("company_name"), sector=t.get("sector"), n_targets=p.get("n_targets"),
                    model_as_of=p["as_of"], targets_predate_drop=date.fromisoformat(p["as_of"]) < drop_date,
                    epicenter=sym in EPICENTER, epicenter_linked=linked,
                    linked_with=",".join(sorted(link["with"])) if linked else "", beta=t.get("beta"), crux=(p.get("summary_json") or {}).get("crux"),
                    position=(p.get("summary_json") or {}).get("position"),
                    pays_for=(p.get("summary_json") or {}).get("pays_for") or [],
                    declines=(p.get("summary_json") or {}).get("declines") or [],
                    exposure=("high" if sym in EPICENTER or (linked and (t.get("beta") or 0) > 1.3)
                              else "medium" if linked or (t.get("beta") or 0) > 1.3 else "low"))
        empty = dict(margin_used=None, price=None, close_date=None, drawdown_from_peak=None, move_since_model=None, required_cagr=None,
                     consensus_3y=None, supported_cagr=None, breakeven_cut=None, upside_to_median=None)
        if not bars:
            out.append(Row(**base, **empty, group="refused", reason="no current price", flags=""))
            continue
        px, cd = float(bars[-1]["price"]), bars[-1]["date"]
        peak = max(float(b["price"]) for b in bars)
        then = _close_on(bars, p["as_of"])
        stats = dict(price=px, close_date=cd, drawdown_from_peak=px / peak - 1,
                     move_since_model=(px / p["price"] - 1) if p.get("price") else None)
        # Price basis: the stored price must match the (split-adjusted) close on as_of.
        if then and p.get("price") and not 0.8 <= p["price"] / then <= 1.25:
            out.append(Row(**base, **{**empty, **stats}, group="refused",
                           reason=f"price basis: stored ${p['price']:.2f} vs adjusted close ${then:.2f} on {p['as_of']} (split?)", flags=""))
            continue
        if (t.get("sector") or "") in ("Financial Services", "Real Estate"):
            out.append(Row(**base, **{**empty, **stats}, group="not_cash_flow",
                           reason=f"{(t.get('sector') or '').lower()}: an FCF/net-margin model does not apply", flags=""))
            continue
        rows = inputs["estimates"].get(sym, [])
        shares = (t["market_cap"] / t["price"]) if t.get("market_cap") and t.get("price") else None
        cm = consensus_margin(rows, snap)
        rev0 = base_revenue(rows, snap)
        mcap = shares * px if shares else None
        q = eq.assess(inputs.get("statements", {}).get(sym), as_of, cm)
        qf = dict(cash_margin=q["cash_margin"], consensus_margin=cm, quality=q["quality"],
                  cash_conversion=q["cash_conversion"], quality_margin=q["quality_margin"],
                  quality_flags="; ".join(q["quality_flags"]), cfo_to_ni=q["cfo_to_ni"], accruals=q["accruals"],
                  sbc_to_revenue=q["sbc_to_revenue"], share_growth=q["share_growth"],
                  one_off_share=q["one_off_share"], quality_years=q["quality_years"])
        g3, _ = consensus_cagr(rows, snap)
        m_cons = cm or p["fcf_margin"]
        # Cost of equity per company (CAPM on the latest 10y yield), not one 9% for all:
        # a flat 9% makes every 2-4% grower "drown" whatever the correction does.
        r_i = cost_of_equity(inputs.get("rf"), t.get("beta"))
        # Equity basis when the market cap and the estimates are in the same currency:
        # dollar reporters whose consensus revenue sits within 0.5-2x the last filed year.
        same_ccy = (q.get("reported_currency") == "USD" and q.get("revenue_last") and rev0
                    and 0.5 <= rev0 / q["revenue_last"] <= 2.0)
        vb = "equity" if same_ccy and mcap else None
        req_cons, method = required_now(p, px, mcap, rev0, m_cons, solve_r=r_i, method=vb)
        if req_cons is None or g3 is None:
            why = ("no consensus revenue" if g3 is None else
                   "price needs growth outside -30%..+60% or FCF <= 0" if method in ("net_debt_fixed", "equity") else method.replace("_", " "))
            out.append(Row(**base, **{**empty, **stats}, **qf, group="not_cash_flow", reason=why, flags=""))
            continue
        gt = p["terminal_growth"]
        supported = faded_cagr(g3, gt)
        be_cons = breakeven_cut(g3, gt, req_cons)
        # Three candidate margins; a lower margin always needs more growth, so the
        # LOWEST one leaves the smallest cushion and decides:
        #   consensus  analysts' farthest-year net margin
        #   quality    consensus cut for profit not arriving as cash (quality.py)
        #   midcycle   cyclical industries only: halfway between consensus and the
        #              5-year reported average when consensus runs >25% above it
        mid = midcycle_margin(t, m_cons, q["hist_net_margin"])
        cands = {"consensus": m_cons}
        if q["quality_margin"] and 0 < q["quality_margin"] < m_cons - 1e-9:
            cands["quality"] = q["quality_margin"]
        if mid and 0 < mid < m_cons - 1e-9:
            cands["midcycle"] = mid
        basis = min(cands, key=cands.get)
        margin = cands[basis]
        req, _ = required_now(p, px, mcap, rev0, margin, solve_r=r_i, clamp=basis != "consensus", method=vb)
        be = breakeven_cut(g3, gt, req)
        be_q = be if basis != "consensus" else None
        upside = (p["target_median"] / px - 1) if p.get("target_median") and (p.get("n_targets") or 0) >= 5 else None
        bust = max(BUST_CUT, g3 / 2)
        fy1 = next((float(r["revenue_avg"]) for r in sorted(rows, key=lambda r: r["fiscal_date"])
                    if r.get("revenue_avg") and date.fromisoformat(r["fiscal_date"]) > snap), None)
        evs = evcheck(sym, inputs.get("events"), p["as_of"], as_of, upside=upside, rev_fy1=fy1,
                      rev_last=q.get("revenue_last"), g3=g3, share_step=q.get("share_step"))
        hard = next((e for e in evs if e["action"] in ("refuse", "not_cash_flow")), None)
        if hard:
            out.append(Row(**base, **{**empty, **stats}, **qf, group="refused" if hard["action"] == "refuse" else "not_cash_flow",
                           reason=f"{hard['kind']}: {hard['note']}", flags="",
                           events="; ".join(f"{e['kind']}: {e['note']}" for e in evs)))
            continue
        if any(e["kind"] == "stale_targets" for e in evs):
            upside = None
        bar_top = any(e["action"] == "bar_top" for e in evs)
        # Drowning must not hinge on the discount rate: re-solve one point lower.
        r_lo = max(R_MIN - 0.01, r_i - ROBUST_STEP)
        req_lo, _ = required_now(p, px, mcap, rev0, margin, solve_r=r_lo, clamp=True, method=vb)
        be8 = breakeven_cut(g3, gt, req_lo) if req_lo is not None else be
        loss = q["loss_making"]
        if be < 0 and be8 < 0:
            group = "drowns"
        elif be < 0:
            group = "fragile"
        elif (be >= bust and upside is not None and upside >= TOP_UPSIDE
              and q["quality"] != "weak" and not loss and not bar_top):
            group = "on_top"
        elif be >= FLUSH_CUT and not loss:
            group = "holds"
        else:
            group = "fragile"
        flags = [f for f, on in [
            ("epicenter", sym in EPICENTER), ("linked to epicenter", linked),
            ("high beta", (t.get("beta") or 0) > 1.3),
            ("targets set before the drop", base["targets_predate_drop"]),
            ("EV scaled (no net-debt check)", method == "ev_scaled"),
            ("non-dollar reporter: legacy enterprise-value basis", method != "equity"),
            *[(f"event: {e['note']}", True) for e in evs],
            ("no consensus margin; today's FCF margin used", cm is None),
            ("thin margin: answer is margin-sensitive", margin < 0.05),
            (f"over-funded only at a {r_i:.1%} discount", be < 0 <= be8),
            ("price funds the consensus story", (p.get("n_endorsed") or 0) * 2 >= (p.get("n_targets") or 99)),
            ("judged on quality-adjusted margin: profit not fully arriving as cash", basis == "quality"),
            ("judged on mid-cycle margin: consensus runs well above the 5-year average", basis == "midcycle"),
            ("at its adjusted margin the price needs more than +60%/yr", req >= 0.60),
            ("held back from on top by earnings quality",
             (q["quality"] == "weak" or loss) and be >= bust and upside is not None and upside >= TOP_UPSIDE),
            ("loss-making over 3 years: capped at fragile", loss and be >= 0),
            ("no statements: earnings quality not checked", q["quality"] == "unknown"),
        ] if on]
        thesis, breaks = hypothesis(group, sym, px, req, g3, supported, be, bust, upside, p.get("n_targets"),
                                    margin, base["targets_predate_drop"], linked, sym in EPICENTER)
        if basis == "quality":
            thesis += (f" Only {q['cash_conversion']:.0%} of its reported profit over the last {q['quality_years']} years "
                       f"arrived as operating cash after stock-based pay, so it is judged at a {margin:.0%} margin, not the "
                       f"{m_cons:.0%} analysts expect ({be_cons * 100:+.0f} points of cushion at the analysts' margin).")
        if basis == "midcycle":
            thesis += (f" Analysts expect a {m_cons:.0%} margin against a {q['hist_net_margin']:.0%} five-year average in a "
                       f"cyclical industry, so it is judged at a mid-cycle {margin:.0%} "
                       f"({be_cons * 100:+.0f} points of cushion at the analysts' margin).")
        if q["quality"] == "weak" or loss:
            thesis += f" Earnings quality is weak: {', '.join(q['quality_flags'])}."
        reason = (f"at a {margin:.0%} {basis} margin and {r_i:.1%} cost of equity the price needs {req:+.1%}/yr for 10y; "
                  f"consensus supports {supported:+.1%} ({g3:+.1%} for 3y, faded); absorbs a {be * 100:+.1f}pt cut")
        solve = {"p": {k: p.get(k) for k in ("implied_revenue_cagr", "fcf_margin", "discount_rate", "terminal_growth", "price")},
                 "price_now": px, "mcap_now": mcap, "revenue": rev0, "g3": g3, "gt": gt, "consensus_margin": cm,
                 "bust_cut": bust, "method": method, "r": r_i, "r_lo": r_lo, "industry": t.get("industry")}
        events_s = "; ".join(f"{e['kind']}: {e['note']}" for e in evs)
        out.append(Row(**base, **stats, **qf, solve=solve, required_cagr=req, consensus_3y=g3, supported_cagr=supported,
                       breakeven_cut=be, margin_used=margin, upside_to_median=upside, thesis=thesis, breaks_if=breaks,
                       group=group, reason=reason, flags="; ".join(flags), margin_basis=basis,
                       breakeven_consensus=be_cons, breakeven_quality=be_q, cost_of_equity=r_i,
                       midcycle_margin=mid, hist_net_margin=q["hist_net_margin"], loss_making=loss,
                       value_basis=method, events=events_s))
    # rank: top/holds by breakeven desc; drowns by shortfall (most negative first)
    order = {"on_top": 0, "holds": 1, "fragile": 2, "drowns": 3, "not_cash_flow": 4, "refused": 5}
    out.sort(key=lambda r: (order[r.group], -(r.breakeven_cut or 0) if r.group != "drowns" else (r.breakeven_cut or 0), r.ticker))
    counters: dict[str, int] = defaultdict(int)
    for r in out:
        counters[r.group] += 1
        r.rank = counters[r.group]
    # Where the cushion sits WITHIN its sector (1 = most cushioned). Book construction
    # ranks on this, so a long/short list is not long tech and short staples by design.
    by_sec: dict[str, list[Row]] = defaultdict(list)
    for r in out:
        if r.breakeven_cut is not None:
            by_sec[r.sector or "?"].append(r)
    for rs in by_sec.values():
        rs.sort(key=lambda r: r.breakeven_cut)
        for i, r in enumerate(rs):
            r.sector_pct = round(i / max(1, len(rs) - 1), 3) if len(rs) > 1 else 0.5
    return out


_DB_FIELDS = ["company", "sector", "rank", "reason", "thesis", "breaks_if", "price", "close_date", "drawdown_from_peak",
              "move_since_model", "required_cagr", "consensus_3y", "supported_cagr", "breakeven_cut", "margin_used",
              "upside_to_median", "n_targets", "targets_predate_drop", "model_as_of", "epicenter", "epicenter_linked",
              "linked_with", "beta", "exposure", "flags", "crux", "position", "pays_for", "declines",
              "margin_basis", "breakeven_consensus", "breakeven_quality", "quality_margin", "cash_conversion", "cash_margin", "consensus_margin", "quality",
              "quality_flags", "cfo_to_ni", "accruals", "sbc_to_revenue", "share_growth", "one_off_share", "quality_years",
              # set only on an agent-reviewed day (judge.py apply); None on a rule-only run
              "rule_grp", "correction_cut", "judgement",
              "cost_of_equity", "midcycle_margin", "hist_net_margin", "loss_making", "sector_pct",
              "value_basis", "events"]


def _finite(v):
    return None if isinstance(v, float) and not math.isfinite(v) else v


def write_db(sb, meta: dict, rows: list[Row]) -> None:
    """Scores first, run row last: the site renders a day only once its run row exists."""
    st = sb.schema("swingtrader")
    recs = [{"as_of": meta["as_of"], "ticker": r.ticker, "grp": r.group, **{k: _finite(getattr(r, k, None)) for k in _DB_FIELDS}}
            for r in rows]
    for i in range(0, len(recs), 200):
        st.table("drawdown_narrative_scores").upsert(recs[i:i + 200], on_conflict="as_of,ticker").execute()
    st.table("drawdown_narrative_runs").upsert({
        "as_of": meta["as_of"], "estimate_snapshot": meta["estimate_snapshot"], "drop_date": meta["drop_date"],
        "universe": meta["universe"], "groups": meta["groups"], "seal_sha256": meta["seal_sha256"],
        "params": {**{k: meta[k] for k in ("flush_cut", "bust_cut", "robust_discount", "erp", "rf", "top_upside", "horizon_years", "epicenter",
                                           "quality_thresholds", "judged_on_quality", "quality")},
                   **{k: meta[k] for k in ("reviewed", "reviewer", "reviewed_at", "rule_seal_sha256", "rule_groups", "moved")
                      if k in meta}},
        "finished_at": datetime.now(ET).isoformat()}, on_conflict="as_of").execute()


def run(drop_date: date = date(2026, 11, 20), workers: int = 6, db: bool = True) -> dict:
    from shared.db import get_supabase_client

    sb = get_supabase_client()
    inputs = load_inputs(sb)
    if not inputs["snapshot_date"]:
        raise RuntimeError("no complete drawdown snapshot; run `cli snapshot` first")
    syms = sorted(inputs["priced_in"])
    earliest = min(date.fromisoformat(p["as_of"]) for p in inputs["priced_in"].values())
    prices, failed = fetch_prices(syms, earliest - timedelta(days=7), workers)
    asof = market_date()
    inputs["statements"] = eq.fetch_statements(syms, workers)
    from . import events as evm

    inputs["events"] = evm.load(syms, asof, workers)
    rows = score(inputs, prices, drop_date, asof)
    data = [r.__dict__ for r in rows]
    ranked = [(r.group, r.rank, r.ticker) for r in rows if r.group in ("on_top", "holds", "fragile", "drowns")]
    seal = hashlib.sha256(json.dumps(ranked).encode()).hexdigest()
    meta = {"as_of": asof.isoformat(), "estimate_snapshot": inputs["snapshot_date"], "drop_date": drop_date.isoformat(),
            "flush_cut": FLUSH_CUT, "bust_cut": "max(%.2f, g3/2)" % BUST_CUT, "robust_discount": "cost_of_equity - %.2f" % ROBUST_STEP, "erp": ERP,
            "rf": inputs.get("rf"), "rf_date": inputs.get("rf_date"), "cost_of_equity_range": [R_MIN, R_MAX],
            "midcycle_trigger": MIDCYCLE_TRIGGER, "top_upside": TOP_UPSIDE, "horizon_years": HORIZON,
            "epicenter": EPICENTER, "universe": len(syms), "price_failed": failed, "seal_sha256": seal,
            "quality_thresholds": eq.THRESHOLDS, "statements_found": len(inputs["statements"]),
            "judged_on_quality": sum(r.margin_basis == "quality" for r in rows),
            "quality": {k: sum(r.quality == k for r in rows) for k in ("clean", "watch", "weak", "unknown")},
            "groups": {g: sum(r.group == g for r in rows) for g in ("on_top", "holds", "fragile", "drowns", "not_cash_flow", "refused")}}
    out = OUT_ROOT / asof.isoformat()
    out.mkdir(parents=True, exist_ok=True)
    from . import ledger

    body = {"meta": meta, "rows": data}
    archived = ledger.archive(out, "scorecard.json", body)
    (out / "rows.json").write_text(json.dumps(data, default=str))
    meta["ledger"] = ledger.append("rule_scorecard", asof.isoformat(), archived, body, seal_sha256=seal)
    status = "skipped"
    if db:
        try:
            write_db(sb, meta, rows)
            status = "written"
        except Exception as exc:  # noqa: BLE001 - the files are kept either way
            status = f"failed: {exc}"
            log.error("narrative DB write failed: %s", exc)
    meta["db"] = status
    return {"meta": meta, "rows": rows, "out_dir": str(out)}
