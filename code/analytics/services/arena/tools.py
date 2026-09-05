"""
The tools an arena agent can call.

Three groups:

  1. **Account tools** (``get_my_portfolio``, ``get_my_recent_trades``) — an
     agent can see its own book and its own history, including its rejections.
     Reading another agent's book is not possible: the agent_id is bound in
     Python at registry-build time and is not a tool argument.

  2. **The write tool** (``place_order``) — the ONLY write an LLM gets. It
     records an intent; the broker decides whether it is legal and what it fills
     at. A rejection comes straight back to the model as the tool result, so the
     agent can correct itself inside the same run rather than losing the day.

  3. **Strategy data tools** — the arena-specific reads that don't exist in the
     shared RAG set: the public screening results, the pair z-scores and the
     ticker trend acceleration. Each agent's spec picks which of these (and
     which shared RAG tools) it may see; that difference IS the experiment.

The binding classes here follow the ``_BindUserAndAllowedRuns`` precedent in
``services/agent_core/market_tools.py``: bind the identity in Python, return a
structured ``{"ok": False, "error": …}`` on bad input rather than raising, so a
malformed tool call teaches the model instead of killing the loop.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Optional

from shared.db import get_supabase_client

from . import store
from .broker import Broker
from .types import OrderIntent, PortfolioSnapshot

log = logging.getLogger(__name__)

_SCHEMA = "swingtrader"


def _tbl(name: str):
    return get_supabase_client().schema(_SCHEMA).table(name)


# ── Point-in-time clock ──────────────────────────────────────────────────────
# When a replay sets this, every source that CAN be rewound is bounded by it, so
# an agent replaying 2 July reads the screening board that existed on 2 July
# rather than the newest one.
#
# It is deliberately narrow. Only the screening boards carry true run history
# (`market_screening_results.run_at`); the news scores were largely backfilled,
# the priced-in rows are all `generation_is_pit = false`, and `ticker_pair_stats`
# holds only a current z-score. Those remain look-ahead in a replay, and the
# tool docstrings say so rather than implying a rewind that is not happening.

_AS_OF: Optional[date] = None


def set_as_of(as_of: Optional[date]) -> None:
    """Bound the rewindable sources to ``as_of``. None restores live behaviour."""
    global _AS_OF
    _AS_OF = as_of


def as_of() -> Optional[date]:
    return _AS_OF


#: Shared RAG tools that accept an ``as_of`` and honour it. The arena injects the
#: replayed session; the model never sees the parameter and cannot set it.
AS_OF_AWARE_TOOLS = (
    "get_top_articles",
    "get_ticker_sentiment",
    "get_ticker_news",
    "search_news",
)

#: Tools that CANNOT be bounded to a past session, and what leaks as a result.
#: Listed explicitly so a replay's residual look-ahead is a documented fact
#: rather than something a reader has to infer from silence.
UNBOUNDED_IN_REPLAY = {
    "get_news_by_tag": "tag search RPC anchors its window at now() server-side",
    "get_cluster_trends": "aggregate view anchored at now()",
    "get_dimension_trends": "aggregate view anchored at now()",
    "get_ticker_relationships": "the graph is refreshed in place; no as-of version exists",
    "get_company_vectors": "one snapshot per ticker, not a time series",
    "get_priced_in": "every row is generation_is_pit = false",
    "get_priced_in_drivers": "every row is generation_is_pit = false",
    "get_priced_in_case": "every row is generation_is_pit = false",
    "search_priced_in_drivers": "every row is generation_is_pit = false",
    "get_pair_signals": "ticker_pair_stats holds only a current z-score, no history",
}


#: The priced-in surfaces. Every row they return carries a ``price`` field that
#: is the price the RECONSTRUCTION was built against, not the price today — and
#: in a replay it is a price from the future. See ``_RepriceToSession``.
PRICED_IN_TOOLS = (
    "get_priced_in",
    "get_priced_in_drivers",
    "get_priced_in_case",
    "search_priced_in_drivers",
)


class _RepriceToSession:
    """Re-anchor a priced-in payload to the price on the session being traded.

    The priced-in strategy is one comparison: today's price against what the
    drivers and the published targets justify. Both halves have to be measured
    on the same day for that subtraction to mean anything, and until now they
    were not:

      * every ``research_priced_in`` row is ``generation_is_pit = false``, so a
        replay of 2 July read the row generated on 4 September;
      * even live, a row is served until it is 45 days old, so its ``price``
        can be a month and a half stale.

    Measured on the arena's own record, the agent trading this surface believed
    CEG was $285.05 on 2 July when it was $238.10 — a 19.7% error on the one
    input the whole strategy subtracts. Across its fourteen buys the mean
    absolute error was 7.2% against gaps of about 20%: the noise and the signal
    were the same size.

    So the price is replaced with the session's actual close, ``median_gap`` is
    recomputed from it, and the original is kept beside it under
    ``reconstruction_price`` rather than dropped. Nothing about the judged tier
    is repaired by this — ``priced_in_pct`` still comes from a model that ran on
    a later date, and ``look_ahead`` continues to say so. This fixes the
    arithmetic, which is the half that CAN be fixed deterministically.
    """

    __slots__ = ("fn", "price_of")

    def __init__(self, fn: Callable[..., Any], price_of: Callable[[str], Optional[float]]) -> None:
        self.fn = fn
        self.price_of = price_of

    def __call__(self, **kwargs: Any) -> Any:
        result = self.fn(**kwargs)
        if isinstance(result, list):
            for row in result:
                if isinstance(row, dict):
                    self._reprice(row)
        elif isinstance(result, dict):
            self._reprice(result)
        return result

    def _reprice(self, row: dict[str, Any]) -> None:
        ticker = str(row.get("ticker") or "").upper()
        if not ticker or "price" not in row:
            return
        try:
            live = self.price_of(ticker)
        except Exception as exc:                               # noqa: BLE001
            log.debug("arena: reprice lookup failed for %s: %s", ticker, exc)
            return
        if not live or live <= 0:
            # No bar for this name on this session. Leaving the reconstruction
            # price in place silently is exactly the bug, so say it instead.
            row["price_note"] = (
                "No price for this ticker on the session being traded; `price` is "
                "the price the reconstruction was built against and may be stale."
            )
            return

        original = row.get("price")
        row["price"] = round(live, 4)
        row["reconstruction_price"] = original
        row["price_note"] = (
            f"`price` is the close on the session you are trading. The "
            f"reconstruction was built against {original}, so its driver "
            f"percentages describe THAT price. Judge the gap on `price`."
        )

        vote = row.get("vote")
        if isinstance(vote, dict):
            median = vote.get("target_median")
            try:
                median = float(median) if median is not None else None
            except (TypeError, ValueError):
                median = None
            if median:
                vote["median_gap_reconstruction"] = vote.get("median_gap")
                vote["median_gap"] = round(live / median - 1.0, 6)
                # The percentile was computed from the stale gap and is now
                # describing a number that is no longer there.
                try:
                    from services.rag.priced_in import gap_context

                    ctx = gap_context(vote["median_gap"])
                    if ctx is not None:
                        vote["median_gap_context"] = ctx
                except Exception:                              # noqa: BLE001
                    vote.pop("median_gap_context", None)


class _BindAsOf:
    """Inject the replayed session into a tool that accepts one.

    The parameter is absent from the schema the model sees, so an agent can
    neither set nor widen its own clock.
    """

    __slots__ = ("fn",)

    def __init__(self, fn: Callable[..., Any]) -> None:
        self.fn = fn

    def __call__(self, **kwargs: Any) -> Any:
        current = as_of()
        if current is not None:
            kwargs["as_of"] = current
        return self.fn(**kwargs)


# ── 1 + 2: the account-bound tools ───────────────────────────────────────────


class AccountTools:
    """Portfolio reads and the order write, bound to one agent and one session.

    Holds the live ``PortfolioSnapshot`` for the run so each ``place_order``
    call is validated against the book as the previous calls left it — an agent
    that queues five orders cannot spend the same cash five times.
    """

    def __init__(
        self,
        agent: dict[str, Any],
        *,
        broker: Broker,
        portfolio: PortfolioSnapshot,
        decision_id: Optional[str],
        intended_for: date,
        reference_prices: dict[str, float],
        as_of: date,
    ) -> None:
        self.agent = agent
        self.broker = broker
        self.portfolio = portfolio
        self.decision_id = decision_id
        self.intended_for = intended_for
        self.reference_prices = reference_prices
        self.as_of = as_of
        self.accepted: list[dict[str, Any]] = []
        self.rejected: list[dict[str, Any]] = []
        self.finished = False
        self.summary = ""

    # -- reads ---------------------------------------------------------------

    def get_my_portfolio(self) -> dict[str, Any]:
        """Current cash, positions, NAV and the agent's own risk limits."""
        from .broker import CASH_BUFFER

        snap = self.portfolio.to_public_dict()

        # SPENDABLE cash, not raw cash. The broker reserves a slice against gap
        # risk, so an agent sizing against `cash` overshoots by exactly that
        # margin and gets rejected — every time, having spent a round on it.
        # Publishing the number it is actually judged against removes a
        # subtraction the agent was never told to make.
        raw_max = self.agent.get("max_positions")
        max_positions = 10 if raw_max is None else int(raw_max)
        snap["available_cash"] = round(self.portfolio.cash * (1 - CASH_BUFFER), 2)
        snap["cash_reserved_pct"] = CASH_BUFFER
        snap["limits"] = {
            "max_position_pct_of_nav": float(self.agent.get("max_position_pct") or 0.20),
            # 0 means no cap; reporting the fallback here while the broker
            # enforces none is how an agent learns a limit that is not real.
            "max_positions": max_positions if max_positions > 0 else None,
            "max_gross_exposure_pct": float(self.agent.get("max_gross_exposure_pct") or 1.0),
            "shorting_allowed": bool(self.agent.get("allow_shorts")),
        }
        snap["starting_cash"] = float(self.agent.get("starting_cash") or 100_000)
        nav = self.portfolio.nav
        snap["total_return_pct"] = (
            round(nav / snap["starting_cash"] - 1.0, 4) if snap["starting_cash"] else None
        )
        return snap

    def get_quote(self, tickers: Any = None) -> dict[str, Any]:
        """Closing price on the session being traded, for any ticker.

        Added because several agents had no way to see the price of a name they
        did not already own. `get_my_portfolio` marks open positions only, and
        the daily prompt carries NAV and cash but no quotes — so an agent
        researching a candidate was reasoning about cheapness with no price in
        front of it, and took whatever price its research tool happened to
        carry. For the priced-in agent that was a price from a later date.
        """
        syms = tickers if isinstance(tickers, (list, tuple)) else [tickers]
        syms = list(dict.fromkeys(
            str(t or "").upper().strip() for t in syms if str(t or "").strip()
        ))[:25]
        if not syms:
            return {"ok": False, "error": "pass one or more tickers"}

        out: dict[str, Any] = {}
        missing: list[str] = []
        for sym in syms:
            price = self.reference_prices.get(sym)
            if price is None:
                price = self._warm(sym)
            if price:
                out[sym] = round(float(price), 4)
            else:
                missing.append(sym)
        return {
            "ok": True,
            "as_of": self.as_of.isoformat(),
            "prices": out,
            "no_price": missing,
            "note": (
                f"Closes on {self.as_of.isoformat()}. An order you place fills at "
                f"the OPEN on {self.intended_for.isoformat()}, so treat these as "
                f"a reference, not a fill price."
            ),
        }

    def get_my_recent_trades(self, limit: int = 20) -> dict[str, Any]:
        """The agent's own recent orders — fills AND rejections.

        Rejections are included deliberately: an agent that keeps asking for
        more than its position cap should be able to see that it keeps asking.
        """
        try:
            limit = max(1, min(int(limit), 50))
        except (TypeError, ValueError):
            limit = 20
        rows = store.list_recent_orders(self.agent["id"], limit=limit)
        return {
            "orders": [
                {
                    "ticker": r["ticker"],
                    "side": r["side"],
                    "quantity": float(r["quantity"]),
                    "status": r["status"],
                    "fill_price": float(r["fill_price"]) if r.get("fill_price") else None,
                    "submitted_at": r.get("submitted_at"),
                    "realized_pnl": (
                        float(r["realized_pnl"]) if r.get("realized_pnl") is not None else None
                    ),
                    "reject_reason": r.get("reject_reason"),
                    "thesis": (r.get("thesis") or "")[:300] or None,
                }
                for r in rows
            ]
        }

    # -- the write -----------------------------------------------------------

    def finish_session(self, summary: str = "") -> dict[str, Any]:
        """End the session deliberately, handing back the published summary."""
        text = str(summary or "").strip()
        if len(text) < 40:
            # Refusing a stub keeps the exit from becoming a way to skip the
            # write-up; the model can call again with a real one.
            return {
                "ok": False,
                "error": "summary is too short — write 3-6 sentences a reader can follow",
            }
        self.finished = True
        self.summary = text
        return {
            "ok": True,
            "status": "session closed",
            "orders_placed": len(self.accepted),
            "orders_rejected": len(self.rejected),
        }

    def place_order(
        self,
        ticker: str = "",
        side: str = "",
        quantity: Any = 0,
        thesis: str = "",
        conviction: Any = None,
        stop_price: Any = None,
        target_price: Any = None,
    ) -> dict[str, Any]:
        """Queue a market order for the next session's open."""
        try:
            qty = float(quantity)
        except (TypeError, ValueError):
            return {"ok": False, "error": f"quantity must be a number, got {quantity!r}"}

        intent = OrderIntent(
            ticker=str(ticker or ""),
            side=str(side or ""),
            quantity=qty,
            thesis=str(thesis or ""),
            conviction=_opt_float(conviction),
            stop_price=_opt_float(stop_price),
            target_price=_opt_float(target_price),
        ).normalized()

        if not intent.thesis:
            return {
                "ok": False,
                "error": "thesis is required — state the evidence for this trade in one or two sentences",
            }

        reference = self.reference_prices.get(intent.ticker)
        if reference is None and intent.ticker:
            # Not pre-warmed (the agent found a name outside the candidate set).
            # Fetch it on demand rather than rejecting for a cache miss.
            reference = self._warm(intent.ticker)

        row = self.broker.submit(
            self.agent,
            intent,
            portfolio=self.portfolio,
            decision_id=self.decision_id,
            intended_for=self.intended_for,
            reference_price=reference,
        )

        if row.get("status") == "rejected":
            self.rejected.append(row)
            # Say what it CAN do, not just what it cannot. A bare "adjust size"
            # makes the agent guess a smaller number and often get rejected
            # again; the affordable quantity is arithmetic we already have.
            snap = self.get_my_portfolio()
            hint = "Adjust size or pick a different name, then try again."
            price = reference or self.reference_prices.get(intent.ticker)
            if price and price > 0:
                by_cash = int(snap["available_cash"] // price)
                by_weight = int(
                    (self.portfolio.nav * float(snap["limits"]["max_position_pct_of_nav"]))
                    // price
                )
                affordable = max(0, min(by_cash, by_weight))
                hint = (
                    f"At ~${price:,.2f} you can buy up to {affordable} shares of "
                    f"{intent.ticker} right now ({by_cash} on available cash, "
                    f"{by_weight} on the per-position weight cap). Re-order at or "
                    f"below that, or sell something first."
                ) if affordable > 0 else (
                    f"You cannot open {intent.ticker} at ~${price:,.2f} with "
                    f"${snap['available_cash']:,.0f} available. Sell something first."
                )
            return {
                "ok": False,
                "status": "rejected",
                "error": row.get("reject_reason"),
                "hint": hint,
                "portfolio": snap,
            }

        self.accepted.append(row)
        return {
            "ok": True,
            "status": "queued",
            "ticker": intent.ticker,
            "side": intent.side,
            "quantity": intent.quantity,
            "estimated_price": round(reference, 4) if reference else None,
            "estimated_notional": round(intent.quantity * reference, 2) if reference else None,
            "fills_at": f"the open on {self.intended_for.isoformat()} (market order, ~5bp slippage)",
            "cash_remaining_after": round(self.portfolio.cash, 2),
        }

    def price_on_session(self, ticker: str) -> Optional[float]:
        """Close for ``ticker`` on the session being traded, cached per run.

        The lookup ``_RepriceToSession`` uses. Same source and same cache the
        order path prices against, so an agent cannot be shown one price and
        filled against a different one.
        """
        sym = str(ticker or "").upper().strip()
        if not sym:
            return None
        price = self.reference_prices.get(sym)
        return price if price is not None else self._warm(sym)

    def _warm(self, ticker: str) -> Optional[float]:
        self.broker.prices.load([ticker], self.as_of - timedelta(days=30), self.as_of)
        price, _ = self.broker.prices.last_close_on_or_before(ticker, self.as_of)
        if price:
            self.reference_prices[ticker] = price
        return price


def _opt_float(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


#: Calling this ends the agent's turn. Passed to run_tool_loop as a stop tool.
FINISH_TOOL = "finish_session"

ACCOUNT_TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": FINISH_TOOL,
            "description": (
                "END your session. Call this as soon as you have done what today "
                "needs — whether that was placing orders or deciding not to. "
                "Everything after it is discarded, so do not call it until your "
                "orders are in. You are NOT rewarded for using every round; a "
                "session that finishes in five rounds with one good trade beats "
                "one that spends twenty rounds researching and never acts."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": (
                            "REQUIRED. 3-6 sentences, published on the site under "
                            "your name: what you saw, what you did about it, and "
                            "what would change your mind. Plain English, no "
                            "markdown, for a reader who cannot see your tool calls."
                        ),
                    }
                },
                "required": ["summary"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_my_portfolio",
            "description": (
                "Your current book: cash, every open position with its cost basis and "
                "unrealised P&L, total NAV, and the risk limits you are held to. "
                "Call this FIRST, before deciding anything."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_quote",
            "description": (
                "The closing price of any ticker on the session you are trading. "
                "Use it before you reason about whether something is cheap or "
                "expensive: prices quoted inside research tools are the price that "
                "research was BUILT against, which can be days or months away from "
                "the price you would actually pay."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "tickers": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Up to 25 US equity symbols, e.g. [\"CEG\", \"GEV\"]",
                    }
                },
                "required": ["tickers"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_my_recent_trades",
            "description": (
                "Your own recent orders, including ones that were REJECTED and why. "
                "Use it to avoid repeating an order that broke a risk limit, and to "
                "see how your past theses actually resolved."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "How many orders (max 50)", "default": 20}
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "place_order",
            "description": (
                "Queue a market order to be filled at the NEXT session's open. This is "
                "the only way you can trade. Buying spends cash; selling a position you "
                "hold closes it. The order is checked against your risk limits and your "
                "available cash — if it is rejected you get the reason back and can retry "
                "with a smaller size or a different name."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string", "description": "US equity symbol, e.g. NVDA"},
                    "side": {"type": "string", "enum": ["buy", "sell"]},
                    "quantity": {"type": "number", "description": "Number of shares (whole shares)"},
                    "thesis": {
                        "type": "string",
                        "description": (
                            "REQUIRED. One or two sentences: the specific evidence from your "
                            "tools that justifies this trade. Cite what you actually saw."
                        ),
                    },
                    "conviction": {
                        "type": "number",
                        "description": "0-1, how strongly you believe this. Optional.",
                    },
                    "stop_price": {"type": "number", "description": "Where the thesis is wrong. Optional."},
                    "target_price": {"type": "number", "description": "Where you would take profit. Optional."},
                },
                "required": ["ticker", "side", "quantity", "thesis"],
            },
        },
    },
]


