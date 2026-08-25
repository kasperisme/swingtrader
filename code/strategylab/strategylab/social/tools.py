"""The evidence surface for investigating a case — everything EXCEPT news.

Mirrors the shape of `analytics/services/rag/tools.py`: one place defines the
data functions and one place defines the schemas the model sees, so a new
investigator gets the same surface as every other.

**The news tools are deliberately absent, and that is the whole design.** By the
governing assumption anything in the corpus is priced in, so an investigation
that answers "is this true?" by reading coverage has answered a different
question — "has someone said it?" — which `entail.py` already settles. Evidence
for a case has to come from measurements the market has not already digested.

What that leaves is narrower than one would like, and the honest consequence is
that many observables the cases name cannot be tested here at all. Crocs' bull
and bear both hinge on **weekly markdown depth on crocs.com and the US wholesale
doors** — the right test, and one this registry cannot run. A tool surface that
quietly substitutes a weaker proxy would be worse than one that reports it
cannot answer, so `coverage_report()` states plainly which observables are
reachable and which are not.
"""

from __future__ import annotations

import json
import logging
from datetime import date, timedelta

import numpy as np
import pandas as pd

from ..config import CACHE_ROOT
from ..data.prices import PriceStore

log = logging.getLogger(__name__)

# Observable kinds the cases emit, and whether this registry can measure them.
OBSERVABLE_COVERAGE = {
    "consumer_attention": ("attention_series", "Wikipedia pageviews for a brand "
                                               "or product page"),
    "unit_volumes": ("segment_revenue_history", "segment revenue as a proxy; "
                                                "true unit volumes unavailable"),
    "pricing": (None, "street/markdown pricing requires retail scraping — NOT "
                      "wired. Cannot be tested here."),
    "store_or_location_counts": (None, "store-locator scraping — NOT wired."),
    "app_ranks": (None, "app-store ranks — NOT wired."),
    "web_traffic": (None, "site traffic panels — NOT wired."),
    "hiring": (None, "job-posting counts — NOT wired."),
}


def coverage_report(observable_kind: str) -> dict:
    tool, note = OBSERVABLE_COVERAGE.get(observable_kind, (None, "unknown kind"))
    return {"kind": observable_kind, "testable": tool is not None,
            "tool": tool, "note": note}


# ----------------------------------------------------------------------
def attention_series(ticker: str, entity: str, days: int = 730) -> dict:
    """Daily Wikipedia pageviews for a brand/product page, with recent growth."""
    from .entity import EntityStore
    from .pageviews import PageviewStore, attention_growth

    pv = PageviewStore()
    ents = EntityStore().load(ticker)
    target = None
    low = (entity or "").lower()
    for e in ents:
        if low and (low in e.label.lower() or low in e.article.lower()):
            target = e.article
            break
    if target is None:
        target = (entity or "").replace(" ", "_")
    df = pv.load(target)
    if df is None or df.empty:
        try:
            df = pv.fetch(target)
            pv.save(target, df)
        except Exception as exc:                              # noqa: BLE001
            return {"error": f"no pageview series for {target!r}: {exc}"}
    if df is None or df.empty:
        return {"error": f"no pageview series for {target!r}"}
    df = df[df["date"] >= pd.Timestamp(date.today() - timedelta(days=days))]
    if df.empty:
        return {"error": "series empty in window"}
    g = attention_growth(df.set_index("date")[["views"]].rename(
        columns={"views": "v"}), 90, 365)["v"].dropna()
    return {"article": target, "obs": int(len(df)),
            "median_daily_views": float(df["views"].median()),
            "last_90d_mean": float(df["views"].tail(90).mean()),
            "prior_year_mean": float(df["views"].mean()),
            "log_growth_vs_own_baseline": (float(g.iloc[-1]) if len(g) else None),
            "note": ("Attention is not purchase. This measures people reading "
                     "about the thing, which is a weak proxy for demand.")}


def price_and_volume(ticker: str, days: int = 365) -> dict:
    df = PriceStore().load(ticker)
    if df is None or df.empty:
        return {"error": f"no price history for {ticker}"}
    df = df.tail(days + 5)
    px = df["close"].to_numpy(dtype=float)
    if len(px) < 30:
        return {"error": "insufficient history"}
    rets = np.diff(np.log(px))
    return {"last": float(px[-1]), "return_1y": float(px[-1] / px[0] - 1.0),
            "max_drawdown": float((px / np.maximum.accumulate(px) - 1).min()),
            "annualised_vol": float(np.std(rets, ddof=1) * np.sqrt(252)),
            "avg_dollar_volume_20d": float(
                (df["close"] * df["volume"]).tail(20).mean())}


