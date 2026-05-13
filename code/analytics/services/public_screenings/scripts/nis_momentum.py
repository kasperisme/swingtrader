"""NIS Momentum — proprietary stock screening developed by newsimpactscreener.

Multi-stage technical + growth-fundamental screen across NYSE + NASDAQ:
  1. Pull NYSE + NASDAQ tickers from FMP
  2. Quote + relative-strength pre-screen (actively traded AND RS > 80)
  3. Trend template — moving-average alignment, slope confirmation,
     proximity to 52-week extremes, RS > 70
  4. Growth fundamentals overlay — increasing EPS direction AND
     3 consecutive quarterly earnings beats
  5. A ticker is reported only if it passes every technical AND
     fundamental gate.

Runtime note: hits FMP for every ticker that survives the RS pre-screen
and for earnings data on each candidate. Expect 5–15 minutes for a full
run. Tune `_TESTING_TICKER_CAP` while iterating.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from services.screener import fundamentals, technical

from ..types import ScreeningResult

log = logging.getLogger(__name__)

_LOOKBACK_DAYS = 365
_DATE_FMT = "%Y-%m-%d"
_SUMMARY_TOP_N = 25  # cap symbols listed in summary (Telegram readability)
_TESTING_TICKER_CAP = 0  # 0 = no cap; set to a small number while iterating


def run(
    client, screening: dict
) -> ScreeningResult:  # noqa: ARG001 — client unused; FMP/REST is the data source
    tech = technical.technical()
    fund = fundamentals.Fundamentals()

    today = datetime.today()
    startdate = today - timedelta(days=_LOOKBACK_DAYS)

    # ── Step 1: tickers ────────────────────────────────────────────────────
    df_col = []
    for exch in ("NYSE", "NASDAQ"):
        df_col.append(tech.get_exhange_tickers(exch))

    import pandas as pd

    df_tickers = pd.concat(df_col, axis=0).dropna(subset=["symbol"])
    if _TESTING_TICKER_CAP:
        df_tickers = df_tickers.head(_TESTING_TICKER_CAP)
        log.warning("[nis_momentum] TESTING cap active: %d tickers", _TESTING_TICKER_CAP)
    tickers = df_tickers["symbol"].to_list()
    log.info("[nis_momentum] universe: %d tickers", len(tickers))

    # ── Step 2: quote + RS pre-screen ──────────────────────────────────────
    df_quote = tech.get_quote_prices(tickers).sort_values("symbol")
    df_rs = tech.get_change_prices(tickers)
    df_quote = df_quote.merge(df_rs, on="symbol", how="left")

    pre_mask = (df_quote["SCREENER"] == 1) & (df_quote["RS"] > 80)
    candidates = df_quote[pre_mask]["symbol"].tolist()
    log.info(
        "[nis_momentum] after pre-screen (SCREENER==1 AND RS>80): %d candidates",
        len(candidates),
    )

    # ── Step 3: per-ticker technical + fundamentals ────────────────────────
    rows: list[dict] = []
    for i, symbol in enumerate(candidates, 1):
        if i % 25 == 0:
            log.info(
                "[nis_momentum] screening %d/%d (%s)", i, len(candidates), symbol
            )
        try:
            _df, tt, error = tech.get_screening(
                symbol,
                startdate=startdate.strftime(_DATE_FMT),
                enddate=today.strftime(_DATE_FMT),
            )
            if error or tt is None:
                continue

            df_fund = fund.get_earnings_data(symbol)
            tt["increasing_eps"] = bool(df_fund["eps_sma_direction"].iloc[-1] == 1)
            tt["beat_estimate"] = bool(df_fund.tail(3)["beat_estimate"].sum() == 3)
            tt["PASSED_FUNDAMENTALS"] = bool(
                tt["increasing_eps"] and tt["beat_estimate"]
            )

            try:
                meta = df_tickers[df_tickers["symbol"] == symbol].iloc[0]
                tt["sector"] = meta.get("sector", "N/A")
                tt["subSector"] = meta.get("subSector", meta.get("industry", "N/A"))
            except Exception:
                tt["sector"] = "N/A"
                tt["subSector"] = "N/A"

            rows.append(tt)
        except Exception as exc:
            log.warning("[nis_momentum] %s failed: %s", symbol, exc)

    # ── Step 4: filter passers (technical AND fundamental) ─────────────────
    passed = [
        r
        for r in rows
        if r.get("Passed") is True and r.get("PASSED_FUNDAMENTALS") is True
    ]
    # Lower RS_Rank = higher percentile.
    passed.sort(key=lambda r: (r.get("RS_Rank") is None, r.get("RS_Rank") or 9999))

    log.info(
        "[nis_momentum] passed full NIS Momentum: %d / %d screened",
        len(passed), len(rows),
    )

    if not passed:
        return ScreeningResult(
            triggered=False,
            summary=None,
            ticker_count=0,
            data_used={
                "universe_size": len(tickers),
                "pre_screen_candidates": len(candidates),
                "screened": len(rows),
                "passed": 0,
            },
        )

    symbols_serialized = [_serialize_row(r) for r in passed]
    summary = _format_summary(passed, total_candidates=len(candidates))
    data_used = {
        "universe_size": len(tickers),
        "pre_screen_candidates": len(candidates),
        "screened": len(rows),
        "passed": len(passed),
        "symbols": symbols_serialized,
    }
    return ScreeningResult(
        triggered=True,
        summary=summary,
        ticker_count=len(passed),
        data_used=data_used,
    )


def _serialize_row(r: dict) -> dict:
    """Project the per-ticker dict into a JSON-safe shape that includes every
    field the /protected/screenings + /screenings/[slug] tables render."""
    def _b(k: str) -> bool:
        return bool(r.get(k))

    def _n(k: str):
        v = r.get(k)
        if v is None:
            return None
        try:
            f = float(v)
            return f if f == f else None  # NaN check
        except Exception:
            return None

    return {
        "symbol": r.get("ticker"),
        "sector": r.get("sector"),
        "subSector": r.get("subSector"),
        # Technical
        "RS_Rank": _n("RS_Rank"),
        "Passed": _b("Passed"),
        "PriceOverSMA150And200": _b("PriceOverSMA150And200"),
        "SMA150AboveSMA200": _b("SMA150AboveSMA200"),
        "SMA50AboveSMA150And200": _b("SMA50AboveSMA150And200"),
        "SMA200Slope": _b("SMA200Slope"),
        "PriceAbove25Percent52WeekLow": _b("PriceAbove25Percent52WeekLow"),
        "PriceWithin25Percent52WeekHigh": _b("PriceWithin25Percent52WeekHigh"),
        "RSOver70": _b("RSOver70"),
        # Supplementary technical (added by get_screening)
        "adr_pct": _n("adr_pct"),
        "vol_ratio_today": _n("vol_ratio_today"),
        "up_down_vol_ratio": _n("up_down_vol_ratio"),
        "accumulation": _b("accumulation"),
        "rs_line_new_high": _b("rs_line_new_high"),
        "within_buy_range": _b("within_buy_range"),
        "extended": _b("extended"),
        # Growth fundamentals
        "increasing_eps": _b("increasing_eps"),
        "beat_estimate": _b("beat_estimate"),
        "PASSED_FUNDAMENTALS": _b("PASSED_FUNDAMENTALS"),
    }


def _format_summary(passed: list[dict], total_candidates: int) -> str:
    n = len(passed)
    head = (
        f"<b>NIS Momentum</b>\n"
        f"{n} stock{'s' if n != 1 else ''} passed (from {total_candidates} candidates)\n"
    )
    shown = passed[:_SUMMARY_TOP_N]
    lines = []
    for r in shown:
        sym = r.get("ticker", "?")
        sector = r.get("sector") or "—"
        rs = r.get("RS_Rank")
        rs_part = f" · RS rank {rs}" if rs is not None else ""
        lines.append(f"• <b>{sym}</b> — {sector}{rs_part}")
    body = "\n".join(lines)
    tail = "" if n <= _SUMMARY_TOP_N else f"\n…and {n - _SUMMARY_TOP_N} more"
    return f"{head}\n{body}{tail}"