def build_account_registry(account: AccountTools):
    """Registry of the three account-bound tools for one agent."""
    from services.agent_core import Tool, ToolRegistry

    fns: dict[str, Callable[..., Any]] = {
        "get_my_portfolio": lambda **kw: account.get_my_portfolio(),
        "get_my_recent_trades": account.get_my_recent_trades,
        "get_quote": account.get_quote,
        "place_order": account.place_order,
        FINISH_TOOL: account.finish_session,
    }
    registry = ToolRegistry()
    for schema in ACCOUNT_TOOL_SCHEMAS:
        name = schema["function"]["name"]
        registry.add(Tool(name=name, schema=schema, fn=fns[name]))
    return registry


# ── 3: strategy data tools ───────────────────────────────────────────────────
# These read surfaces the shared RAG tool set doesn't expose. Each is a plain
# function with no agent binding — they are market-wide reads.


def get_screening_results(screening_slug: str = "nis-momentum", limit: int = 25) -> dict[str, Any]:
    """Latest published run of one of the platform's market screenings."""
    slug = (screening_slug or "nis-momentum").strip()
    try:
        limit = max(1, min(int(limit), 50))
    except (TypeError, ValueError):
        limit = 25

    scr = _tbl("market_screenings").select("id,slug,name,description").eq("slug", slug).limit(1).execute()
    if not scr.data:
        available = _tbl("market_screenings").select("slug").eq("is_active", True).execute()
        return {
            "error": f"no screening with slug {slug!r}",
            "available": sorted(r["slug"] for r in (available.data or [])),
        }
    screening = scr.data[0]

    q = (
        _tbl("market_screening_results")
        .select("id,run_at,triggered,summary")
        .eq("market_screening_id", screening["id"])
        # The screening runner writes 'done' on success (services/market_screenings
        # /runner.py) — NOT 'ok'. Filtering on 'ok' silently returns an empty
        # board for every screening, which reads to an agent as "no setups today"
        # rather than as a bug, and costs it the whole day.
        .eq("status", "done")
        .eq("is_test", False)
    )
    if _AS_OF is not None:
        # The most recent board that EXISTED at the close of the replayed
        # session. Boards run weekly, so this is usually a few days old — which
        # is exactly what a trader acting on that session would have had.
        q = q.lte("run_at", f"{_AS_OF.isoformat()}T23:59:59+00:00")
    res = q.order("run_at", desc=True).limit(1).execute()
    if not res.data:
        note = (
            f"no run of this screening existed on or before {_AS_OF.isoformat()}"
            if _AS_OF is not None
            else "no completed run yet"
        )
        return {"screening": screening["name"], "slug": slug, "rows": [], "note": note}
    result = res.data[0]

    rows = (
        _tbl("market_screening_result_rows")
        .select("symbol,row_data,scan_date")
        .eq("result_id", result["id"])
        .limit(limit)
        .execute()
        .data
        or []
    )
    return {
        "screening": screening["name"],
        "slug": slug,
        "description": screening.get("description"),
        "run_at": result.get("run_at"),
        "summary": (result.get("summary") or "")[:1500] or None,
        "count": len(rows),
        "rows": [
            {"symbol": r["symbol"], "scan_date": r.get("scan_date"), **_trim_row_data(r.get("row_data"))}
            for r in rows
        ],
    }


