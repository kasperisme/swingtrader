"""
The two non-LLM competitors.

They exist so the leaderboard can be read. Nine agents compete; one finishes
first. Without a benchmark and a null, "first place" is a ranking, not a result —
and the loudest, most confident-sounding narrative would win the marketing even
if it lost the money.

  - ``the-index``    buys SPY with everything on its first run and holds. It goes
                     through the identical broker — same slippage, same open
                     fills, same marks — so its number is comparable rather than
                     merely adjacent.
  - ``the-coinflip`` picks uniformly at random from the same universe under the
                     same risk limits and rotates weekly. Its randomness is
                     SEEDED on (slug, date), so a re-run of a past session
                     reproduces the same picks. An unseeded control could be
                     silently re-rolled until it looked bad, which would make it
                     worthless as a control.

Neither reads news, calls a model, or writes a narrative beyond a fixed line.
"""

from __future__ import annotations

import hashlib
import logging
import random
from datetime import date, datetime, timezone
from typing import Any

from . import store
from .broker import Broker
from .types import OrderIntent, PortfolioSnapshot

log = logging.getLogger(__name__)

#: What ``the-index`` buys. SPY is the reference every retail investor actually
#: has access to, which is the comparison that matters here.
BENCHMARK_TICKER = "SPY"

#: ``the-coinflip`` rebalances on this cadence rather than daily — a daily
#: random rotation would lose to transaction costs by construction, which would
#: make it a straw man rather than a null hypothesis.
COINFLIP_REBALANCE_DAYS = 7


def _seeded_rng(slug: str, session: date) -> random.Random:
    """Deterministic per (agent, session). Same day in, same picks out."""
    digest = hashlib.sha256(f"{slug}:{session.isoformat()}".encode()).hexdigest()
    return random.Random(int(digest[:16], 16))


