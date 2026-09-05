"""Second-Order Chain — the neighbour the headline forgot.

The strategy is simple to state and easy to get wrong: when a big story hits one
company, find the company economically attached to it whose price has NOT yet
reacted, and take that. The platform's 38k-edge relationship graph is the map.

This board exists because the agent running that strategy by hand lost money in
three specific, mechanical ways, and every one of them is a filter rather than a
judgement:

1. IT TRADED A NEIGHBOUR THAT HAD ALREADY MOVED. Its first trade bought LRCX
   after MU fell. Over that window MU fell 14.8% — and LRCX had already fallen
   14.5%, AMAT 13.2%. There was nothing left to collect. It could not have known:
   its tools were all news and graph, and "has it moved?" is a PRICE question.
   Quiet coverage is not a quiet price — sympathy selling moves a stock without
   generating a single article. So the `already_moved` gate here is computed on
   returns, and it is the gate that matters most.

2. IT GOT THE SIGN WRONG. Edge direction in this graph is unambiguous —
   `from -[supplier]-> to` means from SUPPLIES to (TSM->NVDA, MU->NVDA,
   NVDA->MSFT) — so the sign is arithmetic, not opinion: everyone in the chain
   moves WITH the headline, a competitor moves AGAINST it.

3. IT TRADED IMMATERIAL EDGES. It bought MU because the graph links Micron to
   Ford and GM; Micron's automotive exposure is a rounding error beside DRAM.
   `strength_avg` and `mention_count` are on every edge and a threshold drops
   that before a model ever sees it.

A NOTE ON SENTIMENT VS PRICE, because they disagree and both are needed. Over
that same MU window the SCORED sentiment was +0.309 across 75 articles while the
stock fell 15%. A sentiment-only board would have said "long the supplier" — the
identical mistake. The headline gate therefore fires on a big MOVE or a strong
sentiment reading, and both are reported so the reader can see when they part.

Pipeline:
  1. Headline names: enough coverage to be a real story, and either a strong
     one-directional sentiment reading or a large recent price move.
  2. Neighbours: every graph edge on a headline name above a strength and
     mention floor, DEDUPED to one edge per pair — the graph records both
     directions and sometimes several types for the same pair, which is how one
     relationship produced four rows with opposite signs.
  3. Tradeable: US listed and liquid enough to take and exit (the raw graph
     contains 000660 and 005930 — SK Hynix and Samsung — which are not).
  4. Sign: chain moves with, competitor moves against.
  5. NOT YET MOVED: the neighbour's return over the window is a small fraction
     of the headline's. This is the trade.
"""

from __future__ import annotations

import logging
import math
from datetime import date, timedelta
from typing import Any, Optional

from shared.db import get_pg_connection

from ..types import ScreeningResult

log = logging.getLogger(__name__)

_SUMMARY_TOP_N = 20

# ── The headline gate ───────────────────────────────────────────────────────
_WINDOW_DAYS = 4           # how recent a story has to be to still be tradeable
_MIN_HEAD_ARTICLES = 8     # below this it is not a story, it is a mention
_MIN_HEAD_SENTIMENT = 0.30 # a one-directional reading, not a mixed one
_MIN_HEAD_MOVE = 0.05      # ...or a 5% move, which counts even if coverage is calm

# ── The edge gate ───────────────────────────────────────────────────────────
_CHAIN_TYPES = ("supplier", "customer", "partner", "competitor", "subsidiary", "acquirer")
_MIN_STRENGTH = 0.70
_MIN_EDGE_MENTIONS = 3     # "a weak edge asserted in one article is a coincidence"
_EDGE_MAX_AGE_DAYS = 180

# ── The gate that matters ───────────────────────────────────────────────────
#: A neighbour has "already moved" once its return is this share of the
#: headline's. LRCX did 98% of MU's move and was still bought.
_MOVED_RATIO = 0.40
_LIQ_PRICE_MIN = 5.0
_LIQ_VOLUME_MIN = 300_000


def _sign_for(role: str) -> int:
    """+1 if the neighbour moves WITH the headline, -1 if against.

    The only asymmetric case is a competitor: a rival's trouble is your
    opportunity. Everything else in a value chain shares the shock.
    """
    return -1 if role == "competitor" else 1


