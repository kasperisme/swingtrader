"""Tests for the arena broker's accounting and risk gates.

The broker is the part of the arena that must be exactly right: if cash,
average cost or realised P&L drift, every number on the public leaderboard is
wrong and no amount of good agent reasoning can rescue it. These tests run
entirely in-memory — no Supabase, no FMP, no LLM — by faking the store module's
row-level writes and the price book.
"""

from __future__ import annotations

from datetime import date

import pytest

from services.arena import broker as broker_mod
from services.arena.broker import Broker, SLIPPAGE_BPS
from services.arena.types import OrderIntent, PortfolioSnapshot, PositionRow


SESSION = date(2026, 9, 2)
AGENT = {
    "id": "agent-1",
    "slug": "test-agent",
    "starting_cash": 100_000.0,
    "max_position_pct": 0.20,
    "max_positions": 5,
    "max_gross_exposure_pct": 1.0,
    "allow_shorts": False,
}


# ── Fakes ────────────────────────────────────────────────────────────────────


class FakePrices:
    """A PriceBook stand-in with hand-set opens and closes."""

    def __init__(self, opens: dict[str, float], closes: dict[str, float] | None = None):
        self.opens = opens
        self.closes = closes or dict(opens)

    def open_price(self, ticker, on):
        return self.opens.get(ticker)

    def close_price(self, ticker, on):
        return self.closes.get(ticker)

    def last_close_on_or_before(self, ticker, on):
        price = self.closes.get(ticker)
        return (price, on) if price else (None, None)

    def load(self, tickers, start, end):
        pass


class FakeStore:
    """Captures the writes the broker makes, so they can be asserted on."""

    def __init__(self, cash: float = 100_000.0):
        self.cash = {"agent-1": cash}
        self.positions: dict[tuple[str, str], dict] = {}
        self.orders: dict[str, dict] = {}
        self.nav_rows: list[dict] = []
        self._next_id = 0

    # -- the subset of services.arena.store the broker touches --
    def insert_order(self, row):
        self._next_id += 1
        row = {**row, "id": f"order-{self._next_id}"}
        self.orders[row["id"]] = row
        return row

    def update_order(self, order_id, patch):
        self.orders[order_id].update(patch)

    def get_cash(self, agent_id):
        return self.cash.get(agent_id)

    def set_cash(self, agent_id, cash):
        self.cash[agent_id] = cash

    def list_positions(self, agent_id):
        return [
            PositionRow(
                ticker=t, quantity=p["quantity"], avg_cost=p["avg_cost"],
                last_price=p.get("last_price"),
            )
            for (a, t), p in self.positions.items()
            if a == agent_id
        ]

    def upsert_position(self, agent_id, ticker, *, quantity, avg_cost, last_price=None):
        self.positions[(agent_id, ticker)] = {
            "quantity": quantity, "avg_cost": avg_cost, "last_price": last_price,
        }

    def delete_position(self, agent_id, ticker):
        self.positions.pop((agent_id, ticker), None)

    def mark_position(self, agent_id, ticker, price):
        if (agent_id, ticker) in self.positions:
            self.positions[(agent_id, ticker)]["last_price"] = price

    def list_pending_orders(self, intended_for=None):
        return [o for o in self.orders.values() if o["status"] == "pending"]

    def latest_nav_row(self, agent_id, before=None):
        rows = [r for r in self.nav_rows if r["agent_id"] == agent_id]
        return rows[-1] if rows else None

    def peak_nav(self, agent_id, through):
        navs = [r["nav"] for r in self.nav_rows if r["agent_id"] == agent_id]
        return max(navs) if navs else None

    def upsert_nav(self, row):
        self.nav_rows.append(row)

    def tradeable_universe(self):
        return {"AAA", "BBB", "SPY"}


@pytest.fixture
def store(monkeypatch):
    fake = FakeStore()
    monkeypatch.setattr(broker_mod, "store", fake)
    return fake


