"""
Arena — competing AI paper-trading agents.

A fixed set of agents, each funded with the same starting cash and each
restricted to a DIFFERENT slice of the platform's data, trading against each
other on a daily clock. The comparison is the product: which way of reading
this data actually produces a tradeable edge, published including the losses.

Layering — the important part:

    roster.py     WHO competes: one AgentSpec per approach (prompt, tools, risk)
    decide.py     the LLM half: tool loop -> order INTENTS, nothing else
    controls.py   the non-LLM half: index / coinflip baselines
        │
        ▼  (an intent is only ever a request)
    broker.py     the deterministic half: validates, fills, marks, books P&L
    store.py      persistence for both halves
    marks.py      prices (session opens for fills, closes for marks)

An LLM's only write is an order intent. Cash, positions, fills and NAV are
computed by ``broker.py`` from the tables — a model cannot mark its own book,
spend cash it does not have, or revise a fill once the outcome is known
(the database enforces that last one too, in a trigger).

Three daily passes, each idempotent per (agent, date):

    fill    after the open   — pending orders fill at the session open + slippage
    mark    after the close  — positions marked to close, NAV row appended
    decide  after the close  — each agent decides for the NEXT session
"""

from .types import AgentSpec, OrderIntent, PortfolioSnapshot, PositionRow
from .broker import Broker, OrderRejected

__all__ = [
    "AgentSpec",
    "OrderIntent",
    "PortfolioSnapshot",
    "PositionRow",
    "Broker",
    "OrderRejected",
]