def _role(from_t: str, to_t: str, rel: str, head: str) -> str:
    """The neighbour's role RELATIVE TO the headline name.

    `from -[supplier]-> to` reads "from supplies to", so the same edge means
    different things depending on which end the story landed on. Collapsing
    that into one label here is what makes the sign rule arithmetic later.
    """
    if rel in ("competitor", "partner", "subsidiary", "acquirer"):
        return rel
    peer_is_from = to_t == head
    if rel == "supplier":
        return "supplier" if peer_is_from else "customer"
    if rel == "customer":
        return "customer" if peer_is_from else "supplier"
    return rel


def _headlines_and_edges(as_of: Optional[date] = None) -> tuple[list[dict], int]:
    """Candidate (headline, neighbour) pairs, one row per PAIR.

    Deduped inside SQL with DISTINCT ON over the edge weight, because the graph
    holds both directions and occasionally several types for the same pair —
    HIMS/NVO came back as supplier, partner (twice) AND competitor, which is two
    different answers about which way to trade.
    """
    ref = as_of or date.today()
    sql = """
    with head as (
      select ticker, count(*) n, avg(sentiment_score) sent
      from swingtrader.ticker_sentiment_heads
      where article_ts >= %(ref)s::date - %(days)s and article_ts < %(ref)s::date + 1
      group by 1
      having count(*) >= %(min_arts)s
    ),
    quiet as (
      select ticker, count(*) n, avg(sentiment_score) sent
      from swingtrader.ticker_sentiment_heads
      where article_ts >= %(ref)s::date - %(days)s and article_ts < %(ref)s::date + 1
      group by 1
    ),
    pair as (
      select distinct on (h.ticker, case when e.from_ticker = h.ticker then e.to_ticker else e.from_ticker end)
             h.ticker head, h.n head_n, h.sent head_sent,
             case when e.from_ticker = h.ticker then e.to_ticker else e.from_ticker end peer,
             e.from_ticker, e.to_ticker, e.rel_type,
             e.strength_avg, e.mention_count
      from head h
      join swingtrader.ticker_relationship_edges e
        on (e.from_ticker = h.ticker or e.to_ticker = h.ticker)
      where e.rel_type = any(%(types)s)
        and e.strength_avg >= %(min_str)s
        and e.mention_count >= %(min_mentions)s
        and e.last_seen_at >= %(ref)s::date - %(edge_age)s
      order by h.ticker,
               case when e.from_ticker = h.ticker then e.to_ticker else e.from_ticker end,
               e.strength_avg * ln(1 + e.mention_count) desc
    )
    select p.head, p.head_n, p.head_sent, p.peer, p.from_ticker, p.to_ticker,
           p.rel_type, p.strength_avg, p.mention_count,
           coalesce(q.n, 0) peer_articles, q.sent peer_sent,
           (select count(*) from head) universe
    from pair p
    left join quiet q on q.ticker = p.peer
    where p.peer !~ '^[0-9]'                       -- non-US listings in the graph
      and p.peer ~ '^[A-Z][A-Z0-9.\\-]{0,6}$'
      and p.peer not in (select ticker from head)  -- the peer is not itself a story
    """
    args = {
        "ref": ref.isoformat(), "days": _WINDOW_DAYS, "min_arts": _MIN_HEAD_ARTICLES,
        "types": list(_CHAIN_TYPES), "min_str": _MIN_STRENGTH,
        "min_mentions": _MIN_EDGE_MENTIONS, "edge_age": _EDGE_MAX_AGE_DAYS,
    }
    with get_pg_connection() as conn, conn.cursor() as cur:
        cur.execute(sql, args)
        rows = cur.fetchall()

    universe = int(rows[0][11]) if rows else 0
    out = []
    for (head, head_n, head_sent, peer, ft, tt, rel, strength, mentions,
         peer_arts, peer_sent, _u) in rows:
        role = _role(ft, tt, rel, head)
        out.append({
            "head": head, "head_articles": int(head_n),
            "head_sentiment": round(float(head_sent), 4),
            "symbol": peer, "role": role, "edge_type": rel,
            "edge_strength": round(float(strength), 3),
            "edge_mentions": int(mentions),
            "edge_weight": round(float(strength) * math.log1p(int(mentions)), 3),
            "peer_articles": int(peer_arts or 0),
            "peer_sentiment": round(float(peer_sent), 4) if peer_sent is not None else None,
        })
    return out, universe


