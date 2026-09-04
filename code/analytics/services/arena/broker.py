"""
The broker — the deterministic half of the arena.

Nothing in this module calls an LLM. It takes order INTENTS, decides whether
they are legal, fills the legal ones at the next session's open, keeps cash and
positions consistent, books realised P&L on closes, and appends the NAV curve.

The rules it enforces, and why each one exists:

  - **Universe.** Only actively-traded NYSE/NASDAQ names (plus SPY/QQQ). Without
    this an agent can win or lose on the data quality of illiquid tickers rather
    than on its approach.
  - **No leverage, no negative cash.** Cash is checked before the order is
    queued (against an estimate) and again at the fill (against the real price).
  - **Position cap / count cap / gross-exposure cap.** Per agent, from its spec.
    An agent that ignores the limits in its prompt gets a rejection it can read
    on its next run — the prompt is a hint, this is the rule.
  - **Shorts only where allowed.** A sell that would take a position below zero
    is rejected unless the agent's spec permits shorting.
  - **Fill at the next open, with slippage against the agent.** An agent decides
    after Monday's close and fills at Tuesday's open. Filling at the decision
    session's close would hand every agent a free overnight gap, which is the
    easiest way to manufacture a fake edge.

Rejections are stored, not discarded. "The agent tried to put 80% of the book in
one name" is a finding about the approach.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any, Optional

from . import store
from .marks import PriceBook
from .types import OrderIntent, PortfolioSnapshot

log = logging.getLogger(__name__)

#: One-way execution cost, applied against the agent on every fill. Retail
#: commissions are zero on US equities now, so slippage is the honest cost —
#: 5bp is on the optimistic side of realistic for liquid large caps and on the
#: generous side for anything small, which is a bias we accept and document
#: rather than tune.
SLIPPAGE_BPS = 5.0
COMMISSION_PER_ORDER = 0.0

#: Leave a little cash unspent when sizing at submit time. The estimate uses the
#: last close; the fill uses the next open. Without the buffer, an agent that
#: sizes to exactly 100% of cash gets rejected by any upward gap.
CASH_BUFFER = 0.03

#: Ignore dust rather than carrying 0.0001-share positions forever.
MIN_QUANTITY = 1e-6


class OrderRejected(Exception):
    """Raised by validation, caught by ``submit`` and recorded on the order."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fill_price(reference: float, side: str) -> float:
    """Slippage always works against the agent."""
    adj = SLIPPAGE_BPS / 10_000.0
    return reference * (1 + adj) if side == "buy" else reference * (1 - adj)


