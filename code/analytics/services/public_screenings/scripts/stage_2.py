"""Stage 2 (Mark Minervini) screener.

A ticker passes if and only if ALL of:
  1. close > SMA50 > SMA150 > SMA200  (full moving-average ladder)
  2. SMA200 rising                    (uptrend confirmed)
  3. close within 25% of 52-week high (near top of range)

No RS pre-screen, no fundamentals, no other filters — by design.

Runtime note: every ticker in the universe is deep-screened (no
pre-filtering). Expect this to scale linearly with universe size; tune
`_TESTING_TICKER_CAP` while iterating and remove it before going wide.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from services.screener import technical

from ..types import ScreeningResult

log = logging.getLogger(__name__)

_LOOKBACK_DAYS = 365
_DATE_FMT = "%Y-%m-%d"
_SUMMARY_TOP_N = 25  # cap symbols listed in summary (Telegram readability)
_TESTING_TICKER_CAP = 200  # TEMP: cap universe size for dev testing. Remove for prod.


def run(
    client, screening: dict
) -> ScreeningResult:  # noqa: ARG001 — client unused; FMP/REST is the data source
    tech = technical.technical()

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
        log.warning("[stage_2] TESTING cap active: %d tickers", _TESTING_TICKER_CAP)
    tickers = df_tickers["symbol"].to_list()
    log.info("[stage_2] universe: %d tickers", len(tickers))

    # Prime the technical module's RS dataframe in one batch call.
    # `minervini_trend_template` reads `self.df_rs` internally for the RS
    # fields it always computes; without this it raises 'NoneType' object is
    # not subscriptable. We do NOT use the return value for filtering — RS is
    # not part of the stage-2 pass criteria.
    tech.get_change_prices(tickers)

    # ── Step 2: per-ticker stage 2 check ──────────────────────────────────
    rows: list[dict] = []
    for i, symbol in enumerate(tickers, 1):
        if i % 25 == 0:
            log.info("[stage_2] screening %d/%d (%s)", i, len(tickers), symbol)
        try:
            df_data, tt, error = tech.get_screening(
                symbol,
                startdate=startdate.strftime(_DATE_FMT),
                enddate=today.strftime(_DATE_FMT),
            )
            if error or tt is None or df_data is None or len(df_data) == 0:
                continue

            last = df_data.iloc[-1]
            close, sma50, sma150, sma200 = (
                last.get("close"),
                last.get("SMA50"),
                last.get("SMA150"),
                last.get("SMA200"),
            )
            # 1. price > MA50 > MA150 > MA200
            ma_ladder = bool(
                pd.notna(sma50)
                and pd.notna(sma150)
                and pd.notna(sma200)
                and close > sma50 > sma150 > sma200
            )
            # 2. 200-day MA rising — reuse the slope check from get_screening
            ma200_rising = bool(tt.get("SMA200Slope"))
            # 3. near 52-week high — reuse the "within 25% of 52w high" check
            near_52w_high = bool(tt.get("PriceWithin25Percent52WeekHigh"))

            passed_stage_2 = ma_ladder and ma200_rising and near_52w_high

            tt["ma_ladder"] = ma_ladder
            tt["ma200_rising"] = ma200_rising
            tt["near_52w_high"] = near_52w_high
            tt["stage_2_pass"] = passed_stage_2

            try:
                meta = df_tickers[df_tickers["symbol"] == symbol].iloc[0]
                tt["sector"] = meta.get("sector", "N/A")
                tt["subSector"] = meta.get("subSector", meta.get("industry", "N/A"))
            except Exception:
                tt["sector"] = "N/A"
                tt["subSector"] = "N/A"

            rows.append(tt)
        except Exception as exc:
            log.warning("[stage_2] %s failed: %s", symbol, exc)

    # ── Step 3: collect passers + format result ────────────────────────────
    passed = [r for r in rows if r.get("stage_2_pass")]
    passed.sort(key=lambda r: r.get("ticker", ""))

    log.info(
        "[stage_2] passed Minervini stage 2: %d / %d screened", len(passed), len(rows)
    )

    if not passed:
        return ScreeningResult(
            triggered=False,
            summary=None,
            ticker_count=0,
            data_used={
                "universe_size": len(tickers),
                "screened": len(rows),
                "passed": 0,
            },
        )

    summary = _format_summary(passed, total_screened=len(rows))
    data_used = {
        "universe_size": len(tickers),
        "screened": len(rows),
        "passed": len(passed),
        "symbols": [
            {
                "symbol": r["ticker"],
                "sector": r.get("sector"),
                "subSector": r.get("subSector"),
            }
            for r in passed
        ],
    }
    return ScreeningResult(
        triggered=True,
        summary=summary,
        ticker_count=len(passed),
        data_used=data_used,
    )


def _format_summary(passed: list[dict], total_screened: int) -> str:
    n = len(passed)
    head = (
        f"<b>Stage 2 (Minervini)</b>\n"
        f"{n} stock{'s' if n != 1 else ''} passed (from {total_screened} screened)\n"
    )
    shown = passed[:_SUMMARY_TOP_N]
    lines = [
        f"• <b>{r.get('ticker', '?')}</b> — {r.get('sector') or '—'}" for r in shown
    ]
    body = "\n".join(lines)
    tail = "" if n <= _SUMMARY_TOP_N else f"\n…and {n - _SUMMARY_TOP_N} more"
    return f"{head}\n{body}{tail}"