def _trim_row_data(row_data: Any) -> dict[str, Any]:
    """Keep the screening row's numeric/short fields; drop long prose blobs that
    would blow out the model's context for little signal."""
    if not isinstance(row_data, dict):
        return {}
    out: dict[str, Any] = {}
    for k, v in row_data.items():
        if k.startswith("__note_"):
            continue
        if isinstance(v, (int, float, bool)) or v is None:
            out[k] = v
        elif isinstance(v, str) and len(v) <= 120:
            out[k] = v
    return out


def list_screenings() -> dict[str, Any]:
    """Every active market screening, so an agent can pick which board to read."""
    rows = (
        _tbl("market_screenings")
        .select("slug,name,description,category,last_run_at")
        .eq("is_active", True)
        .eq("is_published", True)
        .execute()
        .data
        or []
    )
    return {"screenings": rows}


def get_pair_signals(min_abs_zscore: float = 2.0, limit: int = 20) -> dict[str, Any]:
    """Cointegrated pairs whose spread has stretched — the mean-reversion board.

    Only pairs that (a) share a news-derived economic relationship and (b) pass
    the Engle-Granger test are stored at all, so this is already the pruned set.
    """
    try:
        threshold = abs(float(min_abs_zscore))
    except (TypeError, ValueError):
        threshold = 2.0
    try:
        limit = max(1, min(int(limit), 50))
    except (TypeError, ValueError):
        limit = 20

    rows = (
        _tbl("ticker_pair_stats")
        .select(
            "ticker_a,ticker_b,hedge_ratio,coint_pvalue,half_life_days,"
            "current_zscore,current_price_a,current_price_b,zscore_at,is_cointegrated"
        )
        .eq("is_cointegrated", True)
        .not_.is_("current_zscore", "null")
        .execute()
        .data
        or []
    )
    hits = [r for r in rows if abs(float(r["current_zscore"] or 0)) >= threshold]
    hits.sort(key=lambda r: abs(float(r["current_zscore"] or 0)), reverse=True)
    trimmed = hits[:limit]
    return {
        "threshold": threshold,
        "count": len(trimmed),
        "note": (
            "z > 0 means A is rich vs B (short A / long B to fade); z < 0 means A is "
            "cheap vs B. half_life_days is how long the spread historically takes to "
            "close half the gap — a pair with a half-life longer than your holding "
            "period is not a trade."
        ),
        "pairs": [
            {
                "ticker_a": r["ticker_a"],
                "ticker_b": r["ticker_b"],
                "zscore": round(float(r["current_zscore"]), 3),
                "hedge_ratio": _round(r.get("hedge_ratio"), 4),
                "coint_pvalue": _round(r.get("coint_pvalue"), 4),
                "half_life_days": _round(r.get("half_life_days"), 1),
                "price_a": _round(r.get("current_price_a"), 2),
                "price_b": _round(r.get("current_price_b"), 2),
                "as_of": r.get("zscore_at"),
            }
            for r in trimmed
        ],
    }


