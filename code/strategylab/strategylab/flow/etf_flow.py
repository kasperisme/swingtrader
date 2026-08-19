"""Tier 2 — mechanical flow from ETF creations and redemptions.

Why this exists: every Tier-1 quantity is derived from the sign of the returns
it is meant to explain, so it either measures nothing (ρ) or measures itself
(the impact "law"). The only fix is a flow measure that does not come from
price at all.

ETF creation/redemption is that measure. When an ETF's shares outstanding rise,
an authorised participant has delivered the underlying basket — a real,
direction-known purchase of every constituent, in proportion to its weight, for
reasons that have nothing to do with that constituent's own price action. This
is the "arbitrage-induced trading" (AIT) construction from the Ponzi Funds
literature, and it is mechanical in exactly the sense the theory requires.

    Flow_j,t  = (SO_j,t − SO_j,t−1) · NAV_j,t          per ETF, in dollars
    AIT_i,t   = Σ_j  w_ij · Flow_j,t  /  DollarVolume_i,t

Shares outstanding are recovered as marketCap / close. The implementation brief
flagged this as the one thing to validate before building anything — if FMP
merely price-scales a stale share count, the difference is identically zero and
the whole construction collapses. `validate_shares_outstanding()` runs that
check, and it is called before any ingest.

**Window:** FMP's historical market cap reaches back to ~2021-06 on this plan,
so AIT is available for roughly five years — thin, and spanning one regime.
"""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from ..config import CACHE_ROOT
from ..data import fmp

log = logging.getLogger(__name__)

MIN_SO_CHANGE = 0.001        # 0.1% — below this is rounding, not a creation
DEFAULT_START = "2021-06-01"


def _dir(name: str) -> Path:
    p = CACHE_ROOT / name
    p.mkdir(parents=True, exist_ok=True)
    return p


# ----------------------------------------------------------------------
@dataclass
class ValidationResult:
    symbol: str
    sessions: int
    distinct_so_levels: int
    days_with_change: int
    update_rate: float          # share of sessions with a share-count change
    usable_daily: bool          # dense enough for a DAILY flow series
    usable_monthly: bool        # dense enough for a MONTHLY one
    usable: bool                # kept for the caller's convenience = usable_daily
    note: str = ""


# A daily flow series needs the share count to actually move most days. FMP
# updates it on roughly 5% of sessions, which is ample for a monthly series and
# useless for a daily one — and the difference is invisible unless you measure
# the RATE rather than merely asking whether it ever changes.
MIN_DAILY_UPDATE_RATE = 0.40
MIN_MONTHLY_UPDATE_RATE = 0.03


def validate_shares_outstanding(symbols: list[str], start: str, end: str
                                ) -> list[ValidationResult]:
    """The gate. Implied SO must STEP often enough for the intended frequency.

    A stale share count price-scaled by FMP gives an implied SO that is constant
    while the price moves, so ΔSO is identically zero — an all-zero flow series
    that reads as "no creations" rather than "no data".

    But passing that check is not sufficient, and assuming it is was a real
    error here: a count that updates on 5% of sessions passes "it changes
    sometimes" and still cannot support a daily series. A 95%-zero series has a
    strongly NEGATIVE weekly autocorrelation purely from the zero inflation,
    which would then read as "flow mean-reverts" — a statement about the vendor's
    refresh cadence dressed up as a statement about the market.
    """
    out = []
    for sym in symbols:
        try:
            mc = fmp._get(
                "https://financialmodelingprep.com/api/v3/"
                f"historical-market-capitalization/{sym}",
                {"from": start, "to": end, "limit": 5000})
            px = fmp.eod_raw(sym, start, end)
        except Exception as exc:
            out.append(ValidationResult(sym, 0, 0, 0, False, f"fetch failed: {exc}"))
            continue
        if not mc or not px:
            out.append(ValidationResult(sym, 0, 0, 0, False, "no data"))
            continue
        m = pd.DataFrame(mc)[["date", "marketCap"]]
        p = pd.DataFrame(px)[["date", "close"]]
        d = m.merge(p, on="date").sort_values("date")
        d = d[(d["close"] > 0) & (d["marketCap"] > 0)]
        if len(d) < 20:
            out.append(ValidationResult(sym, len(d), 0, 0, 0.0, False, False, False,
                                        "too few sessions"))
            continue
        so = d["marketCap"] / d["close"]
        chg = so.pct_change().abs()
        distinct = int(so.round(-3).nunique())
        changes = int((chg > MIN_SO_CHANGE).sum())
        rate = changes / max(1, len(d) - 1)
        daily_ok = rate >= MIN_DAILY_UPDATE_RATE
        monthly_ok = rate >= MIN_MONTHLY_UPDATE_RATE
        if not monthly_ok:
            note = "implied SO looks static — likely price-scaled stale data"
        elif not daily_ok:
            note = (f"updates on only {rate:.1%} of sessions — usable at MONTHLY "
                    "frequency, not daily")
        else:
            note = ""
        out.append(ValidationResult(sym, len(d), distinct, changes, rate,
                                    daily_ok, monthly_ok, daily_ok, note))
    return out


