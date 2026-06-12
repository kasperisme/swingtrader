"""IPO Screener — recent IPOs run through the AI-Supercycle screen.

Universe: every actively-traded NYSE + NASDAQ common stock whose FMP ``ipoDate``
falls within the last year. Unlike AI Supercycle (a fixed curated basket) the
basket here is rebuilt every run from the IPO calendar embedded in company
profiles.

Screening: identical to ``ai_supercycle`` — for every name it computes
  • Momentum — the shared trend template (50/150/200 SMA alignment + slope,
    proximity to 52-week extremes, relative strength) via services.screener.technical.
  • Growth fundamentals — increasing EPS direction AND 3 consecutive quarterly
    beats via services.screener.fundamentals.

Like AI Supercycle it emits EVERY name it can screen (not just the passers), so
the gallery shows the whole IPO board ranked by relative-strength rank, with
per-row gate flags (passed_momentum / passed_fundamentals / passed_all).

Adaptive SMAs for short history: the Minervini trend template normally needs
~200 trading days to form its 200-day SMA, which a stock that listed a few
months ago doesn't have. Rather than NaN-ing every moving-average gate (which
would make the whole IPO board fail), this screener runs ``get_screening`` with
``sma_min_periods=_SMA_MIN_PERIODS`` — the SMAs average whatever history is
available (capped at the period) once a name has at least that many sessions.
The trade-off is deliberate and known: a "200-day SMA" computed on, say, 90 bars
is a shorter, looser average than a true SMA200, so the alignment gates are more
lenient for the youngest names. Names with fewer than _SMA_MIN_PERIODS sessions
still NaN out and fall to the bottom of the board.

Runtime: one profile sweep of the exchange universe (comma-batched, ~cheap) to
find the IPOs, then one FMP screening + earnings pull per IPO name. Intended to
run daily before the open.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from services.screener import fundamentals, technical

from ..types import ScreeningResult

log = logging.getLogger(__name__)

_LOOKBACK_DAYS = 365  # chart history window handed to the trend template
_IPO_WINDOW_DAYS = 365  # "IPO'd within the last year"
_DATE_FMT = "%Y-%m-%d"
_SUMMARY_TOP_N = 25  # cap symbols listed in the Telegram summary
# Minimum sessions before any SMA (50/150/200) produces a value. Below this a
# fresh listing is too young to read a trend from; at/above it the SMAs average
# whatever history exists, capped at their period. ~50 sessions ≈ 10 weeks.
_SMA_MIN_PERIODS = 50


def _passed_momentum(tt: dict) -> bool:
    """Trend-template ``Passed`` AND price above its 50-day SMA (numpy-safe)."""
    return bool(tt.get("Passed")) and bool(tt.get("PriceOverSMA50"))


def run(
    client, screening: dict
) -> ScreeningResult:  # noqa: ARG001 — client unused; FMP/REST is the data source
    import pandas as pd

    tech = technical.technical()
    fund = fundamentals.Fundamentals()

    today = datetime.today()
    startdate = today - timedelta(days=_LOOKBACK_DAYS)

    # ── Step 1: recent-IPO universe ────────────────────────────────────────
    # Pull the full actively-trading NYSE + NASDAQ list, then keep only names
    # whose company-profile ipoDate lands inside the trailing year. profile() is
    # comma-batched (80 symbols / request) so sweeping the whole universe for
    # ipoDate is a handful of calls, not one-per-symbol.
    df_col = []
    for exch in ("NYSE", "NASDAQ"):
        try:
            df_col.append(tech.get_exhange_tickers(exch))
        except Exception as exc:
            log.warning("[ipo_screener] exchange %s fetch failed: %s", exch, exc)

    if not df_col:
        return ScreeningResult(
            triggered=False,
            summary="Could not fetch the exchange universe this run.",
            ticker_count=0,
            data_used={"universe_size": 0},
            error="no_universe",
        )

    df_all = (
        pd.concat(df_col, axis=0)
        .dropna(subset=["symbol"])
        .drop_duplicates(subset=["symbol"])
    )
    all_syms = df_all["symbol"].astype(str).tolist()
    log.info("[ipo_screener] exchange universe: %d symbols", len(all_syms))

    prof = tech.fmp.profile(all_syms)
    if prof.empty or "ipoDate" not in prof.columns:
        return ScreeningResult(
            triggered=False,
            summary="Could not fetch IPO dates this run.",
            ticker_count=0,
            data_used={"universe_size": len(all_syms)},
            error="no_ipo_data",
        )

    prof = prof.copy()
    prof["ipo_dt"] = pd.to_datetime(prof["ipoDate"], errors="coerce")
    cutoff = pd.Timestamp(today - timedelta(days=_IPO_WINDOW_DAYS))
    recent = prof[(prof["ipo_dt"].notna()) & (prof["ipo_dt"] >= cutoff)].sort_values(
        "ipo_dt", ascending=False
    )
    tickers = recent["symbol"].astype(str).tolist()

    # symbol → (sector, industry, ipoDate) for per-row enrichment.
    meta: dict[str, tuple] = {
        str(r["symbol"]): (r.get("sector"), r.get("industry"), r.get("ipoDate"))
        for _, r in recent.iterrows()
    }
    log.info(
        "[ipo_screener] IPOs in last %d days: %d (of %d listed)",
        _IPO_WINDOW_DAYS, len(tickers), len(all_syms),
    )

    if not tickers:
        return ScreeningResult(
            triggered=False,
            summary="No stocks IPO'd in the last year could be found this run.",
            ticker_count=0,
            data_used={"universe_size": len(all_syms), "ipos_found": 0, "screened": 0},
            error="empty_result",
        )

    # Relative strength is ranked WITHIN the IPO cohort — populate self.df_rs
    # over the full list before the per-symbol screening loop (get_screening
    # reads RS_Rank / RSOver70 from it).
    try:
        tech.get_quote_prices(tickers)
        tech.get_change_prices(tickers)
    except Exception as exc:
        log.warning("[ipo_screener] RS pre-compute failed: %s", exc)

    # ── Step 2: per-ticker technical + fundamentals (same as ai_supercycle) ─
    rows: list[dict] = []
    screened = 0
    for i, symbol in enumerate(tickers, 1):
        if i % 25 == 0:
            log.info("[ipo_screener] screening %d/%d (%s)", i, len(tickers), symbol)
        try:
            _df, tt, error = tech.get_screening(
                symbol,
                startdate=startdate.strftime(_DATE_FMT),
                enddate=today.strftime(_DATE_FMT),
                sma_min_periods=_SMA_MIN_PERIODS,
            )
            if error or tt is None:
                # Either fewer than _SMA_MIN_PERIODS sessions, or no RS entry.
                log.info("[ipo_screener] %s: no technical data (%s)", symbol, error)
                continue

            # Growth fundamentals overlay (best-effort — thin coverage on the
            # newest names shouldn't drop them from the board).
            try:
                df_fund = fund.get_earnings_data(symbol)
                tt["increasing_eps"] = bool(df_fund["eps_sma_direction"].iloc[-1] == 1)
                tt["beat_estimate"] = bool(df_fund.tail(3)["beat_estimate"].sum() == 3)
            except Exception as exc:
                log.info("[ipo_screener] %s: earnings data unavailable (%s)", symbol, exc)
                tt["increasing_eps"] = False
                tt["beat_estimate"] = False

            tt["PASSED_FUNDAMENTALS"] = bool(tt["increasing_eps"] and tt["beat_estimate"])
            tt["passed_momentum"] = _passed_momentum(tt)
            tt["passed_all"] = bool(tt["passed_momentum"] and tt["PASSED_FUNDAMENTALS"])

            sec, ind, ipo = meta.get(symbol, (None, None, None))
            tt["sector"] = sec or "N/A"
            tt["subSector"] = ind or "N/A"
            tt["group"] = ind or sec or "Recent IPO"
            tt["ipo_date"] = ipo[:10] if isinstance(ipo, str) and ipo else None

            screened += 1
            rows.append(tt)
        except Exception as exc:
            log.warning("[ipo_screener] %s failed: %s", symbol, exc)

    if not rows:
        return ScreeningResult(
            triggered=False,
            summary=(
                f"Found {len(tickers)} recent IPOs, but none had enough trading "
                "history to screen yet."
            ),
            ticker_count=0,
            data_used={
                "universe_size": len(all_syms),
                "ipos_found": len(tickers),
                "screened": 0,
                "passed": 0,
            },
            error="empty_result",
        )

    # Sort by relative-strength rank (lower RS_Rank = stronger). Names missing a
    # rank sink to the bottom.
    rows.sort(key=lambda r: (r.get("RS_Rank") is None, r.get("RS_Rank") or 9999))

    passed_all = sum(1 for r in rows if r.get("passed_all"))
    in_uptrend = sum(1 for r in rows if r.get("passed_momentum"))
    log.info(
        "[ipo_screener] screened %d/%d IPOs — %d in uptrend, %d clear all gates",
        screened, len(tickers), in_uptrend, passed_all,
    )

    symbols_serialized = [_serialize_row(r) for r in rows]
    summary = _format_summary(rows, in_uptrend=in_uptrend, passed_all=passed_all)
    data_used = {
        "universe_size": len(all_syms),
        "ipos_found": len(tickers),
        "screened": screened,
        "in_uptrend": in_uptrend,
        "passed": passed_all,
        "sma_min_periods": _SMA_MIN_PERIODS,
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
    /protected/screenings + /screenings/[slug] tables render. Same columns as
    ai_supercycle, plus the IPO date."""

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
        "ipo_date": r.get("ipo_date"),
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
        f"<b>IPO Screener</b>\n"
        f"{n} recent IPO{'s' if n != 1 else ''} screened · {in_uptrend} in a "
        f"momentum uptrend · {passed_all} clear momentum + fundamentals\n"
    )
    shown = rows[:_SUMMARY_TOP_N]
    lines = []
    for r in shown:
        sym = r.get("ticker", "?")
        ind = r.get("subSector") or r.get("sector") or "—"
        rs = r.get("RS_Rank")
        rs_part = f" · RS rank {rs}" if rs is not None else ""
        flag = " ✅" if r.get("passed_all") else (" 📈" if r.get("passed_momentum") else "")
        lines.append(f"• <b>{sym}</b> — {ind}{rs_part}{flag}")
    body = "\n".join(lines)
    tail = "" if n <= _SUMMARY_TOP_N else f"\n…and {n - _SUMMARY_TOP_N} more"
    return f"{head}\n{body}{tail}"
