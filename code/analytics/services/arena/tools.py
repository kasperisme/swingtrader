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

    # -- reads ---------------------------------------------------------------

    def get_my_portfolio(self) -> dict[str, Any]:
        """Current cash, positions, NAV and the agent's own risk limits."""
        snap = self.portfolio.to_public_dict()
        snap["limits"] = {
            "max_position_pct_of_nav": float(self.agent.get("max_position_pct") or 0.20),
            "max_positions": int(self.agent.get("max_positions") or 10),
            "max_gross_exposure_pct": float(self.agent.get("max_gross_exposure_pct") or 1.0),
            "shorting_allowed": bool(self.agent.get("allow_shorts")),
        }
        snap["starting_cash"] = float(self.agent.get("starting_cash") or 100_000)
        nav = self.portfolio.nav
        snap["total_return_pct"] = (
            round(nav / snap["starting_cash"] - 1.0, 4) if snap["starting_cash"] else None
        )
        return snap

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
            return {
                "ok": False,
                "status": "rejected",
                "error": row.get("reject_reason"),
                "hint": "Adjust size or pick a different name, then try again.",
                "portfolio": self.get_my_portfolio(),
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


ACCOUNT_TOOL_SCHEMAS: list[dict] = [
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
        "place_order": account.place_order,
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

    res = (
        _tbl("market_screening_results")
        .select("id,run_at,triggered,summary")
        .eq("market_screening_id", screening["id"])
        # The screening runner writes 'done' on success (services/market_screenings
        # /runner.py) — NOT 'ok'. Filtering on 'ok' silently returns an empty
        # board for every screening, which reads to an agent as "no setups today"
        # rather than as a bug, and costs it the whole day.
        .eq("status", "done")
        .eq("is_test", False)
        .order("run_at", desc=True)
        .limit(1)
        .execute()
    )
    if not res.data:
        return {"screening": screening["name"], "slug": slug, "rows": [], "note": "no completed run yet"}
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

    today = datetime.now(timezone.utc).date()
    window_start = today - timedelta(days=days)
    prior_start = window_start - timedelta(days=prior_days)

    sql = """
        WITH rows AS (
            SELECT ticker, bucket_day, mention_count, weighted_sentiment
            FROM swingtrader.news_trends_ticker_daily_v
            WHERE bucket_day >= %(prior_start)s
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