def get_trending_tickers(days: int = 5, prior_days: int = 15, limit: int = 25) -> dict[str, Any]:
    """Tickers whose news coverage is ACCELERATING, with the sentiment behind it.

    Compares mention volume in the last ``days`` against the daily average over
    the preceding ``prior_days``. Raw volume just returns the mega-caps every
    day; the ratio is what surfaces a name the tape has only just found.

    The aggregation runs in Postgres rather than in Python. Pulling every daily
    ticker row back over PostgREST and summing it here took long enough to trip
    the statement timeout — this returns tens of rows instead of hundreds of
    thousands.
    """
    try:
        days = max(1, min(int(days), 30))
        prior_days = max(days, min(int(prior_days), 90))
        limit = max(1, min(int(limit), 50))
    except (TypeError, ValueError):
        days, prior_days, limit = 5, 15, 25

    # Anchored on the replayed session when one is set, so the acceleration is
    # measured against the coverage that existed then rather than against now.
    today = _AS_OF or datetime.now(timezone.utc).date()
    window_start = today - timedelta(days=days)
    prior_start = window_start - timedelta(days=prior_days)

    sql = """
        WITH rows AS (
            SELECT ticker, bucket_day, mention_count, weighted_sentiment
            FROM swingtrader.news_trends_ticker_daily_v
            WHERE bucket_day >= %(prior_start)s
              AND bucket_day <= %(today)s
        ),
        agg AS (
            SELECT
                ticker,
                SUM(mention_count) FILTER (WHERE bucket_day >= %(window_start)s) AS recent,
                SUM(mention_count) FILTER (WHERE bucket_day <  %(window_start)s) AS prior,
                AVG(weighted_sentiment) FILTER (WHERE bucket_day >= %(window_start)s) AS sentiment
            FROM rows
            GROUP BY ticker
        )
        SELECT
            ticker,
            COALESCE(recent, 0)::int  AS recent,
            COALESCE(prior, 0)::int   AS prior,
            sentiment
        FROM agg
        WHERE COALESCE(recent, 0) >= 3
        -- +0.25/day baseline so a name with no prior coverage scores high but
        -- not infinitely: a single first article should not top the board.
        ORDER BY (COALESCE(recent, 0)::float / %(days)s)
               / ((COALESCE(prior, 0)::float / %(prior_days)s) + 0.25) DESC
        LIMIT %(limit)s
    """
    from shared.db import get_pg_connection

    conn = get_pg_connection()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                sql,
                {
                    "prior_start": prior_start,
                    "today": today,
                    "window_start": window_start,
                    "days": days,
                    "prior_days": prior_days,
                    "limit": limit,
                },
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    out = []
    for ticker, recent, prior, sentiment in rows:
        recent_daily = recent / days
        prior_daily = prior / prior_days
        out.append(
            {
                "ticker": ticker,
                "mentions_recent": recent,
                "mentions_per_day_recent": round(recent_daily, 2),
                "mentions_per_day_prior": round(prior_daily, 2),
                "acceleration": round(recent_daily / (prior_daily + 0.25), 2),
                "avg_weighted_sentiment": _round(sentiment, 3),
            }
        )

    return {
        "window_days": days,
        "prior_days": prior_days,
        "note": (
            "acceleration = recent mentions/day divided by the prior baseline. "
            ">2 means coverage has at least doubled. Pair it with sentiment: "
            "accelerating coverage with negative sentiment is a different trade."
        ),
        "tickers": out,
    }