# ── The price gate: has the neighbour already moved? ────────────────────────

def _returns(price_book, tickers: list[str], start: date, end: date) -> dict[str, float]:
    """Simple return over the window per ticker, from daily closes."""
    out: dict[str, float] = {}
    try:
        price_book.load(tickers, start - timedelta(days=7), end)
    except Exception as exc:                                   # noqa: BLE001
        log.warning("second-order: price load failed: %s", exc)
        return out
    for t in tickers:
        try:
            a, _ = price_book.last_close_on_or_before(t, start)
            b, _ = price_book.last_close_on_or_before(t, end)
        except Exception:                                      # noqa: BLE001
            continue
        if a and b and a > 0:
            out[t] = b / a - 1.0
    return out


def run(client, screening: dict) -> ScreeningResult:  # noqa: ARG001
    """Run the board. ``screening["_as_of"]`` replays it at a past date."""
    from services.arena.marks import PriceBook
    from services.screener.fmp import fmp as FMP

    as_of = screening.get("_as_of")
    if isinstance(as_of, str):
        as_of = date.fromisoformat(as_of)
    ref = as_of or date.today()

    try:
        pairs, universe = _headlines_and_edges(as_of)
    except Exception as exc:                                   # noqa: BLE001
        log.exception("second-order: graph query failed")
        return ScreeningResult(triggered=False, error=f"graph query failed: {exc}")
    log.info("second-order: %d candidate pairs from %d headline names", len(pairs), universe)
    if not pairs:
        return ScreeningResult(
            triggered=False, ticker_count=0,
            summary="No headline story had a strongly-connected neighbour today.",
            data_used={"headline_universe": universe, "symbols": []},
        )

    # Tradeable + liquid. The graph is built from news text, so it contains
    # foreign listings and private companies that no order could ever fill.
    try:
        screen = FMP().stock_screener(price_min=_LIQ_PRICE_MIN, volume_min=_LIQ_VOLUME_MIN)
        liquid = {str(r["symbol"]): {"sector": r.get("sector") or "",
                                     "price": r.get("price")}
                  for _, r in screen.iterrows()}
    except Exception as exc:                                   # noqa: BLE001
        log.exception("second-order: FMP screener failed")
        return ScreeningResult(triggered=False, error=f"FMP screener failed: {exc}")
    pairs = [p for p in pairs if p["symbol"] in liquid]
    log.info("second-order: %d pairs survive the tradeable filter", len(pairs))

    # THE gate. Compare the neighbour's move to the headline's over the window.
    book = PriceBook()
    names = sorted({p["head"] for p in pairs} | {p["symbol"] for p in pairs})
    rets = _returns(book, names, ref - timedelta(days=_WINDOW_DAYS), ref)

    passed: list[dict] = []
    for p in pairs:
        hr, pr = rets.get(p["head"]), rets.get(p["symbol"])
        if hr is None or pr is None:
            continue
        # The headline has to have actually happened: a big move OR a strong read.
        if abs(hr) < _MIN_HEAD_MOVE and abs(p["head_sentiment"]) < _MIN_HEAD_SENTIMENT:
            continue
        # Direction of the shock: the price move leads, sentiment breaks a tie.
        shock = hr if abs(hr) >= _MIN_HEAD_MOVE else p["head_sentiment"]
        expected = _sign_for(p["role"]) * (1 if shock > 0 else -1)
        # Has the neighbour already reacted? Signed so the reader can see WHICH
        # way, but gated on the ABSOLUTE share — the premise is that the market
        # has not connected the two names yet, and a neighbour that moved hard
        # in EITHER direction has been connected. Gating only on the positive
        # side let SNDK through at -148%: it rose 13.2% while being flagged as a
        # short, which is not an overlooked name, it is a disagreeing one.
        captured = (pr * expected) / abs(hr) if hr else 0.0
        if abs(captured) >= _MOVED_RATIO:
            continue
        passed.append({
            **p,
            "side": "long" if expected > 0 else "short",
            "head_return": round(hr, 4),
            "peer_return": round(pr, 4),
            "captured_share": round(captured, 3),
            "sector": liquid[p["symbol"]]["sector"],
            "scan_date": ref.isoformat(),
        })

    passed = _resolve_conflicts(passed)
    passed.sort(key=lambda r: -(abs(r["head_return"]) * r["edge_weight"]))
    n_long = sum(1 for p in passed if p["side"] == "long")

    return ScreeningResult(
        triggered=bool(passed),
        ticker_count=len(passed),
        summary=_format(passed, n_long, len(passed) - n_long, len(pairs), universe),
        data_used={
            "headline_universe": universe,
            "candidate_pairs": len(pairs),
            "as_of": as_of.isoformat() if as_of else None,
            "window_days": _WINDOW_DAYS,
            "gates": {
                "min_head_articles": _MIN_HEAD_ARTICLES,
                "min_head_sentiment": _MIN_HEAD_SENTIMENT,
                "min_head_move": _MIN_HEAD_MOVE,
                "min_edge_strength": _MIN_STRENGTH,
                "min_edge_mentions": _MIN_EDGE_MENTIONS,
                "already_moved_ratio": _MOVED_RATIO,
            },
            "symbols": passed,
        },
    )


