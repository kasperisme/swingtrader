"""Corporate events the stress test must see BEFORE any agent does (council 4).

The 2026-11-21 panel spent its judgement on artefacts the rule could have caught:
pre-split analyst targets (MNST, NFLX, CVNA), pre-deal models (FOXA-Roku closed
11-06, UTZ take-private, ROKU on a takeout), spin-off-distorted growth (HON).
Each one rested on a model remembering it from training. This module checks the
corporate-action feeds instead, and narrative.py acts on the result:

    split       a split of at least 1.5-for-1 (either way) inside [model_as_of - 120d,
                today]: the target spread mixes pre- and post-split shares (the same
                refusal and 120-day window as nis-priced-in-story's `price_basis`)
                -> refused
    adjustment  a smaller price factor in the same window (1907-for-2000, 6209-for-5000)
                is a spin-off or stock dividend, not a split -> barred from on_top,
                recovery case dropped
    mna_target  named as the target of a deal filed in the last 180 days by a LARGER
                listed company: the price is set by the deal -> not_cash_flow.
                A filer smaller than the "target" (Gentherm/MOD, MiniMed/MDT) is a
                spin-off or Reverse Morris Trust of one unit -> mna_spin, barred from
                on_top
    mna_buyer   the acquirer in such a deal: the model predates the combined
                company -> flagged, barred from on_top
    perimeter   FY+1 consensus revenue more than 25% away from the last reported
                year while 3y consensus is under 15%/yr: a spin-off or merger moved
                the perimeter, not the business -> flagged, barred from on_top
    share_step  diluted shares up more than 10% in one filed year: an all-stock
                deal or a conversion -> flagged
    stale_targets  median target more than 80% above the price -> flagged; the
                recovery case (upside) is dropped

The M&A feed is SEC merger filings (S-4/DEFM14A via FMP), so a cash deal announced
but not yet filed can be missed. A miss is the old behaviour, not a new error.
"""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path

from .snapshots import FMP_BASE, _fmp_key, _get

log = logging.getLogger(__name__)

SPLIT_WINDOW_DAYS = 120
SPLIT_MIN_FACTOR = 1.5   # matches nis-priced-in-story / strategylab analyst target window
MNA_DAYS = 180
PERIMETER_JUMP = 0.25
PERIMETER_MAX_G3 = 0.15
SHARE_STEP = 0.10
STALE_UPSIDE = 0.80
CACHE_DIR = Path(__file__).resolve().parents[2] / "output" / "drawdown" / "events"


def _cached(name: str, fetch, max_age_h: int = 20):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    p = CACHE_DIR / f"{name.replace('/', '_')}.json"
    if p.exists() and datetime.now().timestamp() - p.stat().st_mtime < max_age_h * 3600:
        return json.loads(p.read_text())
    body = fetch()
    if body is not None:
        p.write_text(json.dumps(body))
    return body


def fetch_splits(symbols: list[str], workers: int = 6) -> dict[str, list[dict]]:
    key = _fmp_key()

    def one(sym):
        def get():
            try:
                b = _get(f"{FMP_BASE}/splits", {"symbol": sym, "apikey": key}).json()
                return b if isinstance(b, list) else []
            except Exception as exc:  # noqa: BLE001
                log.warning("splits %s: %s", sym, exc)
                return None
        return sym, _cached(f"splits_{sym}", get) or []

    with ThreadPoolExecutor(workers) as ex:
        return dict(ex.map(one, symbols))


def fetch_mna(as_of: date, days: int = MNA_DAYS, max_pages: int = 40) -> list[dict]:
    """Merger filings since as_of - days, newest first (one paged feed, cached daily)."""
    key = _fmp_key()
    since = (as_of - timedelta(days=days)).isoformat()

    def get():
        out = []
        for page in range(max_pages):
            try:
                b = _get(f"{FMP_BASE}/mergers-acquisitions-latest", {"page": page, "limit": 100, "apikey": key}).json()
            except Exception as exc:  # noqa: BLE001
                log.warning("mna page %s: %s", page, exc)
                return out or None
            if not isinstance(b, list) or not b:
                break
            out += b
            if min(str(r.get("transactionDate") or "9") for r in b) < since:
                break
        return [r for r in out if str(r.get("transactionDate") or "") >= since]

    return _cached(f"mna_{as_of.isoformat()}", get) or []