# ----------------------------------------------------------------------
class ETFFlowStore:
    """Daily ETF creation/redemption flow, and the stock-level weight matrix."""

    def __init__(self):
        self.flow_dir = _dir("etf_flow")
        self.weight_dir = _dir("etf_weights")

    # ---- per-ETF dollar flow -------------------------------------------
    def _flow_path(self, etf: str) -> Path:
        return self.flow_dir / f"{etf.replace('/', '_')}.csv.gz"

    def fetch_flow(self, etf: str, start: str, end: str) -> pd.DataFrame:
        mc = fmp._get(
            "https://financialmodelingprep.com/api/v3/"
            f"historical-market-capitalization/{etf}",
            {"from": start, "to": end, "limit": 5000})
        px = fmp.eod_raw(etf, start, end)
        if not mc or not px:
            return pd.DataFrame(columns=["date", "shares_out", "close", "flow_usd"])
        m = pd.DataFrame(mc)[["date", "marketCap"]]
        p = pd.DataFrame(px)[["date", "close"]]
        d = m.merge(p, on="date")
        d["date"] = pd.to_datetime(d["date"])
        d = d[(d["close"] > 0) & (d["marketCap"] > 0)].sort_values("date")
        d["shares_out"] = d["marketCap"] / d["close"]

        dso = d["shares_out"].diff()
        rel = (dso / d["shares_out"].shift(1)).abs()
        # Below the noise floor is rounding in the reported market cap, not a
        # creation. Treating it as flow would inject white noise at the exact
        # frequency the persistence estimate is measured at.
        dso = dso.where(rel > MIN_SO_CHANGE, 0.0)
        d["flow_usd"] = dso * d["close"]
        return d[["date", "shares_out", "close", "flow_usd"]].dropna().reset_index(drop=True)

    def sync_flows(self, etfs: list[str], start: str = DEFAULT_START,
                   end: str = "2026-06-30", workers: int = 8,
                   force: bool = False) -> dict:
        todo = [e for e in etfs if force or not self._flow_path(e).exists()]
        stats = {"requested": len(etfs), "fetched": 0, "empty": 0, "errors": 0,
                 "skipped": len(etfs) - len(todo)}

        def one(etf: str):
            try:
                df = self.fetch_flow(etf, start, end)
                if len(df):
                    df.to_csv(self._flow_path(etf), index=False, compression="gzip")
                return etf, len(df), None
            except Exception as exc:
                return etf, 0, exc

        with ThreadPoolExecutor(max_workers=workers) as pool:
            for fut in as_completed([pool.submit(one, e) for e in todo]):
                _e, n, err = fut.result()
                if err is not None:
                    stats["errors"] += 1
                elif n == 0:
                    stats["empty"] += 1
                else:
                    stats["fetched"] += 1
        return stats

    def load_flow(self, etf: str) -> pd.DataFrame | None:
        p = self._flow_path(etf)
        if not p.exists():
            return None
        try:
            return pd.read_csv(p, parse_dates=["date"])
        except Exception:
            return None

    # ---- stock -> {etf: weight} ------------------------------------------
    def _weight_path(self, symbol: str) -> Path:
        return self.weight_dir / f"{symbol.replace('/', '_')}.json"

    def fetch_weights(self, symbol: str) -> list[dict]:
        rows = fmp._get(
            f"https://financialmodelingprep.com/api/v3/etf-stock-exposure/{symbol}") or []
        out = []
        for r in rows:
            try:
                w = float(r.get("weightPercentage") or 0.0) / 100.0
            except (TypeError, ValueError):
                continue
            etf = r.get("etfSymbol")
            # US-listed ETFs only: foreign lines carry different currencies and
            # their market caps are not comparable to a USD dollar-volume
            # denominator.
            try:
                mv = float(r.get("marketValue") or 0.0)
            except (TypeError, ValueError):
                mv = 0.0
            if etf and 0 < w < 1.0 and "." not in etf and "-" not in etf:
                out.append({"etf": etf, "weight": w, "market_value": mv,
                            "shares": r.get("sharesNumber")})
        return out

    def sync_weights(self, symbols: list[str], workers: int = 8,
                     force: bool = False) -> dict:
        todo = [s for s in symbols if force or not self._weight_path(s).exists()]
        stats = {"requested": len(symbols), "fetched": 0, "errors": 0,
                 "skipped": len(symbols) - len(todo)}

        def one(sym: str):
            try:
                self._weight_path(sym).write_text(json.dumps(self.fetch_weights(sym)))
                return None
            except Exception as exc:
                return exc

        with ThreadPoolExecutor(max_workers=workers) as pool:
            for fut in as_completed([pool.submit(one, s) for s in todo]):
                if fut.result() is None:
                    stats["fetched"] += 1
                else:
                    stats["errors"] += 1
        return stats

    def load_weights(self, symbol: str) -> list[dict]:
        p = self._weight_path(symbol)
        if not p.exists():
            return []
        try:
            return json.loads(p.read_text())
        except Exception:
            return []

    def etfs_referenced(self, symbols: list[str], min_weight: float = 0.0005,
                        top_n: int | None = None) -> list[str]:
        """Every ETF that matters, ranked by DOLLAR exposure to this universe.

        Ranking by aggregate weight percentage is the wrong instinct and an
        expensive one: a $30m thematic fund holding 8% of one mid-cap outranks
        SPY, and its creations move nothing. What determines a stock's mechanical
        flow is w_ij × (dollars the ETF trades), so aggregate position value is
        the correct sort key — and it happens to be returned directly by the
        exposure endpoint.
        """
        agg: dict[str, float] = {}
        fallback: dict[str, float] = {}
        for s in symbols:
            for r in self.load_weights(s):
                if r["weight"] < min_weight:
                    continue
                agg[r["etf"]] = agg.get(r["etf"], 0.0) + float(r.get("market_value") or 0.0)
                fallback[r["etf"]] = fallback.get(r["etf"], 0.0) + r["weight"]
        # If marketValue came back empty across the board, fall back to weight
        # rather than returning an arbitrary order.
        key = agg if sum(agg.values()) > 0 else fallback
        order = sorted(key, key=lambda e: -key[e])
        return order[:top_n] if top_n else order

    def exposure_table(self, symbols: list[str], top_n: int = 20) -> list[dict]:
        """What the ranking actually produced — for eyeballing before a big pull."""
        agg: dict[str, float] = {}
        for s in symbols:
            for r in self.load_weights(s):
                agg[r["etf"]] = agg.get(r["etf"], 0.0) + float(r.get("market_value") or 0.0)
        rows = sorted(agg.items(), key=lambda kv: -kv[1])[:top_n]
        return [{"etf": e, "usd_exposure": v} for e, v in rows]

    # ---- the AIT matrix --------------------------------------------------
    def build_ait(self, symbols: list[str], dates: np.ndarray,
                  dollar_volume: np.ndarray, min_weight: float = 0.0005
                  ) -> tuple[np.ndarray, dict, np.ndarray]:
        """AIT_i,t = Σ_j w_ij · Flow_j,t / DollarVolume_i,t

        Weights are treated as static (one current snapshot per stock). That is
        a real limitation: index membership changes, and a stock added to an ETF
        in 2024 gets its 2024 weight applied to 2021 flows. It biases toward
        names that are ETF-held *today*, which is a survivorship-flavoured
        problem — stated here rather than buried, and it is why this is a
        first-pass estimate rather than the Lou-style FIT.
        """
        grid = pd.DatetimeIndex(dates)
        n, m = len(grid), len(symbols)
        ait = np.zeros((n, m))
        touched = np.zeros(m, dtype=bool)

        needed = self.etfs_referenced(symbols, min_weight)
        flows: dict[str, pd.Series] = {}
        for etf in needed:
            df = self.load_flow(etf)
            if df is None or df.empty:
                continue
            flows[etf] = (df.set_index("date")["flow_usd"]
                            .reindex(grid).fillna(0.0))

        stats = {"etfs_needed": len(needed), "etfs_with_flow": len(flows),
                 "stocks": m}
        if not flows:
            return ait, stats | {"error": "no ETF flow series cached"}, ait

        for j, sym in enumerate(symbols):
            total = np.zeros(n)
            for r in self.load_weights(sym):
                f = flows.get(r["etf"])
                if f is None or r["weight"] < min_weight:
                    continue
                total += r["weight"] * f.to_numpy()
                touched[j] = True
            ait[:, j] = total

        dv = np.where(dollar_volume > 0, dollar_volume, np.nan)
        ait_scaled = ait / dv
        stats["stocks_with_any_etf_flow"] = int(touched.sum())
        stats["coverage"] = float(touched.mean())
        stats["nonzero_share"] = float(np.mean(np.abs(ait[:, touched]) > 0)) if touched.any() else 0.0
        # The raw dollar series is returned alongside the scaled one on purpose.
        # Dividing by dollar volume puts a HIGHLY persistent quantity (AR≈0.67)
        # in the denominator, which can manufacture persistence in the ratio even
        # when the numerator has none — the mirror image of the EMA trap. Any
        # inertia found in the scaled series has to be checked against the raw.
        return ait_scaled, stats | {"raw_dollars_available": True}, ait