def make_portfolio(cash=100_000.0, positions=None):
    return PortfolioSnapshot(
        agent_id="agent-1", slug="test-agent", cash=cash,
        positions=list(positions or []), as_of=SESSION,
    )


def submit(brk, portfolio, side, ticker, qty, price, agent=None):
    return brk.submit(
        agent or AGENT,
        OrderIntent(ticker=ticker, side=side, quantity=qty, thesis="test"),
        portfolio=portfolio,
        decision_id=None,
        intended_for=SESSION,
        reference_price=price,
    )


# ── Validation ───────────────────────────────────────────────────────────────


def test_rejects_ticker_outside_the_universe(store):
    brk = Broker(FakePrices({"AAA": 100.0}), universe={"AAA", "SPY"})
    row = submit(brk, make_portfolio(), "buy", "ZZZ", 10, 100.0)
    assert row["status"] == "rejected"
    assert "not in the tradeable universe" in row["reject_reason"]


def test_rejects_a_buy_it_cannot_afford(store):
    brk = Broker(FakePrices({"AAA": 100.0}), universe={"AAA"})
    row = submit(brk, make_portfolio(cash=1_000.0), "buy", "AAA", 100, 100.0)
    assert row["status"] == "rejected"
    assert "insufficient cash" in row["reject_reason"]


def test_rejects_a_position_over_the_concentration_cap(store):
    brk = Broker(FakePrices({"AAA": 100.0}), universe={"AAA"})
    # 300 x $100 = $30k = 30% of a $100k NAV, over the 20% cap.
    row = submit(brk, make_portfolio(), "buy", "AAA", 300, 100.0)
    assert row["status"] == "rejected"
    assert "position limit" in row["reject_reason"]


def test_allows_reducing_a_position_that_grew_past_the_cap(store):
    """A winner that appreciates through the cap must still be sellable —
    otherwise the agent is trapped in its best position."""
    brk = Broker(FakePrices({"AAA": 400.0}), universe={"AAA"})
    over_cap = PositionRow(ticker="AAA", quantity=100, avg_cost=100.0, last_price=400.0)
    portfolio = make_portfolio(cash=10_000.0, positions=[over_cap])
    row = submit(brk, portfolio, "sell", "AAA", 50, 400.0)
    assert row["status"] == "pending"


def test_rejects_a_short_when_shorting_is_not_allowed(store):
    brk = Broker(FakePrices({"AAA": 100.0}), universe={"AAA"})
    row = submit(brk, make_portfolio(), "sell", "AAA", 10, 100.0)
    assert row["status"] == "rejected"
    assert "short position" in row["reject_reason"]


def test_allows_a_short_when_the_agent_may_short(store):
    brk = Broker(FakePrices({"AAA": 100.0}), universe={"AAA"})
    agent = {**AGENT, "allow_shorts": True}
    row = submit(brk, make_portfolio(), "sell", "AAA", 100, 100.0, agent=agent)
    assert row["status"] == "pending"


def test_rejects_a_new_name_over_the_position_count_cap(store):
    brk = Broker(FakePrices({}), universe={"AAA", "BBB", "CCC", "DDD", "EEE", "FFF"})
    held = [
        PositionRow(ticker=t, quantity=10, avg_cost=10.0, last_price=10.0)
        for t in ("AAA", "BBB", "CCC", "DDD", "EEE")
    ]
    portfolio = make_portfolio(cash=50_000.0, positions=held)
    row = submit(brk, portfolio, "buy", "FFF", 10, 10.0)
    assert row["status"] == "rejected"
    assert "position count limit" in row["reject_reason"]