def _round(v: Any, digits: int) -> Optional[float]:
    try:
        return round(float(v), digits)
    except (TypeError, ValueError):
        return None


STRATEGY_TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "get_screening_results",
            "description": (
                "The latest run of one of the platform's market screenings — the same "
                "boards published on the site. 'nis-momentum' is confirmed price+volume "
                "breakouts, 'nis-short' is breakdowns, 'nis-fundamentals' is quality "
                "screens. Returns the symbols that passed plus their screen metrics."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "screening_slug": {"type": "string", "description": "e.g. nis-momentum", "default": "nis-momentum"},
                    "limit": {"type": "integer", "default": 25},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_screenings",
            "description": "All available market screenings and what each one looks for.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_pair_signals",
            "description": (
                "Cointegrated ticker pairs whose spread has stretched away from its mean. "
                "Every pair here shares a verified economic relationship AND passes a "
                "cointegration test. Includes hedge ratio, z-score and mean-reversion "
                "half-life."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "min_abs_zscore": {"type": "number", "default": 2.0},
                    "limit": {"type": "integer", "default": 20},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_trending_tickers",
            "description": (
                "Tickers whose news coverage is accelerating, ranked by how much the "
                "last few days beat their own prior baseline, with the sentiment of that "
                "coverage. Surfaces names the tape has only just found."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "days": {"type": "integer", "description": "Recent window", "default": 5},
                    "prior_days": {"type": "integer", "description": "Baseline window", "default": 15},
                    "limit": {"type": "integer", "default": 25},
                },
            },
        },
    },
]

STRATEGY_TOOLS: dict[str, Callable[..., Any]] = {
    "get_screening_results": get_screening_results,
    "list_screenings": list_screenings,
    "get_pair_signals": get_pair_signals,
    "get_trending_tickers": get_trending_tickers,
}


def build_strategy_registry(allowed: tuple[str, ...]):
    """Registry of the arena-specific data tools named in ``allowed``."""
    from services.agent_core import Tool, ToolRegistry

    schemas = {s["function"]["name"]: s for s in STRATEGY_TOOL_SCHEMAS}
    registry = ToolRegistry()
    for name in allowed:
        if name in STRATEGY_TOOLS and name in schemas:
            registry.add(Tool(name=name, schema=schemas[name], fn=STRATEGY_TOOLS[name]))
    return registry
