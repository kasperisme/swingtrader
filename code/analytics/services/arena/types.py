"""
Value types shared across the arena.

Deliberately dumb: these carry data between the LLM half and the deterministic
half without either side reaching into the other's tables.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Optional


# ── The competitors ──────────────────────────────────────────────────────────


_SHORTING_ALLOWED = """
## Selling short

You may go SHORT. `place_order` with side='sell' on a name you do not own opens
a short position; buying it back closes it. This is not a hedge you bolt on at
the end — it is the other half of every opinion you already form. When your
research says a price has run past what the evidence supports, that is a trade,
not just a name you decline to buy.

The mechanics, which differ from a long in ways that matter:

- A short sale CREDITS cash; covering spends it. So a short does not need cash
  up front, but it is not free — see exposure below.
- Exposure is measured GROSS: longs plus the absolute value of shorts, against
  your gross-exposure cap. A book that is already fully invested long has no
  room to short, and the order will be rejected. Sell something first.
- Your per-position cap applies to a short exactly as to a long.
- A long can lose 100%. A short's loss has NO upper bound — the position grows
  against you as it moves, so a short that halves your money has not stopped
  getting worse. Size shorts SMALLER than a long you believe equally strongly.
- You trade once a day and cannot leave a resting stop. A short that gaps
  against you overnight is not something you can manage in the morning; it is
  something you must have sized for the night before.

Two failure modes to avoid. Do not short something merely because it has gone
up — that is the crowded, expensive side of a trend and being early is
indistinguishable from being wrong. And do not short to look balanced; a short
you cannot state a thesis for is worse than no position, because it costs
exposure you could have spent on a conviction you actually have.
""".strip()

_SHORTING_FORBIDDEN = """
## Selling short

