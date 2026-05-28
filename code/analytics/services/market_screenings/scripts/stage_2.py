"""Stage 2 (Mark Minervini) screener.

A ticker passes if and only if ALL of:
  1. close > SMA50 > SMA150 > SMA200  (full moving-average ladder)
  2. SMA200 rising                    (uptrend confirmed)
  3. close within 25% of 52-week high (near top of range)

No RS pre-screen, no fundamentals, no other filters — by design.

Runtime: the full ~5k NYSE+NASDAQ universe is first reduced via FMP's bulk
quote endpoint (one call per 400 tickers), which precomputes three of the
stage-2 ladder/range conditions: close > SMA200, SMA50 > SMA200, and the
within-25%-of-52w-high check. Only the survivors are deep-screened to
verify the remaining gates: the SMA150 rung of the ladder (FMP `/quote`
doesn't expose `priceAvg150`) and the rising-SMA200 slope (needs daily
history). This typically collapses ~5,000 tickers to a few hundred
candidates and turns a 25–45 min run into a ~2–3 min run.
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

    tickers = df_tickers["symbol"].to_list()
    log.info("[stage_2] universe: %d tickers", len(tickers))

    # ── Step 2: bulk pre-screen via FMP /quote ────────────────────────────
    # `get_quote_prices` batches the universe into `/api/v3/quote/<csv>` calls
    # and derives boolean flags from the returned price/priceAvg50/
    # priceAvg200/yearHigh fields. Three of those flags match stage-2's
    # exact semantics:
    #   PRICE_OVER_SMA200        → close > SMA200
    #   SMA50_OVER_SMA200        → SMA50  > SMA200
    #   PRICE_25PCT_WITHIN_HIGH  → close within 25% of 52-week high (exclusive of new highs)
    # We pre-filter on those three so the expensive per-ticker daily-chart
    # call only runs for tickers that already satisfy them. The two stage-2
    # gates the bulk quote can't decide are still verified per-ticker below
    # (SMA150 rung of the ladder, rising SMA200 slope).
    df_quote = tech.get_quote_prices(tickers)
    pre_mask = (
        (df_quote["PRICE_OVER_SMA200"] == 1)
        & (df_quote["SMA50_OVER_SMA200"] == 1)
        & (df_quote["PRICE_25PCT_WITHIN_HIGH"] == 1)
    )
    candidates = df_quote.loc[pre_mask, "symbol"].dropna().tolist()
    log.info(
        "[stage_2] bulk pre-screen: %d / %d tickers (close>SMA200, SMA50>SMA200, within 25%% of 52w high)",
        len(candidates),
        len(tickers),
    )

    # Prime the technical module's RS dataframe — `minervini_trend_template`
    # reads `self.df_rs` for the RS fields it always computes; without this
    # it raises 'NoneType' is not subscriptable. RS is not used in stage-2
    # filtering, so prime on the candidate subset only (smaller payload).
    if candidates:
        tech.get_change_prices(candidates)

    # ── Step 3: per-ticker deep-screen on survivors only ──────────────────
    rows: list[dict] = []
    for i, symbol in enumerate(candidates, 1):
        if i % 25 == 0:
            log.info(
                "[stage_2] deep-screening %d/%d (%s)", i, len(candidates), symbol
            )
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
                "pre_screen_candidates": len(candidates),
                "screened": len(rows),
                "passed": 0,
            },
        )

    summary = _format_summary(passed, total_screened=len(rows))
    data_used = {
        "universe_size": len(tickers),
        "pre_screen_candidates": len(candidates),
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