def _resolve_conflicts(rows: list[dict]) -> list[dict]:
    """One row per tradeable symbol, and never a symbol pointing both ways.

    A neighbour can hang off several headlines at once — GOOG came back as
    NVDA's customer (long) AND META's competitor (short) in the same run, which
    is an instruction to do both. The graph is right and the board was wrong to
    pass the contradiction on.

    So: group by symbol, keep the strongest link as the row, and record every
    other headline that reached it under ``also_linked_to``. When the sides
    disagree the name is DROPPED rather than resolved by weight — a name that
    two live stories push in opposite directions has no second-order edge left,
    which is exactly the situation the strategy is supposed to avoid.
    """
    by_symbol: dict[str, list[dict]] = {}
    for r in rows:
        by_symbol.setdefault(r["symbol"], []).append(r)

    out: list[dict] = []
    for symbol, group in by_symbol.items():
        if len({g["side"] for g in group}) > 1:
            log.info("second-order: dropping %s — %s point opposite ways",
                     symbol, " and ".join(f"{g['head']}({g['side']})" for g in group))
            continue
        group.sort(key=lambda g: -(abs(g["head_return"]) * g["edge_weight"]))
        best = dict(group[0])
        if len(group) > 1:
            best["also_linked_to"] = [
                {"head": g["head"], "role": g["role"], "edge_weight": g["edge_weight"]}
                for g in group[1:]
            ]
            # Several independent stories pushing the same way is corroboration,
            # and the ranking should see it.
            best["corroborating_heads"] = len(group)
        out.append(best)
    return out


def _format(rows: list[dict], n_long: int, n_short: int,
            n_pairs: int, universe: int) -> str:
    if not rows:
        return (f"No un-moved neighbours today. {n_pairs} connected pairs came off "
                f"{universe} headline names, but every neighbour had already "
                f"collected its share of the move.")
    head = (f"Second-order chain — {n_long} long, {n_short} short "
            f"(from {n_pairs} connected pairs, {universe} headline names).")
    lines = []
    for r in rows[:_SUMMARY_TOP_N]:
        lines.append(
            f"  {r['symbol']:<6} {r['side'].upper():<5} is {r['head']}'s {r['role']} "
            f"| {r['head']} {r['head_return']:+.1%}, {r['symbol']} {r['peer_return']:+.1%} "
            f"({r['captured_share']:.0%} captured) "
            f"| edge {r['edge_strength']:.2f} x{r['edge_mentions']}"
        )
    return head + "\n\n" + "\n".join(lines)