def test_a_batch_of_orders_cannot_spend_the_same_cash_twice(store):
    """Each accepted order reserves its cash, so the second one in a batch is
    validated against what the first left behind."""
    brk = Broker(FakePrices({"AAA": 100.0, "BBB": 100.0}), universe={"AAA", "BBB", "SPY"})
    # Concentration cap lifted so this test exercises the cash path alone.
    agent = {**AGENT, "max_position_pct": 1.0}
    portfolio = make_portfolio(cash=30_000.0)

    first = submit(brk, portfolio, "buy", "AAA", 200, 100.0, agent=agent)   # $20k
    second = submit(brk, portfolio, "buy", "BBB", 150, 100.0, agent=agent)  # only ~$10k left
    assert first["status"] == "pending"
    assert second["status"] == "rejected"
    assert "insufficient cash" in second["reject_reason"]


# ── Fills ────────────────────────────────────────────────────────────────────


def test_a_buy_fills_at_the_open_with_slippage_against_the_agent(store):
    brk = Broker(FakePrices({"AAA": 50.0}), universe={"AAA"})
    submit(brk, make_portfolio(), "buy", "AAA", 100, 50.0)

    brk.fill_pending(SESSION, {"agent-1": AGENT})

    order = next(iter(store.orders.values()))
    expected = 50.0 * (1 + SLIPPAGE_BPS / 10_000)
    assert order["status"] == "filled"
    assert order["fill_price"] == pytest.approx(expected, rel=1e-9)
    assert store.cash["agent-1"] == pytest.approx(100_000 - 100 * expected)
    assert store.positions[("agent-1", "AAA")]["quantity"] == 100


def test_a_sell_fills_below_the_open(store):
    brk = Broker(FakePrices({"AAA": 50.0}), universe={"AAA"})
    store.positions[("agent-1", "AAA")] = {"quantity": 100, "avg_cost": 40.0}
    portfolio = make_portfolio(
        positions=[PositionRow(ticker="AAA", quantity=100, avg_cost=40.0, last_price=50.0)]
    )
    submit(brk, portfolio, "sell", "AAA", 100, 50.0)

    brk.fill_pending(SESSION, {"agent-1": AGENT})

    order = next(o for o in store.orders.values() if o["status"] == "filled")
    assert order["fill_price"] < 50.0


def test_an_order_in_a_name_that_did_not_trade_is_rejected_not_filled(store):
    """No bar means no session for that name. Filling it at a stale price would
    invent liquidity that did not exist."""
    brk = Broker(FakePrices({}, closes={"AAA": 50.0}), universe={"AAA"})
    submit(brk, make_portfolio(), "buy", "AAA", 10, 50.0)

    brk.fill_pending(SESSION, {"agent-1": AGENT})

    order = next(iter(store.orders.values()))
    assert order["status"] == "rejected"
    assert "did not trade" in order["reject_reason"]


def test_adding_to_a_position_weights_the_average_cost(store):
    brk = Broker(FakePrices({"AAA": 100.0}), universe={"AAA"})
    store.positions[("agent-1", "AAA")] = {"quantity": 100, "avg_cost": 50.0}
    portfolio = make_portfolio(
        positions=[PositionRow(ticker="AAA", quantity=100, avg_cost=50.0, last_price=100.0)]
    )
    submit(brk, portfolio, "buy", "AAA", 100, 100.0)

    brk.fill_pending(SESSION, {"agent-1": AGENT})

    fill = next(o for o in store.orders.values() if o["status"] == "filled")["fill_price"]
    position = store.positions[("agent-1", "AAA")]
    assert position["quantity"] == 200
    assert position["avg_cost"] == pytest.approx((100 * 50.0 + 100 * fill) / 200)


def test_closing_a_long_books_realised_pnl(store):
    brk = Broker(FakePrices({"AAA": 60.0}), universe={"AAA"})
    store.positions[("agent-1", "AAA")] = {"quantity": 100, "avg_cost": 50.0}
    portfolio = make_portfolio(
        positions=[PositionRow(ticker="AAA", quantity=100, avg_cost=50.0, last_price=60.0)]
    )
    submit(brk, portfolio, "sell", "AAA", 100, 60.0)

    brk.fill_pending(SESSION, {"agent-1": AGENT})

    order = next(o for o in store.orders.values() if o["status"] == "filled")
    fill = order["fill_price"]
    assert order["realized_pnl"] == pytest.approx(round(100 * (fill - 50.0), 2))
    assert order["realized_pct"] == pytest.approx(round((fill - 50.0) / 50.0, 6))
    assert ("agent-1", "AAA") not in store.positions  # flat positions are removed


