"""NIS Fundamentals — Buffett-style quality screen.

Identifies "wonderful businesses" the way Buffett does: companies that have
compounded capital efficiently for a decade, fund themselves with their own
cash flow, carry little debt, don't dilute owners, and grow earnings over
time. The screen is pure fundamentals — no price-action gates — so the
output is stable between earnings seasons and is only worth re-running
after a fresh batch of 10-Q / 10-K filings.

All-or-nothing gating: a ticker either passes every gate or is rejected.
Defaults are conservative; tune in one place via ``NIS_GATES``.

Per-ticker cost: 3 FMP API calls (key_metrics annual, income_statement
quarterly, cash_flow_statement quarterly). The NYSE + NASDAQ universe
(~6–7k symbols, minus excluded sectors) → ~15–20k calls end-to-end →
roughly an hour wall clock at Starter's 300/min limit. There is no
price/RS pre-screen, so every universe ticker is deep-screened.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable

import pandas as pd

import services.screener.fmp as fmp

log = logging.getLogger(__name__)


# ── Configuration ───────────────────────────────────────────────────────────

# Sectors whose accounting makes Buffett-style gates produce nonsense.
# Banks/insurers don't have FCF in the conventional sense; REITs report FFO;
# utilities run on regulated returns. Buffett does own banks but with a
# completely different lens — out of scope for v1.
EXCLUDED_SECTORS: frozenset[str] = frozenset({
    "Financial Services",
    "Financials",
    "Real Estate",
    "Utilities",
})


@dataclass(frozen=True)
class NISGates:
    """All thresholds in one place — tweak here to retune the screen."""
    min_years_of_data:        int   = 8     # need ≥ 8 annual periods
    roe_10y_avg_min:          float = 0.15  # 15%
    roic_10y_avg_min:         float = 0.12  # 12%
    fcf_positive_years_min:   int   = 8     # of last 10
    fcf_to_ni_10y_min:        float = 0.8   # cash earnings ≥ 80% of GAAP earnings
    # FMP's key_metrics carries netDebtToEBITDA, not D/E. Net debt / EBITDA is
    # Buffett's preferred leverage gate anyway (he cares about cash earnings
    # vs debt service, not balance-sheet ratios distorted by buybacks).
    # < 1.5 = comfortably under-levered; < 0 means net-cash position.
    net_debt_to_ebitda_max:   float = 1.5
    shares_5y_change_max:     float = 0.0   # flat or down
    eps_10y_cagr_min:         float = 0.07  # 7%


NIS_GATES = NISGates()


# ── Helpers ─────────────────────────────────────────────────────────────────


def _safe_float(v) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
        return f if f == f else None  # NaN check
    except (TypeError, ValueError):
        return None


def _aggregate_annual_from_quarterly(df: pd.DataFrame, sum_cols: list[str]) -> pd.DataFrame:
    """Group a quarterly statement DataFrame into fiscal-year rows.

    Sums the requested columns over each ``fiscalYear`` so we can compute
    annual ratios (FCF, NI, gross profit) without needing the annual-period
    endpoint (which on FMP Starter often counts as a separate call budget).
    """
    if df.empty or "fiscalYear" not in df.columns:
        return pd.DataFrame()
    grouped = df.groupby("fiscalYear", as_index=False)[sum_cols].sum()
    grouped = grouped.sort_values("fiscalYear").reset_index(drop=True)
    return grouped


# ── Core ────────────────────────────────────────────────────────────────────


class NISFundamentals:
    """Stateless gate evaluator. Reuses the existing screener.fmp client.

    Usage:
        bq = NISFundamentals()
        rows = bq.run_screen(universe=["AAPL", "MSFT", ...])
        # rows = list of dicts for ALL passers, sorted by ROE desc
    """

    def __init__(self, gates: NISGates = NIS_GATES) -> None:
        self.fmp = fmp.fmp()
        self.gates = gates

    # ── Per-ticker evaluation ──────────────────────────────────────────────

    def get_nis_flags(self, ticker: str) -> dict | None:
        """Evaluate every gate for one ticker.

        Returns a flat dict (always with ``passes_nis_quality`` bool) OR
        ``None`` if the ticker has insufficient data to evaluate. ``None``
        means "skip silently", not "fail" — caller treats it as a rejection
        but doesn't log it as an error.
        """
        try:
            km   = self.fmp.key_metrics_quarterly(ticker, limit=10)        # annual
            inc  = self.fmp.income_statement_quarterly(ticker, limit=40)   # 10y quarterly
            cf   = self.fmp.cash_flow_statement_quarterly(ticker, limit=40)
        except Exception as exc:
            log.debug("[nis_fundamentals] %s: data fetch failed: %s", ticker, exc)
            return None

        # Need enough annual key_metrics rows for a 10y average to mean anything.
        years_of_data = len(km)
        if years_of_data < self.gates.min_years_of_data:
            return None

        # ── ROE / ROIC (annual key_metrics) ────────────────────────────────
        roe_col  = "returnOnEquity" if "returnOnEquity" in km.columns else None
        roic_col = (
            "roic" if "roic" in km.columns
            else "returnOnInvestedCapital" if "returnOnInvestedCapital" in km.columns
            else None
        )
        if roe_col is None or roic_col is None:
            return None

        roe_series  = km[roe_col].apply(_safe_float).dropna().tail(10)
        roic_series = km[roic_col].apply(_safe_float).dropna().tail(10)
        if len(roe_series) < self.gates.min_years_of_data or len(roic_series) < self.gates.min_years_of_data:
            return None

        roe_10y_avg  = float(roe_series.mean())
        roic_10y_avg = float(roic_series.mean())

        # ── Leverage (latest annual netDebt/EBITDA) ────────────────────────
        net_debt_to_ebitda_latest = _safe_float(km.iloc[-1].get("netDebtToEBITDA"))
        if net_debt_to_ebitda_latest is None:
            return None

        # ── Annual FCF + NI rollups (from quarterly cash flow) ─────────────
        cf_annual = _aggregate_annual_from_quarterly(
            cf, ["freeCashFlow", "netIncome"]
        )
        if cf_annual.empty or len(cf_annual) < self.gates.min_years_of_data:
            return None
        cf_annual = cf_annual.tail(10)
        fcf_positive_years = int((cf_annual["freeCashFlow"] > 0).sum())
        total_fcf_10y = float(cf_annual["freeCashFlow"].sum())
        total_ni_10y  = float(cf_annual["netIncome"].sum())
        fcf_to_ni_10y = (total_fcf_10y / total_ni_10y) if total_ni_10y > 0 else None

        # ── EPS 10y CAGR (annual EPS from rolling-sum TTM at endpoints) ────
        if "eps" in inc.columns and len(inc) >= 36:
            eps_ttm = inc["eps"].apply(_safe_float).rolling(window=4).sum().dropna()
            if len(eps_ttm) >= 36:
                start = float(eps_ttm.iloc[-36])  # ~9y ago TTM
                end   = float(eps_ttm.iloc[-1])
                if start > 0 and end > 0:
                    eps_10y_cagr = (end / start) ** (1 / 9) - 1
                else:
                    eps_10y_cagr = None
            else:
                eps_10y_cagr = None
        else:
            eps_10y_cagr = None

        # ── 5y diluted share count change ──────────────────────────────────
        shares_5y_change_pct: float | None = None
        if "weightedAverageShsOutDil" in inc.columns and len(inc) >= 20:
            shares_now = _safe_float(inc.iloc[-1]["weightedAverageShsOutDil"])
            shares_5y  = _safe_float(inc.iloc[-20]["weightedAverageShsOutDil"])
            if shares_now and shares_5y and shares_5y > 0:
                shares_5y_change_pct = (shares_now / shares_5y - 1) * 100

        # ── Gate evaluation ────────────────────────────────────────────────
        g = self.gates
        passes = (
            roe_10y_avg                  >= g.roe_10y_avg_min
            and roic_10y_avg             >= g.roic_10y_avg_min
            and fcf_positive_years       >= g.fcf_positive_years_min
            and (fcf_to_ni_10y is not None and fcf_to_ni_10y >= g.fcf_to_ni_10y_min)
            and net_debt_to_ebitda_latest <= g.net_debt_to_ebitda_max
            and (shares_5y_change_pct is not None and shares_5y_change_pct <= g.shares_5y_change_max)
            and (eps_10y_cagr is not None and eps_10y_cagr >= g.eps_10y_cagr_min)
        )

        return {
            "symbol":                  ticker,
            "roe_10y_avg_pct":         round(roe_10y_avg * 100, 1),
            "roic_10y_avg_pct":        round(roic_10y_avg * 100, 1),
            "fcf_positive_years":      fcf_positive_years,
            "fcf_to_ni_10y":           round(fcf_to_ni_10y, 2) if fcf_to_ni_10y is not None else None,
            "net_debt_to_ebitda":      round(net_debt_to_ebitda_latest, 2),
            "shares_5y_change_pct":    round(shares_5y_change_pct, 1) if shares_5y_change_pct is not None else None,
            "eps_10y_cagr_pct":        round(eps_10y_cagr * 100, 1) if eps_10y_cagr is not None else None,
            "years_of_data":           years_of_data,
            "passes_nis_quality":      bool(passes),
        }

    # ── Universe iteration ─────────────────────────────────────────────────

    def run_screen(self, universe: Iterable[str]) -> list[dict]:
        """Evaluate every ticker in the universe and return the passers.

        Returns every passer, sorted by 10y avg ROE descending (no cap).
        Skips silently on data errors; logs progress every 25 tickers.
        """
        tickers = [t for t in universe if t]
        total = len(tickers)
        log.info("[nis_fundamentals] evaluating %d tickers", total)

        passers: list[dict] = []
        scored = 0
        rejected = 0
        skipped = 0

        for i, sym in enumerate(tickers, 1):
            if i % 25 == 0:
                log.info(
                    "[nis_fundamentals] %d/%d (passers=%d, skipped=%d)",
                    i, total, len(passers), skipped,
                )
            flags = self.get_nis_flags(sym)
            if flags is None:
                skipped += 1
                continue
            scored += 1
            if flags["passes_nis_quality"]:
                passers.append(flags)
            else:
                rejected += 1

        passers.sort(key=lambda r: r.get("roe_10y_avg_pct") or 0, reverse=True)
        log.info(
            "[nis_fundamentals] done: scored=%d passers=%d rejected=%d skipped=%d",
            scored, len(passers), rejected, skipped,
        )
        return passers
