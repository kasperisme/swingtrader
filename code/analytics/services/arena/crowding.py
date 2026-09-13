"""
Squeeze screen for new short positions — the arena's stand-in for the three
numbers a short seller checks before anything else: short interest, borrow
cost, and how much of the float sits with retail.

NONE of those three is available here. FMP's catalogue has no short-interest or
borrow feed, no tool in this repo carries one, and the broker charges no borrow
fee. So this module screens on the proxies the platform CAN measure, and says
so in every result rather than letting a proxy pass for the real thing:

  * **float value** (FMP ``shares-float`` x the session close) — squeezes live in
    small floats;
  * **free float** — a float mostly held by insiders is a tight float whatever
    its size;
  * **liquidity** — 20-session average dollar volume, i.e. whether a short can
    be covered without moving the price;
  * **run-up** — a 20-session rally already in progress is the squeeze, not the
    setup;
  * **retail crowding** — news attention accelerating against the ticker's own
    baseline WITH bullish sentiment (the platform's own attention board). This
    is the only one of the five that reads the crowd, and it is the exact
    configuration — loud, adored, rising — that the Tesla short lost on.

Any single failure DISQUALIFIES, regardless of how good the thesis is, and the
screen FAILS CLOSED: a number it cannot fetch is a reason to refuse, not a pass.
The same function backs the agent's ``get_short_crowding`` tool and the
broker's short gate, so what the agent is shown is exactly what the broker will
enforce.

Point-in-time: prices, volume and attention are bounded to the session; the
float is FMP's current figure (it has no history), which is residual look-ahead
in a replay and listed in ``tools.UNBOUNDED_IN_REPLAY``.
"""

from __future__ import annotations

import logging
import os
from datetime import date, timedelta
from typing import Any, Optional

import requests

from .marks import PriceBook

log = logging.getLogger(__name__)

# ── Thresholds. Each one disqualifies on its own. ───────────────────────────
#: Float value below this is small enough for a squeeze to be cheap to run.
MIN_FLOAT_VALUE_USD = 1_000_000_000
#: A free float below this share of outstanding is tight regardless of size.
MIN_FREE_FLOAT_PCT = 50.0
#: 20-session average dollar volume. Below it, covering moves the price.
MIN_AVG_DOLLAR_VOLUME_USD = 25_000_000
#: A 20-session rally above this is a squeeze in progress, not a setup.
MAX_RUNUP_20D_PCT = 25.0
#: Retail crowding: coverage accelerating at least this much against its own
#: baseline, with at least MIN_CROWD_MENTIONS recent articles …
MAX_ATTENTION_ACCELERATION = 3.0
MIN_CROWD_MENTIONS = 10
#: … AND average weighted sentiment above this. Accelerating coverage that is
#: NEGATIVE (an investigation, a downgrade) is not a crowd on the long side.
CROWD_BULLISH_SENTIMENT = 0.15

_RUNUP_SESSIONS = 20
_ATTENTION_DAYS, _ATTENTION_PRIOR_DAYS = 5, 15

NOT_MEASURED = (
    "Short interest, borrow cost and retail share of the float are NOT available "
    "on this platform; these are proxies for them, not measurements."
)


def _fmp_key() -> Optional[str]:
    return os.environ.get("APIKEY") or os.environ.get("FMP_API_KEY")


def fetch_float(ticker: str) -> Optional[dict[str, float]]:
    """FMP ``/stable/shares-float`` for one ticker, or None if unavailable."""
    key = _fmp_key()
    if not key:
        return None
    try:
        r = requests.get(
            "https://financialmodelingprep.com/stable/shares-float",
            params={"symbol": ticker, "apikey": key},
            timeout=20,
        )
        rows = r.json() if r.status_code == 200 else []
    except Exception as exc:  # network / plan — absent, and the screen fails closed
        log.warning("arena/crowding: shares-float failed for %s: %s", ticker, exc)
        return None
    if not rows or not isinstance(rows, list):
        return None
    row = rows[0]
    try:
        return {
            "float_shares": float(row["floatShares"]),
            "free_float_pct": float(row["freeFloat"]),
        }
    except (KeyError, TypeError, ValueError):
        return None


def fetch_attention(ticker: str, as_of: date) -> Optional[dict[str, float]]:
    """One ticker's attention acceleration + sentiment, same arithmetic as the
    ``get_trending_tickers`` board, bounded to ``as_of``."""
    window_start = as_of - timedelta(days=_ATTENTION_DAYS)
    prior_start = window_start - timedelta(days=_ATTENTION_PRIOR_DAYS)
    sql = """
        SELECT
            COALESCE(SUM(mention_count) FILTER (WHERE bucket_day >= %(window_start)s), 0)::int,
            COALESCE(SUM(mention_count) FILTER (WHERE bucket_day <  %(window_start)s), 0)::int,
            AVG(weighted_sentiment)     FILTER (WHERE bucket_day >= %(window_start)s)
        FROM swingtrader.news_trends_ticker_daily_v
        WHERE ticker = %(ticker)s
          AND bucket_day >= %(prior_start)s
          AND bucket_day <= %(today)s
    """
    from shared.db import get_pg_connection

    try:
        conn = get_pg_connection()
        try:
            with conn, conn.cursor() as cur:
                cur.execute(sql, {"ticker": ticker, "window_start": window_start,
                                  "prior_start": prior_start, "today": as_of})
                recent, prior, sentiment = cur.fetchone()
        finally:
            conn.close()
    except Exception as exc:
        log.warning("arena/crowding: attention query failed for %s: %s", ticker, exc)
        return None
    recent_daily = recent / _ATTENTION_DAYS
    prior_daily = prior / _ATTENTION_PRIOR_DAYS
    return {
        "mentions_recent": recent,
        "acceleration": round(recent_daily / (prior_daily + 0.25), 2),
        "sentiment": round(float(sentiment), 3) if sentiment is not None else None,
    }