def test_a_partial_close_keeps_the_remaining_lots_basis(store):
    brk = Broker(FakePrices({"AAA": 60.0}), universe={"AAA"})
    store.positions[("agent-1", "AAA")] = {"quantity": 100, "avg_cost": 50.0}
    portfolio = make_portfolio(
        positions=[PositionRow(ticker="AAA", quantity=100, avg_cost=50.0, last_price=60.0)]
    )
    submit(brk, portfolio, "sell", "AAA", 40, 60.0)

    brk.fill_pending(SESSION, {"agent-1": AGENT})

    position = store.positions[("agent-1", "AAA")]
    assert position["quantity"] == 60
    assert position["avg_cost"] == 50.0
    order = next(o for o in store.orders.values() if o["status"] == "filled")
    assert order["realized_pnl"] == pytest.approx(round(40 * (order["fill_price"] - 50.0), 2))


def test_a_profitable_short_books_a_positive_pnl(store):
    """Short at 100, cover at 80: the P&L sign must invert with the position."""
    agent = {**AGENT, "allow_shorts": True}
    brk = Broker(FakePrices({"AAA": 80.0}), universe={"AAA"})
    store.positions[("agent-1", "AAA")] = {"quantity": -100, "avg_cost": 100.0}
    portfolio = make_portfolio(
        cash=110_000.0,
        positions=[PositionRow(ticker="AAA", quantity=-100, avg_cost=100.0, last_price=80.0)],
    )
    submit(brk, portfolio, "buy", "AAA", 100, 80.0, agent=agent)

    brk.fill_pending(SESSION, {"agent-1": agent})

    order = next(o for o in store.orders.values() if o["status"] == "filled")
    assert order["realized_pnl"] > 0
    assert order["realized_pnl"] == pytest.approx(round(100 * (order["fill_price"] - 100.0) * -1, 2))


def test_short_proceeds_are_credited_to_cash(store):
    agent = {**AGENT, "allow_shorts": True}
    brk = Broker(FakePrices({"AAA": 100.0}), universe={"AAA"})
    submit(brk, make_portfolio(), "sell", "AAA", 100, 100.0, agent=agent)

    brk.fill_pending(SESSION, {"agent-1": agent})

    assert store.cash["agent-1"] > 100_000
    assert store.positions[("agent-1", "AAA")]["quantity"] == -100


def test_a_fill_that_no_longer_fits_the_cash_is_rejected_at_the_open(store):
    """Sized against Monday's close, gapped up hard on Tuesday's open."""
    brk = Broker(FakePrices({"AAA": 500.0}, closes={"AAA": 100.0}), universe={"AAA"})
    agent = {**AGENT, "max_position_pct": 1.0}
    store.cash["agent-1"] = 20_000.0
    submit(brk, make_portfolio(cash=20_000.0), "buy", "AAA", 190, 100.0, agent=agent)

    brk.fill_pending(SESSION, {"agent-1": agent})

    order = next(iter(store.orders.values()))
    assert order["status"] == "rejected"
    assert "insufficient cash at fill" in order["reject_reason"]
    assert store.cash["agent-1"] == 20_000.0  # untouched


# ── Marks ────────────────────────────────────────────────────────────────────


def test_nav_is_cash_plus_the_signed_book(store):
    brk = Broker(FakePrices({}, closes={"AAA": 60.0}), universe={"AAA"})
    store.cash["agent-1"] = 40_000.0
    store.positions[("agent-1", "AAA")] = {"quantity": 1000, "avg_cost": 50.0}

    row = brk.mark_to_market(AGENT, SESSION)

    assert row["nav"] == pytest.approx(40_000 + 1000 * 60.0)
    assert row["long_value"] == pytest.approx(60_000)
    assert row["cumulative_return"] == pytest.approx(0.0)


