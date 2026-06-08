"""AI Supercycle — momentum + fundamentals over a curated AI-supercycle universe.

Unlike NIS Momentum / NIS Fundamentals (which scan the whole NYSE + NASDAQ),
this screening runs over a FIXED, hand-curated basket of the names driving the
AI buildout — GPUs/compute, AI memory, semicap equipment, optical/interconnect,
data-center power & thermal, the utilities feeding the load, and the
hyperscalers spending the capex.

For every name it computes:
  • Momentum — the shared trend template (50/150/200 SMA alignment + slope,
    proximity to 52-week extremes, relative strength) via services.screener.technical.
  • Growth fundamentals — increasing EPS direction AND 3 consecutive quarterly
    beats via services.screener.fundamentals.

It emits EVERY name it can screen (not just the passers) so the gallery shows
the whole basket as a board, ranked by relative-strength rank, with per-row
flags for which gates each name clears:
  • passed_momentum      — trend template + price over its 50-day SMA
  • passed_fundamentals   — increasing EPS + 3 straight beats
  • passed_all            — both of the above

Runtime: one FMP screening + earnings pull per name (~40 names) → a couple of
minutes. Intended to run daily before the open so subscribers get a fresh
momentum read on the theme.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from services.screener import fundamentals, technical

from ..types import ScreeningResult

log = logging.getLogger(__name__)

_LOOKBACK_DAYS = 365
_DATE_FMT = "%Y-%m-%d"
_SUMMARY_TOP_N = 25  # cap symbols listed in the Telegram summary

# ── Curated universe ─────────────────────────────────────────────────────────
# symbol → theme group (shown as `subSector` in the gallery table). Keep this
# the single source of truth for the basket; add/remove names here.
_UNIVERSE: dict[str, str] = {
    # GPUs / AI compute
    "NVDA": "AI compute", "AMD": "AI compute", "AVGO": "AI compute",
    "MRVL": "AI compute", "ARM": "AI compute",
    # Networking / interconnect / optics
    "ANET": "Networking & optics", "CRDO": "Networking & optics",
    "ALAB": "Networking & optics", "COHR": "Networking & optics",
    "LITE": "Networking & optics", "CIEN": "Networking & optics",
    # AI memory / storage
    "MU": "Memory & storage", "SNDK": "Memory & storage",
    "WDC": "Memory & storage", "STX": "Memory & storage",
    # Semicap equipment
    "ASML": "Semicap equipment", "AMAT": "Semicap equipment",
    "LRCX": "Semicap equipment", "KLAC": "Semicap equipment",
    "TER": "Semicap equipment",
    # Foundry / IDM
    "TSM": "Foundry & IDM", "INTC": "Foundry & IDM", "GFS": "Foundry & IDM",
    # AI servers / systems
    "SMCI": "AI servers", "DELL": "AI servers", "HPE": "AI servers",
    # Power, thermal & data-center infrastructure
    "VRT": "Power & thermal", "ETN": "Power & thermal", "GEV": "Power & thermal",
    "POWL": "Power & thermal", "NVT": "Power & thermal", "MOD": "Power & thermal",
    # Power generation feeding AI load
    "VST": "Power generation", "CEG": "Power generation",
    "TLN": "Power generation", "NRG": "Power generation",
    # Power / analog semis
    "MPWR": "Power & analog semis", "ON": "Power & analog semis",
    "NXPI": "Power & analog semis",
    # Hyperscalers / AI platforms
    "MSFT": "Hyperscalers", "GOOGL": "Hyperscalers", "AMZN": "Hyperscalers",
    "META": "Hyperscalers", "ORCL": "Hyperscalers",
    # Neoclouds / AI infrastructure
    "NBIS": "Neocloud",
}


def _passed_momentum(tt: dict) -> bool:
    """Trend-template ``Passed`` AND price above its 50-day SMA (numpy-safe)."""
    return bool(tt.get("Passed")) and bool(tt.get("PriceOverSMA50"))


def run(
    client, screening: dict
) -> ScreeningResult:  # noqa: ARG001 — client unused; FMP/REST is the data source
    tech = technical.technical()
    fund = fundamentals.Fundamentals()

    today = datetime.today()
    startdate = today - timedelta(days=_LOOKBACK_DAYS)

    tickers = list(_UNIVERSE.keys())
    log.info("[ai_supercycle] universe: %d curated names", len(tickers))

    # Relative strength is ranked WITHIN the basket — populate self.df_rs over
    # the full curated list before the per-symbol screening loop (get_screening
    # reads RS_Rank / RSOver70 from it).
    try:
        tech.get_quote_prices(tickers)
        tech.get_change_prices(tickers)
    except Exception as exc:
        log.warning("[ai_supercycle] RS pre-compute failed: %s", exc)

    rows: list[dict] = []
    screened = 0
    for i, symbol in enumerate(tickers, 1):
        if i % 10 == 0:
            log.info("[ai_supercycle] screening %d/%d (%s)", i, len(tickers), symbol)
        try:
            _df, tt, error = tech.get_screening(
                symbol,
                startdate=startdate.strftime(_DATE_FMT),
                enddate=today.strftime(_DATE_FMT),
            )
            if error or tt is None:
                log.info("[ai_supercycle] %s: no technical data (%s)", symbol, error)
                continue

            # Growth fundamentals overlay (best-effort — thin coverage on the
            # newest names shouldn't drop them from the board).
            try:
                df_fund = fund.get_earnings_data(symbol)
                tt["increasing_eps"] = bool(df_fund["eps_sma_direction"].iloc[-1] == 1)
                tt["beat_estimate"] = bool(df_fund.tail(3)["beat_estimate"].sum() == 3)
            except Exception as exc:
                log.info("[ai_supercycle] %s: earnings data unavailable (%s)", symbol, exc)
                tt["increasing_eps"] = False
                tt["beat_estimate"] = False

            tt["PASSED_FUNDAMENTALS"] = bool(tt["increasing_eps"] and tt["beat_estimate"])
            tt["passed_momentum"] = _passed_momentum(tt)
            tt["passed_all"] = bool(tt["passed_momentum"] and tt["PASSED_FUNDAMENTALS"])
            tt["group"] = _UNIVERSE.get(symbol, "AI supercycle")

            screened += 1
            rows.append(tt)
        except Exception as exc:
            log.warning("[ai_supercycle] %s failed: %s", symbol, exc)

    if not rows:
        return ScreeningResult(
            triggered=False,
            summary="No AI-supercycle names could be screened this run.",
            ticker_count=0,
            data_used={"universe_size": len(tickers), "screened": 0, "passed": 0},
            error="empty_result",
        )

    # Sort by relative-strength rank (lower RS_Rank = stronger). Names missing a
    # rank sink to the bottom.
    rows.sort(key=lambda r: (r.get("RS_Rank") is None, r.get("RS_Rank") or 9999))

    passed_all = sum(1 for r in rows if r.get("passed_all"))
    in_uptrend = sum(1 for r in rows if r.get("passed_momentum"))
    log.info(
        "[ai_supercycle] screened %d/%d — %d in uptrend, %d clear all gates",
        screened, len(tickers), in_uptrend, passed_all,
    )

    symbols_serialized = [_serialize_row(r) for r in rows]
    summary = _format_summary(rows, in_uptrend=in_uptrend, passed_all=passed_all)
    data_used = {
        "universe_size": len(tickers),
        "screened": screened,
        "in_uptrend": in_uptrend,
        "passed": passed_all,
        "symbols": symbols_serialized,
    }
    return ScreeningResult(
        triggered=True,
        summary=summary,
        ticker_count=len(rows),
        data_used=data_used,
    )


def _serialize_row(r: dict) -> dict:
    """Project the per-ticker dict into the JSON-safe shape the
    /protected/screenings + /screenings/[slug] tables render."""

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
        "sector": "Technology",
        "subSector": r.get("group"),
        # Theme + gate summary
        "group": r.get("group"),
        "passed_momentum": _b("passed_momentum"),
        "passed_all": _b("passed_all"),
        # Technical / momentum
        "RS_Rank": _n("RS_Rank"),
        "Passed": _b("Passed"),
        "PriceOverSMA150And200": _b("PriceOverSMA150And200"),
        "PriceOverSMA50": _b("PriceOverSMA50"),
        "SMA150AboveSMA200": _b("SMA150AboveSMA200"),
        "SMA50AboveSMA150And200": _b("SMA50AboveSMA150And200"),
        "SMA200Slope": _b("SMA200Slope"),
        "PriceAbove25Percent52WeekLow": _b("PriceAbove25Percent52WeekLow"),
        "PriceWithin25Percent52WeekHigh": _b("PriceWithin25Percent52WeekHigh"),
        "RSOver70": _b("RSOver70"),
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


def _format_summary(rows: list[dict], in_uptrend: int, passed_all: int) -> str:
    n = len(rows)
    head = (
        f"<b>AI Supercycle</b>\n"
        f"{n} name{'s' if n != 1 else ''} tracked · {in_uptrend} in a momentum "
        f"uptrend · {passed_all} clear momentum + fundamentals\n"
    )
    shown = rows[:_SUMMARY_TOP_N]
    lines = []
    for r in shown:
        sym = r.get("ticker", "?")
        group = r.get("group") or "—"
        rs = r.get("RS_Rank")
        rs_part = f" · RS rank {rs}" if rs is not None else ""
        flag = " ✅" if r.get("passed_all") else (" 📈" if r.get("passed_momentum") else "")
        lines.append(f"• <b>{sym}</b> — {group}{rs_part}{flag}")
    body = "\n".join(lines)
    tail = "" if n <= _SUMMARY_TOP_N else f"\n…and {n - _SUMMARY_TOP_N} more"
    return f"{head}\n{body}{tail}"