class Broker:
    """Order validation, execution and accounting for one arena.

    Holds no per-agent state: every method takes the agent row (and, where the
    limits matter, its spec) so one Broker instance serves the whole roster in a
    single pass.
    """

    def __init__(self, prices: PriceBook, universe: Optional[set[str]] = None) -> None:
        self.prices = prices
        self._universe = universe

    @property
    def universe(self) -> set[str]:
        if self._universe is None:
            self._universe = store.tradeable_universe()
        return self._universe

    # ── Submit ──────────────────────────────────────────────────────────────

    def submit(
        self,
        agent: dict[str, Any],
        intent: OrderIntent,
        *,
        portfolio: PortfolioSnapshot,
        decision_id: Optional[str],
        intended_for: date,
        reference_price: Optional[float],
    ) -> dict[str, Any]:
        """Validate an intent and record it, pending or rejected.

        Returns the stored order row. Never raises for a bad intent — an invalid
        order is a recorded rejection, because silently dropping it would hide
        the fact that the agent asked for it.

        ``portfolio`` is mutated to reflect an accepted order's *reservation*
        (cash and a provisional position), so a batch of orders from one
        decision is validated against the book as it will actually be, not
        against the same starting cash N times over.
        """
        intent = intent.normalized()
        base = {
            "agent_id": agent["id"],
            "decision_id": decision_id,
            "ticker": intent.ticker,
            "side": intent.side,
            "quantity": max(round(intent.quantity, 4), 0.0001),
            "thesis": intent.thesis or None,
            "conviction": intent.conviction,
            "stop_price": intent.stop_price,
            "target_price": intent.target_price,
            "intended_for": intended_for.isoformat(),
            "reference_price": reference_price,
            "submitted_at": _now(),
        }

        try:
            self._validate(agent, intent, portfolio, reference_price)
        except OrderRejected as exc:
            return store.insert_order(
                {**base, "status": "rejected", "reject_reason": str(exc)[:500]}
            )

        row = store.insert_order({**base, "status": "pending"})
        self._reserve(portfolio, intent, float(reference_price))
        return row

    def _validate(
        self,
        agent: dict[str, Any],
        intent: OrderIntent,
        portfolio: PortfolioSnapshot,
        reference_price: Optional[float],
    ) -> None:
        if intent.side not in ("buy", "sell"):
            raise OrderRejected(f"side must be 'buy' or 'sell', got {intent.side!r}")
        if intent.quantity <= 0:
            raise OrderRejected("quantity must be greater than zero")
        if not intent.ticker:
            raise OrderRejected("ticker is required")
        if intent.ticker not in self.universe:
            raise OrderRejected(
                f"{intent.ticker} is not in the tradeable universe "
                "(actively-traded NYSE/NASDAQ equities and SPY/QQQ)"
            )
        if not reference_price or reference_price <= 0:
            raise OrderRejected(f"no recent price available for {intent.ticker}")

        nav = portfolio.nav
        if nav <= 0:
            raise OrderRejected("account has no NAV left to trade")

        existing = portfolio.position(intent.ticker)
        held = existing.quantity if existing else 0.0
        signed = intent.quantity if intent.side == "buy" else -intent.quantity
        resulting = held + signed
        notional = intent.quantity * reference_price

        # Shorting: only if the spec allows it, and only where the sell actually
        # takes the position below flat (selling a long you own is always fine).
        if resulting < -MIN_QUANTITY and not agent.get("allow_shorts"):
            raise OrderRejected(
                f"selling {intent.quantity:g} {intent.ticker} against a holding of "
                f"{held:g} would open a short position, which this agent may not do"
            )

        # Cash. A buy spends; a short sale credits cash, so only buys and covers
        # need the check. Covering a short is a buy, hence the single branch.
        if intent.side == "buy":
            needed = notional + COMMISSION_PER_ORDER
            available = portfolio.cash * (1 - CASH_BUFFER)
            if needed > available:
                raise OrderRejected(
                    f"insufficient cash: {intent.ticker} x{intent.quantity:g} needs "
                    f"${needed:,.0f} but only ${available:,.0f} is available "
                    f"(cash ${portfolio.cash:,.0f}, {CASH_BUFFER:.0%} reserved for gap risk)"
                )

        # Concentration. Checked on the resulting position, and only when the
        # order INCREASES exposure — an agent must always be able to reduce a
        # position that has grown past the cap by appreciating.
        max_pos_pct = float(agent.get("max_position_pct") or 0.20)
        resulting_notional = abs(resulting) * reference_price
        if abs(resulting) > abs(held) and resulting_notional > nav * max_pos_pct:
            raise OrderRejected(
                f"position limit: {intent.ticker} would be ${resulting_notional:,.0f} "
                f"({resulting_notional / nav:.1%} of ${nav:,.0f} NAV), over the "
                f"{max_pos_pct:.0%} per-position cap"
            )

        # Position count — only opening a NEW name can breach it.
        #
        # 0 means NO cap. Note this cannot be written as `or 10`: that turns a
        # deliberate 0 back into 10, which is how a removed cap silently comes
        # back. The per-position weight and gross-exposure limits still bound
        # the book, so "no count cap" is not "no risk limit" — it only stops the
        # agent spending rounds on rejections when breadth is part of its method.
        raw_max = agent.get("max_positions")
        max_positions = 10 if raw_max is None else int(raw_max)
        opens_new_name = abs(held) <= MIN_QUANTITY and abs(resulting) > MIN_QUANTITY
        if max_positions > 0 and opens_new_name and len(portfolio.positions) >= max_positions:
            raise OrderRejected(
                f"position count limit: already holding {len(portfolio.positions)} "
                f"names, cap is {max_positions}. Close something first."
            )

        # Gross exposure — long + |short|, as a multiple of NAV.
        max_gross = float(agent.get("max_gross_exposure_pct") or 1.0)
        gross_after = (
            portfolio.gross_exposure
            - abs(held) * reference_price
            + abs(resulting) * reference_price
        )
        if gross_after > nav * max_gross * (1 + 1e-9):
            raise OrderRejected(
                f"gross exposure limit: order would take exposure to ${gross_after:,.0f} "
                f"({gross_after / nav:.0%} of NAV), over the {max_gross:.0%} cap"
            )

    def _reserve(
        self, portfolio: PortfolioSnapshot, intent: OrderIntent, reference_price: float
    ) -> None:
        """Apply an accepted order to the in-memory book so the next order in
        the same batch is validated against the remaining cash, not the original."""
        signed = intent.quantity if intent.side == "buy" else -intent.quantity
        portfolio.cash -= signed * reference_price + COMMISSION_PER_ORDER

        existing = portfolio.position(intent.ticker)
        if existing is None:
            from .types import PositionRow

            portfolio.positions.append(
                PositionRow(
                    ticker=intent.ticker,
                    quantity=signed,
                    avg_cost=reference_price,
                    last_price=reference_price,
                )
            )
            return

        resulting = existing.quantity + signed
        if abs(resulting) <= MIN_QUANTITY:
            portfolio.positions.remove(existing)
            return
        if existing.quantity * signed > 0:  # adding in the same direction
            existing.avg_cost = (
                abs(existing.quantity) * existing.avg_cost
                + abs(signed) * reference_price
            ) / abs(resulting)
        elif existing.quantity * resulting < 0:  # flipped through zero
            existing.avg_cost = reference_price
        existing.quantity = resulting

    # ── Fill ────────────────────────────────────────────────────────────────

    def fill_pending(self, session: date, agents_by_id: dict[str, dict]) -> dict[str, int]:
        """Fill every pending order at ``session``'s open.

        Orders are processed per agent in submission order so cash is consumed
        in the order the agent asked for it — an agent that queues more than it
        can afford loses the *last* order, not an arbitrary one.
        """
        stats = {"filled": 0, "rejected": 0, "skipped": 0}
        pending = store.list_pending_orders(intended_for=session)
        if not pending:
            return stats

        by_agent: dict[str, list[dict]] = {}
        for order in pending:
            by_agent.setdefault(order["agent_id"], []).append(order)

        for agent_id, orders in by_agent.items():
            agent = agents_by_id.get(agent_id)
            if agent is None:
                stats["skipped"] += len(orders)
                continue
            cash = store.get_cash(agent_id)
            if cash is None:
                stats["skipped"] += len(orders)
                continue
            positions = {p.ticker: p for p in store.list_positions(agent_id)}

            for order in orders:
                result = self._fill_one(order, agent, cash, positions, session)
                if result is None:
                    stats["rejected"] += 1
                    continue
                cash = result
                # Written per fill, not once per batch. Positions are already
                # written through immediately; batching the cash write would
                # leave a window where a crash mid-batch produces a book whose
                # positions have moved but whose cash has not — an inflated NAV
                # that nothing downstream could detect. A handful of extra
                # round-trips a day is a cheap price for not having that window.
                store.set_cash(agent_id, cash)
                stats["filled"] += 1

        return stats

    def _fill_one(
        self,
        order: dict[str, Any],
        agent: dict[str, Any],
        cash: float,
        positions: dict[str, Any],
        session: date,
    ) -> Optional[float]:
        """Execute one order. Returns the new cash balance, or None if rejected.

        The caller persists the returned cash before moving to the next order,
        so cash and positions never disagree by more than one in-flight fill.
        """
        ticker = order["ticker"]
        side = order["side"]
        quantity = float(order["quantity"])

        reference = self.prices.open_price(ticker, session)
        if not reference or reference <= 0:
            store.update_order(
                order["id"],
                {
                    "status": "rejected",
                    "reject_reason": f"{ticker} did not trade on {session.isoformat()}",
                },
            )
            return None

        price = _fill_price(reference, side)
        signed = quantity if side == "buy" else -quantity
        cash_effect = -(signed * price) - COMMISSION_PER_ORDER

        if side == "buy" and cash + cash_effect < -1e-6:
            store.update_order(
                order["id"],
                {
                    "status": "rejected",
                    "reject_reason": (
                        f"insufficient cash at fill: needed ${quantity * price:,.0f} "
                        f"at the ${price:,.2f} open, had ${cash:,.0f}"
                    ),
                },
            )
            return None

        existing = positions.get(ticker)
        held = existing.quantity if existing else 0.0
        avg_cost = existing.avg_cost if existing else 0.0
        resulting = held + signed

        # Realised P&L on the portion that CLOSES exposure. Opening fills carry
        # NULL so win-rate is computed over closes only.
        realized_pnl: Optional[float] = None
        realized_pct: Optional[float] = None
        if held != 0 and (held > 0) != (signed > 0):
            closing_qty = min(abs(held), abs(signed))
            direction = 1.0 if held > 0 else -1.0
            realized_pnl = closing_qty * (price - avg_cost) * direction
            realized_pct = (
                direction * (price - avg_cost) / avg_cost if avg_cost else None
            )

        # Update the position row.
        if abs(resulting) <= MIN_QUANTITY:
            store.delete_position(agent["id"], ticker)
            positions.pop(ticker, None)
        else:
            if existing is None or held == 0:
                new_cost = price
            elif (held > 0) == (signed > 0):  # adding to the same side
                new_cost = (abs(held) * avg_cost + abs(signed) * price) / abs(resulting)
            elif (held > 0) != (resulting > 0):  # flipped through zero
                new_cost = price
            else:  # partial close — the remaining lot keeps its basis
                new_cost = avg_cost
            store.upsert_position(
                agent["id"],
                ticker,
                quantity=resulting,
                avg_cost=new_cost,
                last_price=price,
            )
            from .types import PositionRow

            positions[ticker] = PositionRow(
                ticker=ticker, quantity=resulting, avg_cost=new_cost, last_price=price
            )

        store.update_order(
            order["id"],
            {
                "status": "filled",
                "filled_at": _now(),
                "fill_price": round(price, 4),
                "reference_price": round(reference, 4),
                "slippage_bps": SLIPPAGE_BPS,
                "commission": COMMISSION_PER_ORDER,
                "notional": round(cash_effect, 2),
                "realized_pnl": round(realized_pnl, 2) if realized_pnl is not None else None,
                "realized_pct": round(realized_pct, 6) if realized_pct is not None else None,
            },
        )
        return cash + cash_effect

    # ── Mark ────────────────────────────────────────────────────────────────

    def mark_to_market(self, agent: dict[str, Any], session: date) -> Optional[dict[str, Any]]:
        """Mark every position to ``session``'s close and append the NAV row.

        Returns the NAV row written, or None if the agent has no account yet.
        Idempotent per (agent, session) — re-running a mark overwrites the row
        rather than double-counting the day.
        """
        agent_id = agent["id"]
        cash = store.get_cash(agent_id)
        if cash is None:
            return None

        positions = store.list_positions(agent_id)
        stale: list[str] = []
        for p in positions:
            price, priced_on = self.prices.last_close_on_or_before(p.ticker, session)
            if price is None:
                # No bar anywhere in the lookback: keep the previous mark rather
                # than inventing one, and say so in the snapshot.
                stale.append(p.ticker)
                continue
            if priced_on != session:
                stale.append(p.ticker)
            p.last_price = price
            store.mark_position(agent_id, p.ticker, price)

        snapshot = PortfolioSnapshot(
            agent_id=agent_id,
            slug=agent["slug"],
            cash=float(cash),
            positions=positions,
            as_of=session,
        )
        nav = snapshot.nav
        starting = float(agent.get("starting_cash") or 100_000)

        prev = store.latest_nav_row(agent_id, before=session)
        prev_nav = float(prev["nav"]) if prev else None
        daily_return = (
            (nav / prev_nav - 1.0) if prev_nav and prev_nav > 0 else None
        )

        peak = store.peak_nav(agent_id, through=session)
        peak = max(peak or starting, nav, starting)
        drawdown = (nav / peak - 1.0) if peak > 0 else None

        row = {
            "agent_id": agent_id,
            "as_of": session.isoformat(),
            "cash": round(snapshot.cash, 2),
            "long_value": round(snapshot.long_value, 2),
            "short_value": round(snapshot.short_value, 2),
            "nav": round(nav, 2),
            "n_positions": len(positions),
            "daily_return": round(daily_return, 8) if daily_return is not None else None,
            "cumulative_return": round(nav / starting - 1.0, 8) if starting else None,
            "drawdown": round(drawdown, 8) if drawdown is not None else None,
            "positions": {
                "holdings": [
                    {
                        "ticker": p.ticker,
                        "quantity": round(p.quantity, 4),
                        "avg_cost": round(p.avg_cost, 4),
                        "mark": round(p.mark, 4),
                        "market_value": round(p.market_value, 2),
                    }
                    for p in positions
                ],
                "stale_marks": stale,
            },
        }
        store.upsert_nav(row)
        return row


def resolve_reference_prices(
    prices: PriceBook, tickers: list[str], on: date
) -> dict[str, float]:
    """Last known close at or before ``on`` for each ticker — the estimate the
    submit-time sizing checks run against."""
    out: dict[str, float] = {}
    for t in {(x or "").upper().strip() for x in tickers if x}:
        price, _ = prices.last_close_on_or_before(t, on)
        if price:
            out[t] = price
    return out