def price_stats(ticker: str, as_of: date, prices: PriceBook) -> Optional[dict[str, float]]:
    """Session close, 20-session return and average dollar volume, from bars
    that existed on ``as_of`` (the same PriceBook the broker fills against)."""
    prices.load([ticker], as_of - timedelta(days=45), as_of)
    bars = prices._bars.get(ticker, {})  # noqa: SLF001 — same package
    days = sorted(d for d in bars if d <= as_of.isoformat())[-(_RUNUP_SESSIONS + 1):]
    if len(days) < _RUNUP_SESSIONS // 2:
        return None
    closes = [bars[d]["close"] for d in days]
    dollar_vol = [
        bars[d]["close"] * bars[d]["volume"]
        for d in days[1:]
        if bars[d].get("volume") is not None
    ]
    if not dollar_vol:
        return None
    return {
        "close": closes[-1],
        "runup_20d_pct": round((closes[-1] / closes[0] - 1) * 100, 1),
        "avg_dollar_volume": round(sum(dollar_vol) / len(dollar_vol), 0),
    }


def evaluate(
    *,
    float_data: Optional[dict[str, float]],
    attention: Optional[dict[str, float]],
    stats: Optional[dict[str, float]],
) -> list[str]:
    """Every reason to refuse the short. Empty list = the screen passes.

    Pure: no I/O, so the thresholds are tested without FMP or the database.
    """
    reasons: list[str] = []

    if stats is None:
        reasons.append("no recent price/volume history to measure run-up and liquidity")
    else:
        if stats["runup_20d_pct"] > MAX_RUNUP_20D_PCT:
            reasons.append(
                f"up {stats['runup_20d_pct']:.0f}% in 20 sessions (limit "
                f"+{MAX_RUNUP_20D_PCT:.0f}%) — a squeeze in progress, not a setup"
            )
        if stats["avg_dollar_volume"] < MIN_AVG_DOLLAR_VOLUME_USD:
            reasons.append(
                f"average dollar volume ${stats['avg_dollar_volume'] / 1e6:,.1f}M "
                f"(minimum ${MIN_AVG_DOLLAR_VOLUME_USD / 1e6:,.0f}M) — too thin to cover"
            )

    if float_data is None:
        reasons.append("float could not be verified (FMP shares-float unavailable)")
    else:
        if float_data["free_float_pct"] < MIN_FREE_FLOAT_PCT:
            reasons.append(
                f"free float {float_data['free_float_pct']:.0f}% of shares "
                f"(minimum {MIN_FREE_FLOAT_PCT:.0f}%) — a tight float"
            )
        if stats is not None:
            float_value = float_data["float_shares"] * stats["close"]
            if float_value < MIN_FLOAT_VALUE_USD:
                reasons.append(
                    f"float worth ${float_value / 1e9:,.2f}B (minimum "
                    f"${MIN_FLOAT_VALUE_USD / 1e9:,.0f}B) — small enough to squeeze"
                )

    if attention is None:
        reasons.append("attention could not be measured (news trend query failed)")
    elif (
        attention["acceleration"] >= MAX_ATTENTION_ACCELERATION
        and attention["mentions_recent"] >= MIN_CROWD_MENTIONS
        and (attention["sentiment"] or 0) > CROWD_BULLISH_SENTIMENT
    ):
        reasons.append(
            f"retail crowding: coverage x{attention['acceleration']:.1f} its baseline "
            f"({attention['mentions_recent']} articles, sentiment "
            f"{attention['sentiment']:+.2f}) — accelerating enthusiasm is peak squeeze risk"
        )
    return reasons


def screen(ticker: str, as_of: date, prices: PriceBook) -> dict[str, Any]:
    """The full screen for one ticker on one session."""
    sym = (ticker or "").upper().strip()
    float_data = fetch_float(sym)
    attention = fetch_attention(sym, as_of)
    stats = price_stats(sym, as_of, prices)
    reasons = evaluate(float_data=float_data, attention=attention, stats=stats)
    return {
        "ticker": sym,
        "as_of": as_of.isoformat(),
        "disqualified": bool(reasons),
        "reasons": reasons,
        "float": float_data,
        "attention": attention,
        "price": stats,
        "thresholds": {
            "min_float_value_usd": MIN_FLOAT_VALUE_USD,
            "min_free_float_pct": MIN_FREE_FLOAT_PCT,
            "min_avg_dollar_volume_usd": MIN_AVG_DOLLAR_VOLUME_USD,
            "max_runup_20d_pct": MAX_RUNUP_20D_PCT,
            "crowding": (
                f"acceleration >= {MAX_ATTENTION_ACCELERATION} with >= "
                f"{MIN_CROWD_MENTIONS} articles and sentiment > {CROWD_BULLISH_SENTIMENT}"
            ),
        },
        "not_measured": NOT_MEASURED,
    }


SHORT_CROWDING_SCHEMA: dict = {
    "type": "function",
    "function": {
        "name": "get_short_crowding",
        "description": (
            "The squeeze screen the broker applies to every NEW or ENLARGED short. "
            "Checks float value, free float, 20-session liquidity, 20-session "
            "run-up and retail crowding (accelerating, bullish coverage). If it "
            "returns disqualified=true, the broker WILL reject the short — the "
            "thesis does not matter. Run it before researching a name deeply. "
            "Short interest and borrow cost are not available anywhere here; "
            "these are proxies."
        ),
        "parameters": {
            "type": "object",
            "properties": {"ticker": {"type": "string", "description": "US equity symbol"}},
            "required": ["ticker"],
        },
    },
}