def segment_revenue_history(ticker: str, years: int = 5) -> dict:
    """Revenue by product segment across fiscal years — the materiality anchor."""
    from .business import _segments
    out = {}
    for kind in ("product", "geographic"):
        rows = _segments(ticker, kind)
        out[kind] = [
            {s.name: {"revenue": s.revenue, "share": round(s.share, 3),
                      "yoy": (round(s.yoy, 3) if s.yoy is not None else None)}
             for s in year} for year in rows[:years]]
    return out


def earnings_surprise_history(ticker: str, limit: int = 12) -> dict:
    p = CACHE_ROOT / "surprises" / f"{ticker.replace('.', '-')}.json"
    if not p.exists():
        return {"error": f"no surprise cache for {ticker}"}
    try:
        rows = json.loads(p.read_text())
    except Exception as exc:                                  # noqa: BLE001
        return {"error": str(exc)}
    rows = sorted(rows, key=lambda r: r.get("date", ""), reverse=True)[:limit]
    out = []
    for r in rows:
        a, e = r.get("actualEarningResult"), r.get("estimatedEarning")
        if a is None or e is None:
            continue
        out.append({"date": r["date"], "actual": a, "estimate": e,
                    "surprise": round(a - e, 4),
                    "surprise_pct": (round((a - e) / abs(e), 4) if e else None)})
    beats = sum(1 for r in out if r["surprise"] > 0)
    return {"quarters": out, "beat_rate": (beats / len(out)) if out else None,
            "n": len(out)}


def peer_metrics(ticker: str, metric: str = "return_1y") -> dict:
    """The same measure across relationship-graph peers — is this idiosyncratic?"""
    from .narrative import network
    net = network(ticker, 180)
    peers = (net.get("competitor", []) + net.get("industry", []))[:8]
    out = {}
    for p in [ticker] + [x for x in peers if x != ticker]:
        r = price_and_volume(p)
        if "error" not in r:
            out[p] = {k: round(v, 4) for k, v in r.items()
                      if k in ("return_1y", "annualised_vol", "max_drawdown")}
    return {"peers": out,
            "note": "If the whole peer set moved together, the case is a sector "
                    "call, not a company call."}


TOOLS = {
    "attention_series": attention_series,
    "price_and_volume": price_and_volume,
    "segment_revenue_history": segment_revenue_history,
    "earnings_surprise_history": earnings_surprise_history,
    "peer_metrics": peer_metrics,
}

SCHEMAS = [
    {"name": "attention_series",
     "description": "Daily Wikipedia pageviews for a brand or product page, with "
                    "growth versus its own trailing baseline. Attention, not purchase.",
     "input_schema": {"type": "object",
                      "properties": {"ticker": {"type": "string"},
                                     "entity": {"type": "string",
                                                "description": "brand or product name"}},
                      "required": ["ticker", "entity"]}},
    {"name": "price_and_volume",
     "description": "Trailing return, volatility, drawdown and dollar volume.",
     "input_schema": {"type": "object",
                      "properties": {"ticker": {"type": "string"},
                                     "days": {"type": "integer"}},
                      "required": ["ticker"]}},
    {"name": "segment_revenue_history",
     "description": "Revenue by product and geographic segment across fiscal years, "
                    "with share of total and year-over-year growth.",
     "input_schema": {"type": "object",
                      "properties": {"ticker": {"type": "string"}},
                      "required": ["ticker"]}},
    {"name": "earnings_surprise_history",
     "description": "Reported vs estimated EPS by quarter, and the beat rate.",
     "input_schema": {"type": "object",
                      "properties": {"ticker": {"type": "string"}},
                      "required": ["ticker"]}},
    {"name": "peer_metrics",
     "description": "Price metrics across relationship-graph peers, to separate a "
                    "company call from a sector call.",
     "input_schema": {"type": "object",
                      "properties": {"ticker": {"type": "string"}},
                      "required": ["ticker"]}},
]