def _mcaps(symbols: list[str]) -> dict[str, float | None]:
    key = _fmp_key()

    def one(sym):
        def get():
            try:
                b = _get(f"{FMP_BASE}/profile", {"symbol": sym, "apikey": key}).json()
                return {"mcap": (b[0].get("marketCap") if isinstance(b, list) and b else None)}
            except Exception:  # noqa: BLE001
                return None
        return sym, (_cached(f"profile_{sym}", get, max_age_h=72) or {}).get("mcap")

    with ThreadPoolExecutor(4) as ex:
        return dict(ex.map(one, symbols))


def load(symbols: list[str], as_of: date, workers: int = 6) -> dict:
    mna = fetch_mna(as_of)
    caps = _mcaps(sorted({r[k] for r in mna for k in ("symbol", "targetedSymbol") if r.get(k)}))
    for r in mna:
        r["acquirer_mcap"], r["target_mcap"] = caps.get(r.get("symbol")), caps.get(r.get("targetedSymbol"))
    targets, buyers = {}, {}
    for r in mna:
        if r.get("targetedSymbol"):
            targets.setdefault(r["targetedSymbol"], r)
        if r.get("symbol"):
            buyers.setdefault(r["symbol"], r)
    return {"splits": fetch_splits(symbols, workers), "mna_targets": targets, "mna_buyers": buyers,
            "mna_filings": len(mna), "as_of": as_of.isoformat()}


def check(sym: str, ev: dict | None, model_as_of: str, as_of: date, *, upside: float | None,
          rev_fy1: float | None, rev_last: float | None, g3: float | None, share_step: float | None) -> list[dict]:
    """Events for one name, each {kind, action, note}. action: refuse | not_cash_flow | bar_top | flag."""
    out: list[dict] = []
    ev = ev or {}
    lo = date.fromisoformat(model_as_of) - timedelta(days=SPLIT_WINDOW_DAYS)
    for s in (ev.get("splits") or {}).get(sym, []):
        try:
            d = date.fromisoformat(str(s.get("date"))[:10])
        except ValueError:
            continue
        num, den = s.get("numerator") or 0, s.get("denominator") or 0
        if not (lo <= d <= as_of and num and den and num != den):
            continue
        factor = max(num / den, den / num)
        if factor >= SPLIT_MIN_FACTOR:
            out.append({"kind": "split", "action": "refuse",
                        "note": f"{num:g}-for-{den:g} split on {d}: analyst targets mix pre- and post-split shares"})
        else:
            out.append({"kind": "adjustment", "action": "bar_top",
                        "note": f"{num:g}-for-{den:g} price adjustment on {d} (spin-off or stock dividend): "
                                f"targets and the model may predate it"})
        break
    t = (ev.get("mna_targets") or {}).get(sym)
    if t:
        a_cap, t_cap = t.get("acquirer_mcap"), t.get("target_mcap")
        if a_cap and t_cap and a_cap >= 0.5 * t_cap:
            out.append({"kind": "mna_target", "action": "not_cash_flow",
                        "note": f"named as the target of {t.get('companyName')} (filed {t.get('transactionDate')}): "
                                f"the deal sets the price"})
        else:
            out.append({"kind": "mna_spin", "action": "bar_top",
                        "note": f"named in a filing by the smaller {t.get('companyName')} ({t.get('transactionDate')}): "
                                f"a spin-off or Reverse Morris Trust of one unit, the model predates it"})
    b = (ev.get("mna_buyers") or {}).get(sym)
    if b and not t:
        out.append({"kind": "mna_buyer", "action": "bar_top",
                    "note": f"acquiring {b.get('targetedCompanyName')} (filed {b.get('transactionDate')}): "
                            f"the model predates the combined company"})
    if rev_fy1 and rev_last and rev_last > 0 and g3 is not None and g3 < PERIMETER_MAX_G3:
        jump = rev_fy1 / rev_last - 1
        if abs(jump) > PERIMETER_JUMP:
            out.append({"kind": "perimeter", "action": "bar_top",
                        "note": f"next-year consensus revenue is {jump:+.0%} vs the last reported year against "
                                f"{g3:+.0%}/yr growth: a spin-off or deal moved the perimeter"})
    if share_step is not None and share_step > SHARE_STEP:
        out.append({"kind": "share_step", "action": "flag",
                    "note": f"diluted shares rose {share_step:.0%} in one filed year (all-stock deal or conversion?)"})
    if upside is not None and upside > STALE_UPSIDE:
        out.append({"kind": "stale_targets", "action": "flag",
                    "note": f"median target {upside:+.0%} above the price: stale or mis-based targets; recovery case dropped"})
    return out