You are LONG ONLY. `place_order` with side='sell' closes a position you hold; it
cannot open a short, and an order that would take a holding below zero is
rejected. When your research says something is over-priced, the trade available
to you is to not own it, or to sell what you do own — say so in your reasoning
rather than reaching for a position you cannot take.
""".strip()


@dataclass(frozen=True)
class AgentSpec:
    """A competitor's definition, as declared in ``roster.py``.

    This is the source of truth for prompt + tool access + risk limits; the
    ``arena_agents`` row is a projection of it (``cli.py sync-roster`` writes
    the projection). Editing the spec and re-syncing changes how the agent
    behaves tomorrow — it never rewrites what it already did.
    """

    slug: str
    name: str
    tagline: str
    approach: str

    #: The real investor whose publicly-known approach this agent implements.
    #: The names are affectionate parodies; nothing here implies affiliation or
    #: endorsement, and the page says whose style it is rather than leaving the
    #: pun to carry the meaning on its own.
    inspiration: str = ""

    #: 'llm' runs the tool loop; 'deterministic' runs a pure-Python control.
    engine: str = "llm"

    #: Which internal RAG / FMP tools this agent may call. The whole point of
    #: the experiment is that these differ — an agent that can see everything
    #: is not testing an approach, it is testing the model.
    tools: tuple[str, ...] = ()

    #: Give the agent the FMP MCP tool set on top of ``tools``. Expensive
    #: (28 schemas in the context) so it is opt-in per agent.
    include_fmp: bool = False

    system_prompt: str = ""

    # Risk limits — enforced by the broker, restated in the prompt.
    starting_cash: float = 100_000.0
    max_position_pct: float = 0.20
    #: 0 = no position-count cap; the weight and gross-exposure caps still apply.
    max_positions: int = 10
    max_gross_exposure_pct: float = 1.00
    allow_shorts: bool = False

    #: The exposure band this strategy is expected to run at, as a fraction of
    #: NAV. NOT enforced by the broker — an agent that sees nothing worth owning
    #: must still be able to sit in cash. It is stated in the prompt so that
    #: sitting far below it becomes a decision the agent has to justify rather
    #: than the default it drifts into.
    #:
    #: The first replay made the cost of omitting this obvious: the reasoning
    #: agents ran at 0-19% invested while the buy-and-hold control ran at 97%,
    #: so they were competing on a tenth of their capital and lost on exposure
    #: rather than on stock selection — which measures nothing.
    target_exposure: tuple[float, float] = (0.50, 0.95)
    max_tool_rounds: int = 20

    sort_order: int = 0
    is_published: bool = True

    def __post_init__(self) -> None:
        """Append the truthful shorting section to the prompt.

        Kept here rather than written into each persona because it is MECHANICS,
        and mechanics that differ between agents stop the agents being
        comparable. More importantly it is derived from ``allow_shorts`` rather
        than restated beside it: an agent whose flag says one thing and whose
        prompt says another will either never use a capability it has, or spend
        rounds placing orders the broker rejects. Both happened before this
        existed — the broker has supported shorting throughout and no prompt
        mentioned it, so six of the seven LLM agents ran long-only by ignorance
        rather than by strategy.

        Deterministic controls get nothing: they have no prompt to read.
        """
        if self.engine != "llm" or not self.system_prompt:
            return
        block = _SHORTING_ALLOWED if self.allow_shorts else _SHORTING_FORBIDDEN
        # frozen=True, so the field is set the way frozen dataclasses set fields.
        object.__setattr__(self, "system_prompt", f"{self.system_prompt}\n\n{block}")


# ── What an agent asks for ───────────────────────────────────────────────────


@dataclass
class OrderIntent:
    """A request to trade. Not a fill — the broker decides that."""

    ticker: str
    side: str  # 'buy' | 'sell'
    quantity: float
    thesis: str = ""
    conviction: Optional[float] = None
    stop_price: Optional[float] = None
    target_price: Optional[float] = None

    def normalized(self) -> "OrderIntent":
        return OrderIntent(
            ticker=(self.ticker or "").upper().strip(),
            side=(self.side or "").lower().strip(),
            quantity=float(self.quantity or 0),
            thesis=(self.thesis or "").strip()[:2000],
            conviction=self.conviction,
            stop_price=self.stop_price,
            target_price=self.target_price,
        )


# ── The book ─────────────────────────────────────────────────────────────────


@dataclass
class PositionRow:
    ticker: str
    quantity: float  # signed: > 0 long, < 0 short
    avg_cost: float
    last_price: Optional[float] = None
    opened_at: Optional[datetime] = None

    @property
    def is_short(self) -> bool:
        return self.quantity < 0

    @property
    def mark(self) -> float:
        return float(self.last_price if self.last_price else self.avg_cost)

    @property
    def market_value(self) -> float:
        """Signed. Negative for shorts — a short is a liability."""
        return self.quantity * self.mark

    @property
    def unrealized_pnl(self) -> float:
        return self.quantity * (self.mark - self.avg_cost)

    @property
    def unrealized_pct(self) -> Optional[float]:
        if not self.avg_cost:
            return None
        sign = 1.0 if self.quantity > 0 else -1.0
        return sign * (self.mark - self.avg_cost) / self.avg_cost


@dataclass
class PortfolioSnapshot:
    """A marked book at a point in time."""

    agent_id: str
    slug: str
    cash: float
    positions: list[PositionRow] = field(default_factory=list)
    as_of: Optional[date] = None

    @property
    def long_value(self) -> float:
        return sum(p.market_value for p in self.positions if p.quantity > 0)

    @property
    def short_value(self) -> float:
        """Positive magnitude of short exposure."""
        return -sum(p.market_value for p in self.positions if p.quantity < 0)

    @property
    def nav(self) -> float:
        """Cash plus the signed value of the book.

        Short proceeds are credited to cash at the fill, so subtracting the
        (negative) market value here is what makes a short that moves against
        the agent actually cost it NAV.
        """
        return self.cash + sum(p.market_value for p in self.positions)

    @property
    def gross_exposure(self) -> float:
        return sum(abs(p.market_value) for p in self.positions)

    def position(self, ticker: str) -> Optional[PositionRow]:
        t = ticker.upper().strip()
        return next((p for p in self.positions if p.ticker == t), None)

    def to_public_dict(self) -> dict[str, Any]:
        """The shape an agent's own ``get_my_portfolio`` tool returns."""
        nav = self.nav
        return {
            "as_of": self.as_of.isoformat() if self.as_of else None,
            "nav": round(nav, 2),
            "cash": round(self.cash, 2),
            "invested": round(self.gross_exposure, 2),
            "cash_pct_of_nav": round(self.cash / nav, 4) if nav else None,
            "n_positions": len(self.positions),
            "positions": [
                {
                    "ticker": p.ticker,
                    "quantity": round(p.quantity, 4),
                    "direction": "short" if p.is_short else "long",
                    "avg_cost": round(p.avg_cost, 4),
                    "last_price": round(p.mark, 4),
                    "market_value": round(p.market_value, 2),
                    "unrealized_pnl": round(p.unrealized_pnl, 2),
                    "unrealized_pct": (
                        round(p.unrealized_pct, 4) if p.unrealized_pct is not None else None
                    ),
                    "pct_of_nav": round(abs(p.market_value) / nav, 4) if nav else None,
                    "held_since": p.opened_at.date().isoformat() if p.opened_at else None,
                }
                for p in sorted(
                    self.positions, key=lambda x: abs(x.market_value), reverse=True
                )
            ],
        }