def run_control(
    agent: dict[str, Any],
    *,
    session: date,
    intended_for: date,
    broker: Broker,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Dispatch a deterministic agent's daily run."""
    slug = agent.get("strategy_key") or agent["slug"]
    handlers = {"jack-boggle": _run_index, "burton-malarkey": _run_coinflip}
    handler = handlers.get(slug)
    if handler is None:
        raise ValueError(f"no deterministic handler for strategy_key {slug!r}")

    decision = store.open_decision(agent["id"], intended_for, llm_model=None)
    started = datetime.now(timezone.utc)
    if not dry_run:
        store.cancel_pending_for(agent["id"], intended_for)
    portfolio = store.load_portfolio(agent, as_of=session)

    intents, narrative = handler(agent, portfolio, session, broker)

    if dry_run:
        return {
            "slug": agent["slug"],
            "dry_run": True,
            "intents": [(i.side, i.ticker, i.quantity) for i in intents],
            "narrative": narrative,
        }

    accepted = rejected = 0
    refused: list[str] = []
    for intent in intents:
        price, _ = broker.prices.last_close_on_or_before(intent.ticker, session)
        row = broker.submit(
            agent,
            intent,
            portfolio=portfolio,
            decision_id=decision.get("id"),
            intended_for=intended_for,
            reference_price=price,
        )
        if row.get("status") == "rejected":
            rejected += 1
            refused.append(intent.ticker)
            log.info(
                "arena/%s: rejected %s %s x%g — %s",
                agent["slug"], intent.side, intent.ticker, intent.quantity,
                row.get("reject_reason"),
            )
        else:
            accepted += 1

    # The narrative is written before the broker rules on the orders, so any
    # refusal is appended here. A published summary that claims a trade the
    # broker refused would be the exact dishonesty this whole design avoids.
    if refused:
        narrative += (
            f" The broker refused {len(refused)} of these orders "
            f"({', '.join(refused)}) — they did not fit the risk limits."
        )

    store.close_decision(
        decision["id"],
        {
            "status": "ok",
            "narrative": narrative,
            "orders_requested": len(intents),
            "orders_accepted": accepted,
            "orders_rejected": rejected,
            "nav_at_decision": round(portfolio.nav, 2),
            "cash_at_decision": round(portfolio.cash, 2),
            "duration_ms": int(
                (datetime.now(timezone.utc) - started).total_seconds() * 1000
            ),
        },
    )
    return {
        "slug": agent["slug"],
        "status": "ok",
        "orders_accepted": accepted,
        "orders_rejected": rejected,
        "narrative": narrative,
    }


# ── the-index ────────────────────────────────────────────────────────────────


def _run_index(
    agent: dict[str, Any],
    portfolio: PortfolioSnapshot,
    session: date,
    broker: Broker,
) -> tuple[list[OrderIntent], str]:
    """Buy the benchmark once, with everything, then never trade again."""
    if portfolio.position(BENCHMARK_TICKER) is not None:
        return [], (
            f"Holding {BENCHMARK_TICKER}. No action — that is the entire strategy. "
            "Every other agent in this competition has to beat a position anyone "
            "could open in one click and then ignore."
        )

    broker.prices.load([BENCHMARK_TICKER], session.replace(year=session.year - 1), session)
    price, _ = broker.prices.last_close_on_or_before(BENCHMARK_TICKER, session)
    if not price:
        return [], f"No {BENCHMARK_TICKER} price available for {session.isoformat()}; stayed in cash."

    # Leave the broker's cash buffer unspent so the open gap cannot reject the
    # one order this agent will ever place.
    from .broker import CASH_BUFFER

    shares = int((portfolio.cash * (1 - CASH_BUFFER - 0.005)) // price)
    if shares < 1:
        return [], "Not enough cash to buy a share of the benchmark."

    return (
        [
            OrderIntent(
                ticker=BENCHMARK_TICKER,
                side="buy",
                quantity=shares,
                thesis=(
                    "Buy and hold the benchmark. This is the control: it is here to be "
                    "beaten, and to show what beating it is actually worth."
                ),
                conviction=1.0,
            )
        ],
        f"Bought {shares} shares of {BENCHMARK_TICKER} at roughly ${price:,.2f} with the "
        f"full account. That is the last trade this agent will make.",
    )


# ── the-coinflip ─────────────────────────────────────────────────────────────


def _run_coinflip(
    agent: dict[str, Any],
    portfolio: PortfolioSnapshot,
    session: date,
    broker: Broker,
) -> tuple[list[OrderIntent], str]:
    """Sell everything and buy N random names, once a week."""
    funded = agent.get("funded_on")
    if funded:
        try:
            days_in = (session - date.fromisoformat(str(funded)[:10])).days
        except ValueError:
            days_in = 0
        if portfolio.positions and days_in % COINFLIP_REBALANCE_DAYS != 0:
            return [], (
                f"Holding {len(portfolio.positions)} randomly chosen names. Rebalances "
                f"every {COINFLIP_REBALANCE_DAYS} days; not today."
            )

    rng = _seeded_rng(agent["slug"], session)
    n = int(agent.get("max_positions") or 8)

    intents = [
        OrderIntent(
            ticker=p.ticker,
            side="sell" if p.quantity > 0 else "buy",
            quantity=abs(p.quantity),
            thesis="Weekly random rebalance — closing the previous draw.",
        )
        for p in portfolio.positions
    ]

    # Draw from names the platform actually covers, so the control is exposed to
    # the same liquidity profile as the strategies rather than to the tail of the
    # universe where prices are thin and the comparison would be unfair.
    candidates = sorted(_liquid_candidates())
    if not candidates:
        return intents, "No candidate universe available; stayed in cash."
    picks = rng.sample(candidates, min(n, len(candidates)))

    broker.prices.load(picks, session.replace(year=session.year - 1), session)
    nav = portfolio.nav
    # Size on 1/N of NAV, not on the per-position cap: N names at the cap can
    # add up to more than 100% of the book, and the last draws would then be
    # rejected for cash — which would quietly turn the control into a
    # concentrated bet on whichever names happened to be drawn first.
    per_name = min(
        nav / max(n, 1),
        nav * float(agent.get("max_position_pct") or 0.12),
    ) * 0.9

    bought: list[str] = []
    for ticker in picks:
        price, _ = broker.prices.last_close_on_or_before(ticker, session)
        if not price:
            continue
        shares = int(per_name // price)
        if shares < 1:
            continue
        intents.append(
            OrderIntent(
                ticker=ticker,
                side="buy",
                quantity=shares,
                thesis=(
                    f"Random draw, seeded on {session.isoformat()}. No analysis was "
                    "performed. If a reasoning agent cannot beat this, its reasoning "
                    "was decoration."
                ),
            )
        )
        bought.append(ticker)

    return intents, (
        f"Weekly random rebalance: closed {len(portfolio.positions)} positions and drew "
        f"{', '.join(bought) if bought else 'nothing'}. Seeded on the session date, so "
        "this draw is reproducible and cannot be re-rolled."
    )


def _liquid_candidates(min_market_cap: int = 2_000_000_000) -> set[str]:
    """Actively-traded names above a market-cap floor.

    The floor is the fairness control: without it the random agent draws mostly
    micro-caps, loses on spread and data quality, and flatters every strategy it
    is supposed to be testing.
    """
    from shared.db import get_supabase_client

    symbols: set[str] = set()
    page, size = 0, 1000
    while True:
        res = (
            get_supabase_client()
            .schema("swingtrader")
            .table("tickers")
            .select("symbol")
            .eq("is_actively_trading", True)
            .gte("market_cap", min_market_cap)
            .range(page * size, page * size + size - 1)
            .execute()
        )
        rows = res.data or []
        symbols.update((r["symbol"] or "").upper().strip() for r in rows if r.get("symbol"))
        if len(rows) < size:
            break
        page += 1
    return {s for s in symbols if s and s.isalpha()}
