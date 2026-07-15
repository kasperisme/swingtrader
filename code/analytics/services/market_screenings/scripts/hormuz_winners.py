"""Hormuz Winners — a curated basket of the names positioned to BENEFIT
from an Iran / Strait-of-Hormuz supply-shock, each validated by two independent
signals so the board isn't just a thesis on paper:

  • Momentum — the shared trend template (50/150/200 SMA alignment + slope,
    proximity to 52-week extremes, relative strength) via services.screener.technical.
    Answers "is the market actually rewarding this name right now?"
  • News exposure — mentions + mean sentiment for each ticker across the last two
    weeks of crisis-tagged articles (iran/oil/geopolitics/shipping/defense/…) from
    ticker_sentiment_heads_v. Answers "is it genuinely in THIS story?"

Unlike a raw news scrape (which is dominated by mega-caps that merely get mentioned),
this runs over a FIXED, hand-curated beneficiary universe grouped by *why* each name
benefits — oil & gas, oil services, defense & aerospace, tankers & shipping, uranium /
energy security, safe-haven, and ETF proxies. It emits EVERY name it can screen, ranked
by relative-strength rank, flagging who is confirmed in an uptrend + in the news.

Runtime: one FMP screening per name (~40) → a couple of minutes.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta

from services.screener import technical

from ..types import ScreeningResult

log = logging.getLogger(__name__)

_LOOKBACK_DAYS = 365
_DATE_FMT = "%Y-%m-%d"
_SUMMARY_TOP_N = 25
_SCHEMA = "swingtrader"

# ── Curated beneficiary universe ─────────────────────────────────────────────
# symbol → thesis bucket (shown as `subSector`/`group` in the gallery table).
_UNIVERSE: dict[str, str] = {
    # Oil & gas E&P — higher crude on a supply shock
    "XOM": "Oil & gas", "CVX": "Oil & gas", "COP": "Oil & gas", "OXY": "Oil & gas",
    "EOG": "Oil & gas", "DVN": "Oil & gas", "FANG": "Oil & gas", "HES": "Oil & gas",
    "CTRA": "Oil & gas",
    # Oil services — drilling & activity ramp
    "SLB": "Oil services", "HAL": "Oil services", "BKR": "Oil services",
    "NOV": "Oil services", "FTI": "Oil services",
    # Defense & aerospace — conflict lifts defense spend
    "LMT": "Defense & aerospace", "RTX": "Defense & aerospace", "NOC": "Defense & aerospace",
    "GD": "Defense & aerospace", "LHX": "Defense & aerospace", "HII": "Defense & aerospace",
    "TDG": "Defense & aerospace", "KTOS": "Defense & aerospace", "AVAV": "Defense & aerospace",
    # Tankers & shipping — Hormuz disruption spikes tanker rates
    "FRO": "Tankers & shipping", "STNG": "Tankers & shipping", "INSW": "Tankers & shipping",
    "DHT": "Tankers & shipping", "TNK": "Tankers & shipping", "ASC": "Tankers & shipping",
    "NAT": "Tankers & shipping",
    # Uranium / energy security — energy-independence bid
    "CCJ": "Uranium & energy security", "LEU": "Uranium & energy security",
    "UEC": "Uranium & energy security",
    # Safe haven — geopolitical-risk hedge
    "NEM": "Safe haven", "AEM": "Safe haven", "GLD": "Safe haven",
    # ETF proxies — the clean thematic expression
    "XLE": "ETF proxy", "OIH": "ETF proxy", "ITA": "ETF proxy",
}

# bucket → one-line "why it benefits" thesis, surfaced per row for the board + ad.
_THESIS: dict[str, str] = {
    "Oil & gas": "Crude spikes on a Hormuz supply shock — producers' cash flow re-rates.",
    "Oil services": "Higher prices pull forward drilling and completion activity.",
    "Defense & aerospace": "Active conflict lifts defense budgets and munitions demand.",
    "Tankers & shipping": "Hormuz disruption spikes tanker rates and reroutes flows.",
    "Uranium & energy security": "Energy-independence bid on supply insecurity.",
    "Safe haven": "Geopolitical risk drives a flight to gold.",
    "ETF proxy": "Clean thematic exposure to the energy / defense complex.",
}

# tags that define "this story" for the news-exposure overlay
_CRISIS_TAGS = ["iran", "oil", "geopolitics", "middle east", "shipping", "defense",
                "energy", "tankers", "aerospace", "opec", "crude", "uranium", "natural gas"]


def _passed_momentum(tt: dict) -> bool:
    return bool(tt.get("Passed")) and bool(tt.get("PriceOverSMA50"))


def _news_exposure(client) -> dict[str, tuple[int, float]]:
    """{ticker: (mentions, mean_sentiment)} across the last 14 days of crisis-tagged
    articles. Best-effort — an empty map just drops the overlay, never the screen."""
    try:
        res = client.schema(_SCHEMA).rpc("search_news_by_tags", {
            "tag_filter": _CRISIS_TAGS, "match_count": 500,
            "lookback_hours": 336, "stream_filter": None,
        }).execute()
        ids = [a["article_id"] for a in (res.data or []) if a.get("article_id") is not None]
    except Exception as exc:  # noqa: BLE001
        log.warning("[hormuz_winners] news RPC failed: %s", exc)
        return {}
    ssum: dict[str, float] = defaultdict(float)
    scnt: dict[str, int] = defaultdict(int)
    for i in range(0, len(ids), 300):
        try:
            rows = (client.schema(_SCHEMA).table("ticker_sentiment_heads_v")
                    .select("ticker,sentiment_score").in_("article_id", ids[i:i + 300])
                    .execute().data or [])
        except Exception as exc:  # noqa: BLE001
            log.warning("[hormuz_winners] sentiment pull failed: %s", exc)
            continue
        for r in rows:
            t = str(r.get("ticker") or "").upper().strip()
            s = r.get("sentiment_score")
            if t and s is not None:
                ssum[t] += float(s)
                scnt[t] += 1
    return {t: (scnt[t], ssum[t] / scnt[t]) for t in scnt}


def run(client, screening: dict) -> ScreeningResult:  # noqa: ARG001
    tech = technical.technical()
    today = datetime.today()
    startdate = today - timedelta(days=_LOOKBACK_DAYS)
    tickers = list(_UNIVERSE.keys())
    log.info("[hormuz_winners] universe: %d curated names", len(tickers))

    news = _news_exposure(client)
    log.info("[hormuz_winners] news overlay: %d names with crisis mentions", len(news))

    # RS is ranked WITHIN the basket — pre-compute over the full list.
    try:
        tech.get_quote_prices(tickers)
        tech.get_change_prices(tickers)
    except Exception as exc:  # noqa: BLE001
        log.warning("[hormuz_winners] RS pre-compute failed: %s", exc)

    rows: list[dict] = []
    screened = 0
    for i, symbol in enumerate(tickers, 1):
        if i % 10 == 0:
            log.info("[hormuz_winners] screening %d/%d (%s)", i, len(tickers), symbol)
        try:
            _df, tt, error = tech.get_screening(
                symbol, startdate=startdate.strftime(_DATE_FMT), enddate=today.strftime(_DATE_FMT))
            if error or tt is None:
                log.info("[hormuz_winners] %s: no technical data (%s)", symbol, error)
                continue
            bucket = _UNIVERSE.get(symbol, "Iran crisis")
            mentions, sentiment = news.get(symbol, (0, None))
            tt["group"] = bucket
            tt["thesis"] = _THESIS.get(bucket, "")
            tt["news_mentions"] = int(mentions)
            tt["news_sentiment"] = sentiment
            tt["in_news"] = bool(mentions)
            tt["passed_momentum"] = _passed_momentum(tt)
            # "benefiting now" = confirmed in a momentum uptrend (price is rewarding it)
            tt["benefiting"] = bool(tt["passed_momentum"])
            screened += 1
            rows.append(tt)
        except Exception as exc:  # noqa: BLE001
            log.warning("[hormuz_winners] %s failed: %s", symbol, exc)

    if not rows:
        return ScreeningResult(
            triggered=False,
            summary="No Hormuz Winners could be screened this run.",
            ticker_count=0,
            data_used={"universe_size": len(tickers), "screened": 0, "benefiting": 0},
            error="empty_result")

    # strongest first by relative-strength rank within the basket (lower = stronger);
    # names missing a rank sink to the bottom. `benefiting` stays a per-row flag/column.
    rows.sort(key=lambda r: (r.get("RS_Rank") is None, r.get("RS_Rank") or 9999))
    benefiting = sum(1 for r in rows if r.get("benefiting"))
    in_news = sum(1 for r in rows if r.get("in_news"))
    log.info("[hormuz_winners] screened %d/%d — %d benefiting, %d in the news",
             screened, len(tickers), benefiting, in_news)

    data_used = {
        "universe_size": len(tickers), "screened": screened,
        "benefiting": benefiting, "in_news": in_news,
        "symbols": [_serialize_row(r) for r in rows],
    }
    return ScreeningResult(
        triggered=benefiting > 0,
        summary=_format_summary(rows, benefiting=benefiting, in_news=in_news),
        ticker_count=len(rows),
        data_used=data_used)


def _serialize_row(r: dict) -> dict:
    def _b(k: str) -> bool:
        return bool(r.get(k))

    def _n(k: str):
        v = r.get(k)
        if v is None:
            return None
        try:
            f = float(v)
            return f if f == f else None
        except Exception:  # noqa: BLE001
            return None

    return {
        "symbol": r.get("ticker"),
        "sector": "Energy / Defense",
        "subSector": r.get("group"),
        "group": r.get("group"),
        "thesis": r.get("thesis"),
        # who's benefiting now
        "benefiting": _b("benefiting"),
        "passed_momentum": _b("passed_momentum"),
        # news exposure (is it in THIS story)
        "in_news": _b("in_news"),
        "news_mentions": r.get("news_mentions") or 0,
        "news_sentiment": _n("news_sentiment"),
        # technical / momentum
        "RS_Rank": _n("RS_Rank"),
        "Passed": _b("Passed"),
        "PriceOverSMA50": _b("PriceOverSMA50"),
        "PriceOverSMA150And200": _b("PriceOverSMA150And200"),
        "SMA50AboveSMA150And200": _b("SMA50AboveSMA150And200"),
        "SMA200Slope": _b("SMA200Slope"),
        "PriceWithin25Percent52WeekHigh": _b("PriceWithin25Percent52WeekHigh"),
        "RSOver70": _b("RSOver70"),
        "adr_pct": _n("adr_pct"),
        "vol_ratio_today": _n("vol_ratio_today"),
        "within_buy_range": _b("within_buy_range"),
        "extended": _b("extended"),
    }


def _format_summary(rows: list[dict], benefiting: int, in_news: int) -> str:
    n = len(rows)
    head = (
        f"<b>Hormuz Winners</b>\n"
        f"{n} name{'s' if n != 1 else ''} tracked · {benefiting} in a momentum "
        f"uptrend · {in_news} in the crisis news\n"
    )
    lines = []
    for r in rows[:_SUMMARY_TOP_N]:
        sym = r.get("ticker", "?")
        group = r.get("group") or "—"
        rs = r.get("RS_Rank")
        rs_part = f" · RS {rs}" if rs is not None else ""
        flag = " ✅" if r.get("benefiting") else ""
        news = " 📰" if r.get("in_news") else ""
        lines.append(f"• <b>{sym}</b> — {group}{rs_part}{flag}{news}")
    tail = "" if n <= _SUMMARY_TOP_N else f"\n…and {n - _SUMMARY_TOP_N} more"
    return f"{head}\n" + "\n".join(lines) + tail
