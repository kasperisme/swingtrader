"""The FIM strategy universe — the screener spec, implemented literally.

    NYSE + NASDAQ common stock   isEtf=false, isActivelyTrading=true,
                                 excluding ADRs, REITs, SPACs and dual-class
                                 duplicates (one line per company)
    Market cap                   $2B – $50B
    Price                        > $5           (Amihud is junk below this)
    ADV                          > $10M/day     (Q_break meaningful; our own
                                                 orders don't dominate f_t)
    ETF ownership                >= 3% of shares outstanding
    History                      >= 2 years     (26 weeks for rho + burn-in)
    Earnings                     exclude ±10 sessions at rebalance

The ETF-ownership floor is the load-bearing one and the easiest to skip. The
Tier-2 flow signal only exists where mechanical holders are present: a stock
nobody indexes has no arbitrage-induced trading to measure, and including such
names does not weaken the estimate, it dilutes it toward zero by construction.

Every filter except membership is evaluated per-bar from the price panel, so it
is point-in-time: a name enters the universe the day it first qualifies.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from ..config import meta_cache_dir
from ..data.universe import UniverseBuilder

log = logging.getLogger(__name__)

# Suffixes and name patterns that mark share classes / non-common lines.
_DUAL_CLASS_MARKERS = ("-A", "-B", "-C", ".A", ".B", ".C")
_SPAC_WORDS = ("acquisition corp", "acquisition co", "acquisition holdings",
               "blank check", "capital corp i", "spac")
_ADR_WORDS = ("adr", "american depositary", "american depository")
_REIT_WORDS = (" reit", "real estate investment trust")


@dataclass
class UniverseSpec:
    min_market_cap: float = 2e9
    max_market_cap: float = 50e9
    min_price: float = 5.0
    min_adv_usd: float = 10e6
    min_etf_ownership: float = 0.03
    min_history_days: int = 504          # ~2 years
    earnings_exclusion_days: int = 10
    exclude_adr: bool = True
    exclude_reit: bool = True
    exclude_spac: bool = True
    dedupe_share_classes: bool = True


@dataclass
class UniverseResult:
    mask: np.ndarray                      # (n_days, n_symbols) bool — eligible per bar
    symbols: list[str]
    funnel: dict = field(default_factory=dict)
    daily_counts: np.ndarray | None = None
    dropped: dict = field(default_factory=dict)

    def summary(self) -> str:
        rows = ["Universe funnel (names surviving each filter):"]
        for k, v in self.funnel.items():
            rows.append(f"   {k:<34} {v}")
        if self.daily_counts is not None and len(self.daily_counts):
            dc = self.daily_counts[self.daily_counts > 0]
            if dc.size:
                rows.append(f"   {'names eligible per day (median)':<34} {int(np.median(dc))}")
                rows.append(f"   {'                       (min-max)':<34} "
                            f"{int(dc.min())}-{int(dc.max())}")
        return "\n".join(rows)


# ----------------------------------------------------------------------
def _looks_like(name: str, words: tuple) -> bool:
    n = (name or "").lower()
    return any(w in n for w in words)


def _company_key(row: dict) -> str:
    """Collapse share classes onto one company.

    GOOG/GOOGL and BRK-A/BRK-B are one company each; keeping both double-counts
    the same flow and breaks the 'one line per company' rule.
    """
    name = (row.get("companyName") or row.get("symbol") or "").lower()
    for suffix in (" class a", " class b", " class c", " cl a", " cl b", " cl c"):
        name = name.replace(suffix, "")
    return name.strip().rstrip(".,")


def etf_ownership(symbols: list[str], shares_out: np.ndarray,
                  weights_loader) -> np.ndarray:
    """Share of each company's stock held by ETFs, as of the latest snapshot.

    `etf-stock-exposure` returns a current snapshot, so this is one number per
    name rather than a time series — a real limitation, since index membership
    changes. It biases toward names that are ETF-held TODAY. Stated here; it is
    why this is a screening filter and not a signal.
    """
    latest = np.full(len(symbols), np.nan)
    for j, sym in enumerate(symbols):
        rows = weights_loader(sym)
        if not rows:
            continue
        held = 0.0
        for r in rows:
            try:
                held += float(r.get("shares") or 0.0)
            except (TypeError, ValueError):
                continue
        col = shares_out[:, j]
        so = col[np.isfinite(col)]
        if so.size and so[-1] > 0:
            latest[j] = held / so[-1]
    return latest


def build_universe(panel, shares_out: np.ndarray, adv: np.ndarray,
                   market_cap: np.ndarray, spec: UniverseSpec,
                   weights_loader=None, earnings_dates: dict | None = None,
                   listing_meta: dict | None = None) -> UniverseResult:
    n, m = panel.close.shape
    symbols = list(panel.symbols)
    funnel: dict[str, int] = {}
    dropped: dict[str, list] = {}

    # ---- static membership filters --------------------------------------
    keep_static = np.ones(m, dtype=bool)
    funnel["listed (cached with price history)"] = int(keep_static.sum())

    meta = listing_meta or {}
    if spec.exclude_adr or spec.exclude_reit or spec.exclude_spac:
        for j, s in enumerate(symbols):
            name = (meta.get(s, {}) or {}).get("companyName", "")
            industry = (meta.get(s, {}) or {}).get("industry", "") or ""
            sector = (meta.get(s, {}) or {}).get("sector", "") or ""
            bad = False
            if spec.exclude_adr and _looks_like(name, _ADR_WORDS):
                bad = True
            if spec.exclude_reit and (_looks_like(name, _REIT_WORDS)
                                      or "reit" in industry.lower()
                                      or sector.lower() == "real estate"):
                bad = True
            if spec.exclude_spac and _looks_like(name, _SPAC_WORDS):
                bad = True
            if bad:
                keep_static[j] = False
                dropped.setdefault("adr_reit_spac", []).append(s)
        funnel["after ADR / REIT / SPAC exclusion"] = int(keep_static.sum())

    if spec.dedupe_share_classes:
        seen: dict[str, int] = {}
        for j, s in enumerate(symbols):
            if not keep_static[j]:
                continue
            key = _company_key(meta.get(s, {"symbol": s}))
            if key in seen:
                # Keep the more liquid line of a dual-class pair.
                other = seen[key]
                a = np.nanmedian(adv[:, j]) if np.isfinite(adv[:, j]).any() else 0.0
                b = np.nanmedian(adv[:, other]) if np.isfinite(adv[:, other]).any() else 0.0
                drop = j if a <= b else other
                keep_static[drop] = False
                dropped.setdefault("dual_class", []).append(symbols[drop])
                if drop == other:
                    seen[key] = j
            else:
                seen[key] = j
        funnel["after dual-class dedupe"] = int(keep_static.sum())

    # ---- ETF ownership floor --------------------------------------------
    if spec.min_etf_ownership > 0 and weights_loader is not None:
        own = etf_ownership(symbols, shares_out, weights_loader)
        has = np.isfinite(own) & (own >= spec.min_etf_ownership)
        keep_static &= has
        funnel[f"after ETF ownership >= {spec.min_etf_ownership:.0%}"] = int(keep_static.sum())
        dropped["etf_ownership_median"] = float(np.nanmedian(own)) if np.isfinite(own).any() else None

    # ---- per-bar (point-in-time) filters ---------------------------------
    ok = np.isfinite(panel.close) & keep_static[None, :]
    ok &= panel.close > spec.min_price
    ok &= np.greater_equal(adv, spec.min_adv_usd,
                           out=np.zeros_like(ok), where=np.isfinite(adv))
    ok &= np.greater_equal(market_cap, spec.min_market_cap,
                           out=np.zeros_like(ok), where=np.isfinite(market_cap))
    ok &= np.less(market_cap, spec.max_market_cap,
                  out=np.zeros_like(ok), where=np.isfinite(market_cap))

    bars = np.cumsum(np.isfinite(panel.close).astype(int), axis=0)
    ok &= bars >= spec.min_history_days

    # ---- earnings blackout ------------------------------------------------
    if earnings_dates and spec.earnings_exclusion_days > 0:
        grid = pd.DatetimeIndex(panel.dates)
        w = spec.earnings_exclusion_days

        # Partial coverage is worse than none: names WITH earnings data lose
        # ~8% of their eligible days to blackouts while names without keep all
        # of theirs, so the filter quietly tilts the universe toward whichever
        # names happened to be missing from the cache.
        eligible_names = [symbols[j] for j in range(m) if keep_static[j]]
        have = sum(1 for sym in eligible_names if earnings_dates.get(sym))
        coverage = have / max(1, len(eligible_names))
        funnel["earnings-date coverage"] = f"{have}/{len(eligible_names)} ({coverage:.0%})"
        if coverage < 0.9:
            log.warning(
                "Earnings dates cover only %.0f%% of the universe. Applying the "
                "blackout anyway would penalise exactly the names that HAVE data, "
                "so it is skipped — sync the rest, or accept no blackout.", coverage * 100)
            funnel["earnings blackout applied"] = "SKIPPED (coverage below 90%)"
            earnings_dates = None

    if earnings_dates and spec.earnings_exclusion_days > 0:
        blocked_total = 0
        for j, sym in enumerate(symbols):
            dts = earnings_dates.get(sym)
            if not dts:
                continue
            pos = np.searchsorted(grid.values, np.array(dts, dtype="datetime64[ns]"))
            for p_ in pos:
                lo, hi = max(0, p_ - w), min(n, p_ + w + 1)
                ok[lo:hi, j] = False
                blocked_total += hi - lo
        funnel["earnings blackout applied"] = f"±{w} sessions, {blocked_total:,} cells"

    ever = ok.any(axis=0)
    funnel["names ever eligible"] = int(ever.sum())
    counts = ok.sum(axis=1)
    return UniverseResult(mask=ok, symbols=symbols, funnel=funnel,
                          daily_counts=counts, dropped=dropped)


def listing_metadata(refresh: bool = False) -> dict:
    """symbol -> {companyName, sector, industry} for the exclusion rules."""
    path = Path(meta_cache_dir()) / "listing_meta.json"
    if path.exists() and not refresh:
        try:
            return json.loads(path.read_text())
        except Exception:
            pass
    ub = UniverseBuilder()
    rows = ub.listed(refresh=refresh)
    out = {}
    for r in rows:
        out[r["symbol"]] = {"symbol": r["symbol"], "sector": r.get("sector"),
                            "industry": r.get("industry"),
                            "companyName": r.get("companyName")}
    path.write_text(json.dumps(out))
    return out
