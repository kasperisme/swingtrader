"""NIS Fundamentals — Buffett-style quality screen over the NYSE + NASDAQ.

Universe is the full NYSE + NASDAQ listing (same source as NIS Momentum),
minus the excluded sectors. Identifies the ~30 companies that pass every
Buffett-style quality gate:

  • 10y avg ROE  ≥ 15%
  • 10y avg ROIC ≥ 12%
  • Free cash flow positive ≥ 8 of last 10 years
  • 10y FCF / Net Income ratio ≥ 0.8   (earnings quality)
  • Net-debt / EBITDA ≤ 1.5             (conservative leverage)
  • Diluted share count flat or ↓ over last 5y
  • 10y EPS CAGR ≥ 7%
  • Sector NOT IN {Financial Services, Real Estate, Utilities}

Output is stable between earnings seasons — gates are pure fundamentals, no
price input — so the screening is scheduled quarterly (Mar 1 / Jun 1 / Sep
1 / Dec 1, after the bulk of each earnings season has reported).
"""

from __future__ import annotations

import logging

from services.screener.nis_fundamentals import EXCLUDED_SECTORS, NISFundamentals

from ..types import ScreeningResult

log = logging.getLogger(__name__)

_SUMMARY_TOP_N = 25  # cap symbols in the Telegram summary for readability


def run(client, screening: dict) -> ScreeningResult:  # noqa: ARG001 — FMP/REST is the data source
    import pandas as pd

    bq = NISFundamentals()

    # ── Universe: full NYSE + NASDAQ minus excluded sectors ────────────────
    # Same listing source as NIS Momentum (see nis_momentum.py step 1).
    df_col = []
    for exch in ("NYSE", "NASDAQ"):
        df_col.append(bq.fmp.exchange_tickers(exch))
    universe = pd.concat(df_col, axis=0).dropna(subset=["symbol"])
    universe = universe.drop_duplicates(subset=["symbol"])
    if universe.empty or "symbol" not in universe.columns:
        log.error("[nis_fundamentals] exchange_tickers() returned no data")
        return ScreeningResult(
            triggered=False,
            summary="No NYSE/NASDAQ universe data available.",
            ticker_count=0,
            data_used={"universe_size": 0, "passed": 0},
            error="empty_universe",
        )

    pre_count = len(universe)
    if "sector" in universe.columns:
        universe = universe[~universe["sector"].isin(EXCLUDED_SECTORS)]
    tickers = universe["symbol"].dropna().tolist()
    log.info(
        "[nis_fundamentals] universe: %d → %d after sector exclusion",
        pre_count, len(tickers),
    )

    # ── Run gates ──────────────────────────────────────────────────────────
    passers = bq.run_screen(tickers)

    if not passers:
        return ScreeningResult(
            triggered=False,
            summary=None,
            ticker_count=0,
            data_used={
                "universe_size":      pre_count,
                "after_sector_filter": len(tickers),
                "passed":             0,
            },
        )

    # Decorate with sector metadata for the gallery + Telegram summary.
    sector_lookup = dict(zip(universe["symbol"], universe.get("sector", [])))
    sub_sector_col = (
        "subSector" if "subSector" in universe.columns
        else "industry" if "industry" in universe.columns
        else None
    )
    sub_sector_lookup = (
        dict(zip(universe["symbol"], universe[sub_sector_col]))
        if sub_sector_col else {}
    )
    for row in passers:
        sym = row["symbol"]
        row["sector"]    = sector_lookup.get(sym) or "N/A"
        row["subSector"] = sub_sector_lookup.get(sym) or "N/A"

    summary = _format_summary(passers, universe_size=len(tickers))
    data_used = {
        "universe_size":      pre_count,
        "after_sector_filter": len(tickers),
        "passed":             len(passers),
        "symbols":            passers,
    }
    return ScreeningResult(
        triggered=True,
        summary=summary,
        ticker_count=len(passers),
        data_used=data_used,
    )


def _format_summary(passers: list[dict], universe_size: int) -> str:
    n = len(passers)
    head = (
        f"<b>NIS Fundamentals</b>\n"
        f"{n} name{'s' if n != 1 else ''} pass Buffett-quality gates "
        f"(of {universe_size} screened)\n"
    )
    shown = passers[:_SUMMARY_TOP_N]
    lines = []
    for r in shown:
        sym = r["symbol"]
        sector = r.get("sector") or "—"
        roe = r.get("roe_10y_avg_pct")
        roe_part = f" · 10y ROE {roe:.0f}%" if roe is not None else ""
        lines.append(f"• <b>{sym}</b> — {sector}{roe_part}")
    body = "\n".join(lines)
    tail = "" if n <= _SUMMARY_TOP_N else f"\n…and {n - _SUMMARY_TOP_N} more"
    return f"{head}\n{body}{tail}"