def test_a_short_that_moves_against_the_agent_costs_nav(store):
    """Short 100 at $100 (cash 110k, position -100). Price to $120: NAV must
    fall by $2,000, not rise."""
    brk = Broker(FakePrices({}, closes={"AAA": 120.0}), universe={"AAA"})
    store.cash["agent-1"] = 110_000.0
    store.positions[("agent-1", "AAA")] = {"quantity": -100, "avg_cost": 100.0}

    row = brk.mark_to_market(AGENT, SESSION)

    assert row["nav"] == pytest.approx(110_000 - 12_000)
    assert row["short_value"] == pytest.approx(12_000)


def test_daily_return_and_drawdown_track_the_previous_row(store):
    brk = Broker(FakePrices({}, closes={"AAA": 90.0}), universe={"AAA"})
    store.cash["agent-1"] = 0.0
    store.positions[("agent-1", "AAA")] = {"quantity": 1000, "avg_cost": 100.0}
    store.nav_rows.append({"agent_id": "agent-1", "as_of": "2026-09-01", "nav": 110_000.0})

    row = brk.mark_to_market(AGENT, SESSION)

    assert row["nav"] == pytest.approx(90_000)
    assert row["daily_return"] == pytest.approx(90_000 / 110_000 - 1)
    assert row["drawdown"] == pytest.approx(90_000 / 110_000 - 1)   # peak was 110k
    assert row["cumulative_return"] == pytest.approx(-0.10)


def test_a_position_with_no_recent_bar_is_flagged_stale_not_dropped(store):
    """An untradeable name keeps its last mark and is named in the snapshot —
    silently valuing it at zero would look like a catastrophic loss."""
    brk = Broker(FakePrices({}, closes={}), universe={"AAA"})
    store.cash["agent-1"] = 50_000.0
    store.positions[("agent-1", "AAA")] = {
        "quantity": 100, "avg_cost": 50.0, "last_price": 55.0,
    }

    row = brk.mark_to_market(AGENT, SESSION)

    assert "AAA" in row["positions"]["stale_marks"]
    assert row["nav"] == pytest.approx(50_000 + 100 * 55.0)


# ── position_effect ─────────────────────────────────────────────────────────
# `side` alone is ambiguous once agents can short: a sell either closes a long
# or OPENS a short. The two flips are the reason this is recorded rather than
# inferred — they produce a row indistinguishable from a plain close.

import pytest

from services.arena.broker import _position_effect


@pytest.mark.parametrize("held,signed,resulting,expected", [
    (0,    10,  10,  "open_long"),      # flat -> long
    (0,   -10, -10,  "open_short"),     # flat -> short
    (10,    5,  15,  "open_long"),      # adding to a long
    (10,   -4,   6,  "close_long"),     # partial close
    (10,  -10,   0,  "close_long"),     # full close
    (10,  -15,  -5,  "flip_to_short"),  # sold THROUGH zero
    (-10,  -5, -15,  "open_short"),     # adding to a short
    (-10,   4,  -6,  "cover_short"),    # partial cover
    (-10,  10,   0,  "cover_short"),    # full cover
    (-10,  15,   5,  "flip_to_long"),   # bought THROUGH zero
])
def test_position_effect_names_what_the_fill_did(held, signed, resulting, expected):
    assert _position_effect(held, signed, resulting) == expected


def test_a_flip_is_not_reported_as_a_plain_close():
    # The case the UI could not have recovered from side + realized_pnl: both
    # of these are a SELL that closes a long and sets realized_pnl.
    assert _position_effect(10, -10, 0) == "close_long"
    assert _position_effect(10, -15, -5) == "flip_to_short"
