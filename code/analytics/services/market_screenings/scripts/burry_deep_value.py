"""Burry Deep Value — cheap, hated and unwatched, on both sides of the book.

Michael Burry's documented method is a value screen with two halves, and only
one of them is a commodity. The commodity half is EV/EBITDA, free cash flow and
low debt — his own description of the process starts at EV/EBITDA and he is
explicit that the acceptable multiple is INDUSTRY-relative ("a technology
company might justifiably trade at 15-20x… a utility only 6-8x"), that he uses
enterprise value rather than market cap because it carries the debt, and that
free cash flow is preferred because it is "purer and harder to manipulate".

The other half is the part no conventional screener can run, and it is why this
board exists here rather than in a stock screener: Burry looked for **"ick"
stocks** — names that provoke a first reaction of revulsion — and for the
**neglected**, "unpopular companies that look like road kill". Those are not
fundamental facts. They are facts about ATTENTION and SENTIMENT, and this
platform measures both per ticker per day in ``ticker_coverage_daily``.

Measured over a 90-day window across 3,885 covered tickers:

    mentions    p10=3      median=6      p90=33
    sentiment   p10=-0.28  median=+0.41  p90=+0.80

Sentiment skews strongly positive, so a negative reading is genuinely rare —
which makes "ick" a discriminating gate rather than a mood. That asymmetry is
the whole edge of this screen.

Pipeline, ordered CHEAP GATES FIRST because the fundamental step costs one FMP
call per surviving ticker:

  1. Attention gates (SQL, one query). Ick: 90-day average sentiment below
     zero. Neglect: mention count inside a band — enough coverage to be real,
     little enough to be ignored. Cuts thousands to dozens.
  2. Liquidity + tradeability (one FMP screener call). Enough price and volume
     to take and exit a position; also supplies each name's sector.
  3. Value gates (one FMP key-metrics call per survivor):
       • EV/EBITDA under a SECTOR-relative ceiling
       • free cash flow yield positive and meaningful
       • net debt / EBITDA under a ceiling
  4. Rare-bird flag (not a gate): working capital per share above the price —
     Burry's "selling at less than two-thirds of net value". Rare; flagged when
     found because those "deserve longer holding periods".
  5. Margin of safety (bonus where available): the priced-in programme's
     reverse-DCF. ``median_gap`` says where the price sits against published
     analyst models and ``implied_revenue_cagr`` says what growth the price
     REQUIRES — a number no screener has. Only ~476 names carry it, so it
     annotates rather than gates; requiring it would cap the board at the
     large-cap end and exclude exactly the neglected names the screen is for.

THE SHORT SIDE is the same pipeline with every comparator flipped, and it is
deliberately NOT the ``nis-short`` method. That board is Minervini/O'Neil —
former leaders in a Stage-4 breakdown, entered 5-15 weeks after the top. This
one shorts what is expensive, adored and crowded while it is still going up,
because that is what Burry did and being early is the cost of the trade. Rows
carry ``side`` so one run answers both questions.

NO MARKET-REGIME GATE, unlike nis_short. Gating on the S&P's 200-day is O'Neil's
timing discipline; Burry is early on purpose and holds through the drawdown.

Known gap: short interest / days-to-cover is not in the schema and not among the
FMP tools wired here, so squeeze risk on the short side is unscreened — the same
hole ``nis_short`` documents. ``_SQUEEZE_SI_MAX_PCT`` is the hook.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from shared.db import get_pg_connection

from ..types import ScreeningResult

log = logging.getLogger(__name__)

_SUMMARY_TOP_N = 20
_TESTING_TICKER_CAP = 0        # 0 = no cap; set small while iterating
_SQUEEZE_SI_MAX_PCT: Optional[float] = None   # hook: reject crowded shorts once wired

# ── Attention window ────────────────────────────────────────────────────────
_COVERAGE_DAYS = 90
#: Below this a ticker is not neglected, it is simply absent — no coverage means
#: no sentiment reading worth trusting, not a contrarian opportunity.
_MIN_MENTIONS = 3
#: The neglect ceiling. p90 of the covered universe is 33, so this keeps roughly
#: the bottom four-fifths by attention and drops the names everyone watches.
_MAX_MENTIONS_LONG = 40
#: The short side wants the opposite: crowded, loudly covered names.
_MIN_MENTIONS_SHORT = 33
_ICK_SENTIMENT_MAX = 0.0       # long: the market dislikes it
_ADORED_SENTIMENT_MIN = 0.60   # short: the market loves it

# ── Value gates ─────────────────────────────────────────────────────────────
#: Burry's ceiling is industry-relative by his own account, so a single number
#: would either exclude every technology name or admit every utility. These are
#: the bands his description implies, applied to FMP's sector labels.
_SECTOR_EV_EBITDA_MAX: dict[str, float] = {
    "Technology": 18.0,
    "Communication Services": 14.0,
    "Healthcare": 14.0,
    "Consumer Cyclical": 12.0,
    "Industrials": 12.0,
    "Basic Materials": 10.0,
    "Consumer Defensive": 12.0,
    "Financial Services": 12.0,
    "Real Estate": 16.0,
    "Energy": 8.0,
    "Utilities": 10.0,
}
_SECTOR_EV_EBITDA_DEFAULT = 12.0
#: Free cash flow is the measure Burry trusts; a negative one disqualifies
#: regardless of how cheap the multiple looks.
_MIN_FCF_YIELD = 0.04
#: "Minimal debt." Not zero — a levered but cash-generative business is still
#: investable — but enough leverage to make the equity a call option is not.
_MAX_NET_DEBT_TO_EBITDA = 3.5
#: Short side: rich on the multiple AND not generating the cash to justify it.
_SHORT_EV_EBITDA_MIN_MULT = 1.5   # x the sector ceiling
_SHORT_MAX_FCF_YIELD = 0.02

_LIQ_PRICE_MIN = 5.0
_LIQ_VOLUME_MIN = 300_000


# ── Step 1: the attention gates, in one query ───────────────────────────────

def _attention_candidates() -> tuple[list[dict], list[dict], int]:
    """(ick+neglected, adored+crowded, universe size) from ticker_coverage_daily.

    One query for both sides. Runs first because it is the only step that costs
    nothing per ticker and it removes ~97% of the universe.
    """
    sql = """
    with w as (
      select ticker,
             sum(mention_count)  as mentions,
             sum(scored_count)   as scored,
             avg(avg_sentiment)  as sentiment
      from swingtrader.ticker_coverage_daily
      where bucket_day >= current_date - %(days)s
      group by ticker
      having sum(mention_count) >= %(min_mentions)s
    )
    select ticker, mentions, scored, sentiment,
           case
             when sentiment < %(ick)s  and mentions <= %(max_long)s  then 'long'
             when sentiment > %(adored)s and mentions >= %(min_short)s then 'short'
           end as side,
           count(*) over () as universe
    from w
    order by sentiment
    """
    args = {
        "days": _COVERAGE_DAYS, "min_mentions": _MIN_MENTIONS,
        "ick": _ICK_SENTIMENT_MAX, "max_long": _MAX_MENTIONS_LONG,
        "adored": _ADORED_SENTIMENT_MIN, "min_short": _MIN_MENTIONS_SHORT,
    }
    with get_pg_connection() as conn, conn.cursor() as cur:
        cur.execute(sql, args)
        rows = cur.fetchall()

    # index 5, not 4 — `side` sits between sentiment and the window count.
    universe = int(rows[0][5]) if rows else 0
    longs, shorts = [], []
    for ticker, mentions, scored, sentiment, side, _u in rows:
        rec = {
            "symbol": ticker,
            "mentions_90d": int(mentions or 0),
            "scored_90d": int(scored or 0),
            "sentiment_90d": round(float(sentiment), 4) if sentiment is not None else None,
        }
        if side == "long":
            longs.append(rec)
        elif side == "short":
            shorts.append(rec)
    return longs, shorts, universe


# ── Step 5: the platform's own margin-of-safety read ────────────────────────

def _priced_in(tickers: list[str]) -> dict[str, dict]:
    """`median_gap` and the reverse-DCF's required growth, where published.

    Annotation, never a gate: only ~476 names carry a published reconstruction
    and they skew large, which is the opposite end of the market from the one
    this screen is looking at.
    """
    if not tickers:
        return {}
    sql = """
    select distinct on (ticker)
           ticker, median_gap, implied_revenue_cagr, target_median, n_targets
    from swingtrader.research_priced_in
    where published and ticker = any(%(t)s)
    order by ticker, as_of desc, created_at desc
    """
    try:
        with get_pg_connection() as conn, conn.cursor() as cur:
            cur.execute(sql, {"t": tickers})
            return {
                r[0]: {
                    "median_gap": _f(r[1]),
                    "implied_revenue_cagr": _f(r[2]),
                    "analyst_target_median": _f(r[3]),
                    "n_targets": int(r[4]) if r[4] is not None else None,
                }
                for r in cur.fetchall()
            }
    except Exception as exc:                                   # noqa: BLE001
        log.warning("burry: priced-in annotation unavailable (%s)", exc)
        return {}


def _f(v: Any) -> Optional[float]:
    try:
        f = float(v)
        return f if f == f else None                           # NaN check
    except (TypeError, ValueError):
        return None


# ── Step 3/4: the value gates, per surviving ticker ─────────────────────────

def _value_read(fmp_client, symbol: str) -> Optional[dict]:
    """EV/EBITDA, FCF yield, leverage and working capital for one name."""
    try:
        km = fmp_client.key_metrics_quarterly(symbol, limit=1)
    except Exception as exc:                                   # noqa: BLE001
        log.debug("burry: key metrics failed for %s: %s", symbol, exc)
        return None
    if km is None or km.empty:
        return None
    r = km.iloc[-1]
    return {
        "ev_to_ebitda": _f(r.get("evToEBITDA")),
        "ev_to_fcf": _f(r.get("evToFreeCashFlow")),
        "fcf_yield": _f(r.get("freeCashFlowYield")),
        "net_debt_to_ebitda": _f(r.get("netDebtToEBITDA")),
        "earnings_yield": _f(r.get("earningsYield")),
        "working_capital": _f(r.get("workingCapital")),
        "enterprise_value": _f(r.get("enterpriseValue")),
    }


def _passes_long(v: dict, sector: str) -> bool:
    ceiling = _SECTOR_EV_EBITDA_MAX.get(sector, _SECTOR_EV_EBITDA_DEFAULT)
    ev = v.get("ev_to_ebitda")
    fcf = v.get("fcf_yield")
    lev = v.get("net_debt_to_ebitda")
    # A NEGATIVE EV/EBITDA is not cheap, it is an EBITDA loss wearing a small
    # number. Require a positive multiple under the ceiling.
    if ev is None or ev <= 0 or ev > ceiling:
        return False
    if fcf is None or fcf < _MIN_FCF_YIELD:
        return False
    if lev is not None and lev > _MAX_NET_DEBT_TO_EBITDA:
        return False
    return True


def _passes_short(v: dict, sector: str) -> bool:
    ceiling = _SECTOR_EV_EBITDA_MAX.get(sector, _SECTOR_EV_EBITDA_DEFAULT)
    ev = v.get("ev_to_ebitda")
    fcf = v.get("fcf_yield")
    if ev is None or ev < ceiling * _SHORT_EV_EBITDA_MIN_MULT:
        return False
    # Rich AND not generating the cash to justify it. A rich multiple on strong
    # free cash flow is a good business, not a short.
    if fcf is None or fcf > _SHORT_MAX_FCF_YIELD:
        return False
    return True


def _rare_bird(v: dict, price: Optional[float], shares: Optional[float]) -> bool:
    """Burry's "less than two-thirds of net value" — a net-net, roughly.

    Working capital per share against the price. FMP's ``workingCapital`` is
    current assets less current liabilities, so this is the generous form of the
    test (it does not subtract long-term liabilities); it is a FLAG, never a
    gate, and the label says which test it passed.
    """
    wc = v.get("working_capital")
    if not (wc and price and shares) or shares <= 0:
        return False
    return (wc / shares) > (price / (2 / 3))


# ── The run ─────────────────────────────────────────────────────────────────

def run(client, screening: dict) -> ScreeningResult:  # noqa: ARG001
    from services.screener.fmp import fmp as FMP

    fmp_client = FMP()

    # 1. Attention. The only free step, so it goes first and does the most work.
    try:
        longs, shorts, universe = _attention_candidates()
    except Exception as exc:                                   # noqa: BLE001
        log.exception("burry: attention query failed")
        return ScreeningResult(triggered=False, error=f"coverage query failed: {exc}")

    log.info("burry: attention gates -> %d long / %d short candidates from %d covered",
             len(longs), len(shorts), universe)
    if not longs and not shorts:
        return ScreeningResult(
            triggered=False, ticker_count=0,
            summary="No names passed the attention gates — nothing cheap-and-hated "
                    "or rich-and-adored in the covered universe today.",
            data_used={"universe_covered": universe, "symbols": []},
        )

    # 2. Liquidity, and the sector label the value ceiling needs.
    try:
        screen = fmp_client.stock_screener(
            price_min=_LIQ_PRICE_MIN, volume_min=_LIQ_VOLUME_MIN
        )
        liquid = {
            str(r["symbol"]): {
                "sector": r.get("sector") or "",
                "industry": r.get("industry") or "",
                "price": _f(r.get("price")),
                "market_cap": _f(r.get("marketCap")),
                "volume": _f(r.get("volume")),
            }
            for _, r in screen.iterrows()
        }
    except Exception as exc:                                   # noqa: BLE001
        log.exception("burry: FMP screener failed")
        return ScreeningResult(triggered=False, error=f"FMP screener failed: {exc}")

    candidates = [(c, "long") for c in longs if c["symbol"] in liquid]
    candidates += [(c, "short") for c in shorts if c["symbol"] in liquid]
    if _TESTING_TICKER_CAP:
        candidates = candidates[:_TESTING_TICKER_CAP]
    log.info("burry: %d candidates survive the liquidity floor", len(candidates))

    # 3/4. The value gates. One FMP call each, which is why they run last.
    passed: list[dict] = []
    for cand, side in candidates:
        sym = cand["symbol"]
        meta = liquid[sym]
        value = _value_read(fmp_client, sym)
        if not value:
            continue
        ok = _passes_long(value, meta["sector"]) if side == "long" \
            else _passes_short(value, meta["sector"])
        if not ok:
            continue
        shares = None
        if meta["market_cap"] and meta["price"]:
            shares = meta["market_cap"] / meta["price"]
        passed.append({
            **cand, **meta, **value,
            "side": side,
            "sector_ev_ebitda_ceiling": _SECTOR_EV_EBITDA_MAX.get(
                meta["sector"], _SECTOR_EV_EBITDA_DEFAULT),
            "rare_bird": _rare_bird(value, meta["price"], shares) if side == "long" else False,
        })

    # 5. Annotate with the reverse-DCF where the programme has published one.
    pi = _priced_in([p["symbol"] for p in passed])
    for p in passed:
        p.update(pi.get(p["symbol"], {
            "median_gap": None, "implied_revenue_cagr": None,
            "analyst_target_median": None, "n_targets": None,
        }))

    passed.sort(key=lambda p: (p["side"] != "long", p.get("sentiment_90d") or 0))
    n_long = sum(1 for p in passed if p["side"] == "long")
    n_short = len(passed) - n_long

    return ScreeningResult(
        triggered=bool(passed),
        ticker_count=len(passed),
        summary=_format_summary(passed, n_long, n_short, len(candidates), universe),
        data_used={
            "universe_covered": universe,
            "attention_candidates": len(longs) + len(shorts),
            "after_liquidity": len(candidates),
            "passed_long": n_long,
            "passed_short": n_short,
            "coverage_days": _COVERAGE_DAYS,
            "gates": {
                "ick_sentiment_max": _ICK_SENTIMENT_MAX,
                "neglect_mentions_max": _MAX_MENTIONS_LONG,
                "adored_sentiment_min": _ADORED_SENTIMENT_MIN,
                "crowded_mentions_min": _MIN_MENTIONS_SHORT,
                "min_fcf_yield": _MIN_FCF_YIELD,
                "max_net_debt_to_ebitda": _MAX_NET_DEBT_TO_EBITDA,
                "sector_ev_ebitda_max": _SECTOR_EV_EBITDA_MAX,
            },
            # MUST be "symbols": runner._split_symbols_from_data_used pops this
            # key into market_screening_result_rows, which is what the /screenings
            # page and the arena's get_screening_results read. Under any other
            # name the per-ticker payload stays buried in the JSONB.
            "symbols": passed,
        },
    )


def _format_summary(passed: list[dict], n_long: int, n_short: int,
                    n_candidates: int, universe: int) -> str:
    if not passed:
        return (f"No names cleared the value gates. {n_candidates} candidates passed "
                f"the attention gates out of {universe} covered tickers, but none "
                f"were both cheap enough and cash-generative enough to qualify.")

    def line(p: dict) -> str:
        ev = p.get("ev_to_ebitda")
        fcf = p.get("fcf_yield")
        gap = p.get("median_gap")
        bits = [
            f"{p['symbol']}",
            f"sent {p['sentiment_90d']:+.2f}" if p.get("sentiment_90d") is not None else "",
            f"{p['mentions_90d']} mentions",
            f"EV/EBITDA {ev:.1f}" if ev is not None else "",
            f"FCF yield {fcf:.1%}" if fcf is not None else "",
            f"{gap:+.0%} vs analyst median" if gap is not None else "",
            "RARE BIRD" if p.get("rare_bird") else "",
        ]
        return "  " + " · ".join(b for b in bits if b)

    head = (f"Burry deep value — {n_long} long, {n_short} short "
            f"(from {n_candidates} attention candidates, {universe} covered).")
    longs = [line(p) for p in passed if p["side"] == "long"][:_SUMMARY_TOP_N]
    shorts = [line(p) for p in passed if p["side"] == "short"][:_SUMMARY_TOP_N]
    out = [head]
    if longs:
        out.append("\nCHEAP, HATED, UNWATCHED:\n" + "\n".join(longs))
    if shorts:
        out.append("\nRICH, ADORED, CROWDED:\n" + "\n".join(shorts))
    return "\n".join(out)
