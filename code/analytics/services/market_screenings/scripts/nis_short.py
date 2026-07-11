"""NIS Short — the inverse of NIS Momentum, for the SHORT side (Minervini / O'Neil).

The core insight (straight from O'Neil and Minervini): you do NOT short weakness
that is already priced in. A stock at new lows with bad fundamentals is beaten
down and prime short-squeeze fuel. The best shorts are FORMER LEADERS rolling
over after a climax — you short distribution and failure, not perennial dogs.

So this is not a naive "flip every long rule". The universe is deliberately
seeded with ex-winners (up 100%+ in the prior 1–3 years) that are now in a
Stage-4 decline. Market regime (S&P vs its 200-day) is computed and surfaced
for context — shorting works best in a confirmed downtrend — but it does NOT
gate the scan; the screen always runs and the AI analysis pass weighs regime.

Pipeline (mirror of nis_momentum, inverted):
  1. Universe: all NYSE + NASDAQ tickers.
  2. Inverted quote + RS pre-screen — actively traded, price < SMA200,
     SMA50 < SMA200, ≥25% below the 52-week high, AND weak RS (bottom ~30%).
  3. Stage-4 decline template (all required):
       • close < SMA50 < SMA150 < SMA200
       • SMA200 falling (20-day slope confirmation, mirror of the long slope gate)
       • close ≥ 25% below the 52-week high, and that high is STALE (made months ago)
       • RS weak (RS < 30 — inverse of the long side's RS > 70)
  4. Former-leader gate (the single most important filter): the stock ran
     100%+ from a prior trough to its peak inside the lookback, and the peak
     is ≥ ~5 weeks old (O'Neil: the best shorts are 5–15 weeks after the top,
     not at the exact peak — shorting the top gets you squeezed).
  5. Distribution volume: down-days heavier than up-days over the last 50
     sessions (up/down-volume ratio ≤ 0.85 — the inverse of accumulation).
  6. Decelerating fundamentals: EPS momentum rolling over (not accelerating)
     AND (EPS SMA turning down OR a recent earnings miss). Deceleration and
     disappointment, not absolute badness.
  7. Liquidity floor: enough average daily dollar volume to borrow and exit.

A ticker is reported only if it passes EVERY technical AND fundamental gate.

Squeeze note: the one filter the long side never needs is short-interest /
days-to-cover screening — heavily-shorted names are squeeze fuel, not
opportunity. FMP short-interest is not wired into ``services.screener.fmp``,
so that gate is enforced downstream by (a) the liquidity floor here and
(b) the per-ticker AI analysis prompt, which is told to reject crowded shorts
and to demand rally-into-resistance entries with a hard stop. See
``_SQUEEZE_SI_MAX_PCT`` for the hook to wire it in once the data exists.

Runtime note: like nis_momentum, hits FMP per surviving ticker (daily chart +
earnings). Expect several minutes for a full run. Tune ``_TESTING_TICKER_CAP``
while iterating.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from services.screener import fundamentals, technical

from ..types import ScreeningResult

log = logging.getLogger(__name__)

# 3 years of daily history — enough to detect a prior 100%+ advance (O'Neil's
# short setups almost always come from stocks that were huge former winners over
# the last 1–3 years) while still resolving SMA150/200 and a stale 52w high.
_LOOKBACK_DAYS = 1095
_DATE_FMT = "%Y-%m-%d"
_SUMMARY_TOP_N = 25  # cap symbols listed in summary (Telegram readability)
_TESTING_TICKER_CAP = 0  # 0 = no cap; set to a small number while iterating

# ── Tunables ────────────────────────────────────────────────────────────────
_RS_MAX = 30              # weak RS gate (inverse of the long side's RS > 70)
_OFF_HIGH_MIN_PCT = 25.0  # must be ≥ this far below the 52-week high
_PEAK_STALE_MIN_SESSIONS = 25  # peak ≥ ~5 weeks old (5–15 weeks post-top zone)
_PRIOR_ADVANCE_MIN_PCT = 100.0  # former leader: ran ≥100% into its peak
_DISTRIBUTION_UD_MAX = 0.85    # up/down-vol ratio ≤ this = distribution
_MIN_DOLLAR_VOL = 10_000_000   # avg daily $ volume floor (borrow/exit liquidity)
_SESSIONS_52W = 252

# Squeeze hook — max short-interest-as-%-of-float to allow. Not enforced yet
# because FMP short-interest isn't wrapped in services.screener.fmp; wire a
# fetch in _squeeze_ok() and flip this on when the data source exists.
_SQUEEZE_SI_MAX_PCT = None


def run(
    client, screening: dict
) -> ScreeningResult:  # noqa: ARG001 — client unused; FMP/REST is the data source
    import pandas as pd

    tech = technical.technical()
    fund = fundamentals.Fundamentals()

    today = datetime.today()
    startdate = today - timedelta(days=_LOOKBACK_DAYS)

    # ── Step 0: market regime (informational) ──────────────────────────────
    # The screen no longer gates on regime — it always scans. We still compute
    # the S&P read for context (surfaced in data_used and weighed by the AI
    # analysis pass) and because get_market_direction populates tech.spx_df,
    # which the per-ticker RS-line metric depends on.
    try:
        market = tech.get_market_direction()
    except Exception as exc:  # never let a data hiccup crash the run
        log.warning("[nis_short] market direction lookup failed: %s", exc)
        market = {}

    spx_below_200 = not bool(market.get("price_above_sma200", True))
    regime = {
        "spx_condition": market.get("spx_condition"),
        "spx_price_above_sma200": market.get("price_above_sma200"),
        "spx_sma50_rising": market.get("sma50_rising"),
        "distribution_days": market.get("distribution_days"),
        "favorable_for_shorts": spx_below_200,
    }

    # ── Step 1: tickers ────────────────────────────────────────────────────
    df_col = []
    for exch in ("NYSE", "NASDAQ"):
        df_col.append(tech.get_exhange_tickers(exch))

    df_tickers = pd.concat(df_col, axis=0).dropna(subset=["symbol"])
    if _TESTING_TICKER_CAP:
        df_tickers = df_tickers.head(_TESTING_TICKER_CAP)
        log.warning("[nis_short] TESTING cap active: %d tickers", _TESTING_TICKER_CAP)
    tickers = df_tickers["symbol"].to_list()
    log.info("[nis_short] universe: %d tickers", len(tickers))

    # ── Step 2: inverted quote + RS pre-screen ─────────────────────────────
    # Long side wants price>SMA200, SMA50>SMA200, within 25% of the high, RS>80.
    # We want the mirror: price<SMA200, SMA50<SMA200, ≥25% BELOW the high, RS weak.
    df_quote = tech.get_quote_prices(tickers).sort_values("symbol")
    df_rs = tech.get_change_prices(tickers)  # universe-wide RS percentile
    df_quote = df_quote.merge(df_rs, on="symbol", how="left")

    below_sma200 = df_quote["PRICE_OVER_SMA200"] == 0
    sma50_below_sma200 = df_quote["SMA50_OVER_SMA200"] == 0
    off_high = df_quote["price"] <= df_quote["yearHigh"] * (1 - _OFF_HIGH_MIN_PCT / 100.0)
    weak_rs = df_quote["RS"] < _RS_MAX

    pre_mask = below_sma200 & sma50_below_sma200 & off_high & weak_rs
    candidates = df_quote[pre_mask]["symbol"].dropna().tolist()

    # The trend-template dict carries RS_Rank but not the raw 0-100 RS, so keep a
    # symbol→RS map to inject the weak-RS value the short gate reads.
    rs_map = df_rs.set_index("symbol")["RS"].to_dict()
    log.info(
        "[nis_short] after pre-screen (px<SMA200 & SMA50<SMA200 & ≥%d%% off high & RS<%d): %d candidates",
        int(_OFF_HIGH_MIN_PCT),
        _RS_MAX,
        len(candidates),
    )

    # ── Step 3: per-ticker Stage-4 template + former-leader + fundamentals ──
    deep_screened = 0
    passed: list[dict] = []
    for i, symbol in enumerate(candidates, 1):
        if i % 25 == 0:
            log.info("[nis_short] screening %d/%d (%s)", i, len(candidates), symbol)
        try:
            df_data, tt, error = tech.get_screening(
                symbol,
                startdate=startdate.strftime(_DATE_FMT),
                enddate=today.strftime(_DATE_FMT),
            )
            if error or tt is None or df_data is None or len(df_data) < _SESSIONS_52W:
                continue

            # Inject universe-wide RS (0-100) so the weak-RS gate can read it.
            rs_val = rs_map.get(symbol)
            tt["RS"] = float(rs_val) if rs_val is not None and rs_val == rs_val else None

            short_tt = _short_flags(df_data, tt, pd)
            if short_tt is None:
                continue
            tt.update(short_tt)

            # Fundamentals: deceleration / disappointment, not absolute badness.
            tt.update(_short_fundamentals(fund, symbol))

            deep_screened += 1
            if _passed_short_gates(tt):
                try:
                    meta = df_tickers[df_tickers["symbol"] == symbol].iloc[0]
                    tt["sector"] = meta.get("sector", "N/A")
                    tt["subSector"] = meta.get("subSector", meta.get("industry", "N/A"))
                except Exception:
                    tt["sector"] = "N/A"
                    tt["subSector"] = "N/A"
                passed.append(tt)
        except Exception as exc:
            log.warning("[nis_short] %s failed: %s", symbol, exc)

    # ── Step 4: rank passers ───────────────────────────────────────────────
    # Weakest RS first (best short candidates), then furthest below the high.
    passed.sort(
        key=lambda r: (
            r.get("RS") if r.get("RS") is not None else 9999,
            -(r.get("pct_below_high") or 0),
        )
    )

    log.info(
        "[nis_short] passed full NIS Short: %d / %d deep-screened",
        len(passed),
        deep_screened,
    )

    base_data = {
        "market_regime": regime,
        "universe_size": len(tickers),
        "pre_screen_candidates": len(candidates),
        "screened": deep_screened,
        "passed": len(passed),
    }

    if not passed:
        return ScreeningResult(
            triggered=False,
            summary=None,
            ticker_count=0,
            data_used=base_data,
        )

    symbols_serialized = [_serialize_row(r) for r in passed]
    summary = _format_summary(passed, total_candidates=len(candidates))
    base_data["symbols"] = symbols_serialized
    return ScreeningResult(
        triggered=True,
        summary=summary,
        ticker_count=len(passed),
        data_used=base_data,
    )


# ──────────────────────────────────────────────────────────────────────────
# Stage-4 technical flags (computed directly from the daily chart)
# ──────────────────────────────────────────────────────────────────────────

def _short_flags(df, tt: dict, pd) -> dict | None:
    """Compute the inverted Stage-4 decline flags + former-leader/timing metrics.

    Returns None if the moving averages can't be resolved (too little history).
    """
    last = df.iloc[-1]
    close = float(last.get("close")) if pd.notna(last.get("close")) else None
    sma50 = last.get("SMA50")
    sma150 = last.get("SMA150")
    sma200 = last.get("SMA200")
    if close is None or not (pd.notna(sma50) and pd.notna(sma150) and pd.notna(sma200)):
        return None
    sma50, sma150, sma200 = float(sma50), float(sma150), float(sma200)

    # Stage-4 moving-average ladder (mirror of the long ladder)
    price_below_50_150_200 = bool(close < sma50 < sma150 < sma200)
    sma150_below_200 = bool(sma150 < sma200)
    sma50_below_150_200 = bool(sma50 < sma150 and sma50 < sma200)

    # SMA200 falling — inverse of the long SMA200Slope gate (≤2 up-days in 20
    # AND the 200-day is lower than it was ~1 month ago).
    sma200_falling = bool(
        len(df) >= 22
        and df["SMA200_slope_direction"].tail(20).sum() <= 2
        and sma200 < float(df["SMA200"].iloc[-21])
    )

    # 52-week position + stale high
    win = df.tail(_SESSIONS_52W)
    high_52w = float(win["high"].max())
    low_52w = float(win["low"].min())
    pct_below_high = (high_52w - close) / high_52w * 100 if high_52w > 0 else 0.0
    peak_pos = int(win["high"].values.argmax())
    peak_age_sessions = len(win) - 1 - peak_pos
    off_high = bool(pct_below_high >= _OFF_HIGH_MIN_PCT)
    high_is_stale = bool(peak_age_sessions >= _PEAK_STALE_MIN_SESSIONS)

    # Former leader — a 100%+ advance into the peak, measured trough-before-peak
    # → peak across the FULL lookback window (not just the last 52 weeks).
    full_peak_pos = int(df["high"].values.argmax())
    trough_before = float(df["low"].iloc[: full_peak_pos + 1].min()) if full_peak_pos > 0 else float(df["low"].iloc[0])
    peak_high = float(df["high"].iloc[full_peak_pos])
    prior_advance_pct = (peak_high - trough_before) / trough_before * 100 if trough_before > 0 else 0.0
    former_leader = bool(prior_advance_pct >= _PRIOR_ADVANCE_MIN_PCT)

    # RS weak (universe-wide percentile from get_change_prices)
    rs = tt.get("RS_Rank")
    rs_pct = None
    try:
        # tt only carries RS_Rank; pull the 0-100 RS off the row if present.
        rs_pct = float(tt.get("RS")) if tt.get("RS") is not None else None
    except Exception:
        rs_pct = None

    # Distribution volume — down-days heavier than up-days (inverse accumulation)
    ud_ratio = tt.get("up_down_vol_ratio")
    distribution = bool(ud_ratio is not None and ud_ratio <= _DISTRIBUTION_UD_MAX)

    # Rally-into-resistance timing aid: how far a bounce is from the (declining)
    # 50-day, which is now overhead resistance. Negative = already above it.
    dist_to_sma50_pct = (sma50 - close) / close * 100 if close > 0 else None

    # Liquidity floor
    avg_vol_50 = float(df["volume"].tail(50).mean()) if len(df) >= 50 else float(df["volume"].mean())
    avg_dollar_vol = avg_vol_50 * close
    liquid = bool(avg_dollar_vol >= _MIN_DOLLAR_VOL)

    return {
        # Stage-4 template
        "PriceBelowSMA50_150_200": price_below_50_150_200,
        "SMA150BelowSMA200": sma150_below_200,
        "SMA50BelowSMA150And200": sma50_below_150_200,
        "SMA200Falling": sma200_falling,
        "OffHigh25Pct": off_high,
        "HighIsStale": high_is_stale,
        "RSWeak": bool(rs_pct is not None and rs_pct < _RS_MAX),
        # Former leader / timing
        "FormerLeader": former_leader,
        "prior_advance_pct": round(prior_advance_pct, 1),
        "pct_below_high": round(pct_below_high, 1),
        "peak_age_sessions": peak_age_sessions,
        "dist_to_sma50_pct": round(dist_to_sma50_pct, 1) if dist_to_sma50_pct is not None else None,
        "week52_high": round(high_52w, 2),
        "week52_low": round(low_52w, 2),
        # Volume / liquidity
        "Distribution": distribution,
        "avg_dollar_vol": round(avg_dollar_vol, 0),
        "Liquid": liquid,
        "RS": rs_pct,
        "RS_Rank": rs,
    }


def _short_fundamentals(fund, symbol: str) -> dict:
    """Deceleration / disappointment flags — the short-side fundamental gate.

    We want a name that is still (or was recently) growing but is now SLOWING or
    disappointing after a big run — not a company that was always bad. Returns
    ``PASSED_FUNDAMENTALS_SHORT`` plus the component flags.
    """
    out = {
        "eps_decelerating": None,
        "eps_sma_declining": None,
        "recent_miss": None,
        "PASSED_FUNDAMENTALS_SHORT": False,
    }
    try:
        df_fund = fund.get_earnings_data(symbol)
        if df_fund is None or len(df_fund) < 5:
            return out
        latest = df_fund.iloc[-1]

        # EPS momentum rolling over: current-quarter YoY growth < prior quarter's.
        eps_decel = None
        if "eps_accelerating" in df_fund.columns:
            val = latest.get("eps_accelerating")
            eps_decel = (not bool(val)) if val is not None else None

        # EPS SMA turning down (the 4-quarter smoothed EPS is declining).
        eps_sma_declining = bool(latest.get("eps_sma_direction") == 0)

        # Most recent quarter missed consensus.
        recent_miss = bool(df_fund.tail(1)["beat_estimate"].sum() == 0)

        out["eps_decelerating"] = eps_decel
        out["eps_sma_declining"] = eps_sma_declining
        out["recent_miss"] = recent_miss

        # Gate: momentum not accelerating AND (SMA rolling down OR a fresh miss).
        out["PASSED_FUNDAMENTALS_SHORT"] = bool(
            (eps_decel is not False)  # not clearly accelerating
            and (eps_sma_declining or recent_miss)
        )
    except Exception as exc:
        log.warning("[nis_short] fundamentals for %s failed: %s", symbol, exc)
    return out


def _squeeze_ok(symbol: str) -> bool:  # noqa: ARG001 — hook, not yet wired
    """Squeeze filter placeholder — reject crowded shorts (high short interest /
    days-to-cover). Not enforced until FMP short-interest is wrapped in
    ``services.screener.fmp``; returns True (pass) so it never blocks today.
    """
    if _SQUEEZE_SI_MAX_PCT is None:
        return True
    return True


def _passed_short_gates(tt: dict) -> bool:
    """NIS Short gate — every technical + fundamental condition required."""
    return bool(
        tt.get("PriceBelowSMA50_150_200")
        and tt.get("SMA150BelowSMA200")
        and tt.get("SMA50BelowSMA150And200")
        and tt.get("SMA200Falling")
        and tt.get("OffHigh25Pct")
        and tt.get("HighIsStale")
        and tt.get("RSWeak")
        and tt.get("FormerLeader")
        and tt.get("Distribution")
        and tt.get("Liquid")
        and tt.get("PASSED_FUNDAMENTALS_SHORT")
    )


# ──────────────────────────────────────────────────────────────────────────
# Serialization + summary
# ──────────────────────────────────────────────────────────────────────────

def _serialize_row(r: dict) -> dict:
    """Project the per-ticker dict into a JSON-safe shape for the results table."""
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
        # Technical (Stage-4)
        "RS": _n("RS"),
        "RS_Rank": _n("RS_Rank"),
        "PriceBelowSMA50_150_200": _b("PriceBelowSMA50_150_200"),
        "SMA150BelowSMA200": _b("SMA150BelowSMA200"),
        "SMA50BelowSMA150And200": _b("SMA50BelowSMA150And200"),
        "SMA200Falling": _b("SMA200Falling"),
        "OffHigh25Pct": _b("OffHigh25Pct"),
        "HighIsStale": _b("HighIsStale"),
        "RSWeak": _b("RSWeak"),
        # Former leader / timing
        "FormerLeader": _b("FormerLeader"),
        "prior_advance_pct": _n("prior_advance_pct"),
        "pct_below_high": _n("pct_below_high"),
        "peak_age_sessions": _n("peak_age_sessions"),
        "dist_to_sma50_pct": _n("dist_to_sma50_pct"),
        "week52_high": _n("week52_high"),
        "week52_low": _n("week52_low"),
        # Supplementary technical (from get_screening)
        "adr_pct": _n("adr_pct"),
        "vol_ratio_today": _n("vol_ratio_today"),
        "up_down_vol_ratio": _n("up_down_vol_ratio"),
        "Distribution": _b("Distribution"),
        "avg_dollar_vol": _n("avg_dollar_vol"),
        "Liquid": _b("Liquid"),
        # Fundamentals (deceleration)
        "eps_decelerating": _b("eps_decelerating"),
        "eps_sma_declining": _b("eps_sma_declining"),
        "recent_miss": _b("recent_miss"),
        "PASSED_FUNDAMENTALS_SHORT": _b("PASSED_FUNDAMENTALS_SHORT"),
    }


def _format_summary(passed: list[dict], total_candidates: int) -> str:
    n = len(passed)
    head = (
        f"<b>NIS Short</b>\n"
        f"{n} short setup{'s' if n != 1 else ''} passed (from {total_candidates} candidates)\n"
    )
    shown = passed[:_SUMMARY_TOP_N]
    lines = []
    for r in shown:
        sym = r.get("ticker", "?")
        sector = r.get("sector") or "—"
        below = r.get("pct_below_high")
        below_part = f" · {below:.0f}% off high" if below is not None else ""
        lines.append(f"• <b>{sym}</b> — {sector}{below_part}")
    body = "\n".join(lines)
    tail = "" if n <= _SUMMARY_TOP_N else f"\n…and {n - _SUMMARY_TOP_N} more"
    return f"{head}\n{body}{tail}"
