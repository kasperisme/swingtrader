"""
Persistence for the arena tables.

Every write here goes through the service-role Supabase client, which bypasses
RLS — the runner is the only writer. Reads used by the public site go through
the ``arena_*_public_v`` views instead (see the Next.js server actions), so
nothing in this module needs to think about publication state.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from shared.db import get_supabase_client

from .types import PortfolioSnapshot, PositionRow

log = logging.getLogger(__name__)

_SCHEMA = "swingtrader"


# ── Replay stamping ──────────────────────────────────────────────────────────
# A historical replay writes through these same functions. Rather than thread an
# `is_backtest` argument down every call site (and risk one path forgetting it,
# which would silently publish simulated rows as live record), the replay sets a
# module-level stamp for the duration of the run and every insert picks it up.
#
# It is a process-global on purpose: the replay is single-threaded by
# construction (agents share one Ollama backend), and a stamp that could be set
# on one path and missed on another is the failure this is designed to prevent.

_BACKTEST_STAMP: dict[str, Any] = {}


def set_backtest_mode(run_id: Optional[str]) -> None:
    """Stamp every subsequent write as part of replay ``run_id``.

    Pass None to return to live mode. ``cli.py`` and ``backtest.py`` are the only
    callers; anything else writing live rows must never touch this.
    """
    global _BACKTEST_STAMP
    _BACKTEST_STAMP = (
        {"is_backtest": True, "backtest_run_id": run_id} if run_id else {}
    )


def is_backtest_mode() -> bool:
    return bool(_BACKTEST_STAMP)


# ── Championship scope ───────────────────────────────────────────────────────
# Every book, order, decision and NAV row belongs to exactly one championship.
# Like the replay stamp above, the active championship is set once per run
# rather than threaded through every signature — but unlike the stamp, a MISSING
# championship is an error rather than a default. Writing an unscoped row would
# put it in no championship at all, where the leaderboard cannot see it and no
# amount of later repair can tell which season it belonged to.

_ACTIVE_CHAMPIONSHIP: Optional[str] = None


def set_championship(championship_id: Optional[str]) -> None:
    global _ACTIVE_CHAMPIONSHIP
    _ACTIVE_CHAMPIONSHIP = championship_id


def active_championship() -> Optional[str]:
    return _ACTIVE_CHAMPIONSHIP


def _champ() -> str:
    if not _ACTIVE_CHAMPIONSHIP:
        raise RuntimeError(
            "no active championship — call store.set_championship(id) first. "
            "Every arena write must belong to a championship."
        )
    return _ACTIVE_CHAMPIONSHIP


def _scoped(row: dict[str, Any]) -> dict[str, Any]:
    """Stamp a row with the active championship and any replay marker."""
    return _stamped({**row, "championship_id": _champ()})


def _stamped(row: dict[str, Any]) -> dict[str, Any]:
    """Apply the replay stamp to a row destined for a stampable table."""
    return {**row, **_BACKTEST_STAMP} if _BACKTEST_STAMP else row


def _tbl(name: str):
    return get_supabase_client().schema(_SCHEMA).table(name)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Agents ───────────────────────────────────────────────────────────────────


def upsert_agent(spec_row: dict[str, Any]) -> dict[str, Any]:
    """Insert or update one agent row, keyed on slug.

    Only the *definition* columns are written. Anything the broker owns (cash,
    positions, history) is untouched, so re-syncing the roster after a prompt
    edit never resets a running experiment.
    """
    res = _tbl("arena_agents").upsert(spec_row, on_conflict="slug").execute()
    return (res.data or [{}])[0]


def get_agent(slug: str) -> Optional[dict[str, Any]]:
    res = _tbl("arena_agents").select("*").eq("slug", slug).limit(1).execute()
    return (res.data or [None])[0]


def list_agents(active_only: bool = True) -> list[dict[str, Any]]:
    q = _tbl("arena_agents").select("*")
    if active_only:
        q = q.eq("is_active", True)
    res = q.order("sort_order").order("slug").execute()
    return res.data or []


# ── Cash account ─────────────────────────────────────────────────────────────


def get_cash(agent_id: str) -> Optional[float]:
    res = (
        _tbl("arena_accounts")
        .select("cash")
        .eq("agent_id", agent_id)
        .eq("championship_id", _champ())
        .limit(1)
        .execute()
    )
    rows = res.data or []
    return float(rows[0]["cash"]) if rows else None


def set_cash(agent_id: str, cash: float) -> None:
    _tbl("arena_accounts").upsert(
        {
            "agent_id": agent_id,
            "championship_id": _champ(),
            "cash": round(float(cash), 2),
            "updated_at": _now(),
        },
        on_conflict="championship_id,agent_id",
    ).execute()


def open_account(agent_id: str, championship_id: str, starting_cash: float) -> None:
    """Fund an agent for one championship.

    Explicitly scoped rather than using the ambient championship, because this is
    called while STARTING one — the point at which the ambient value is not yet
    set. Idempotent: an agent already funded for this championship keeps its
    balance, so re-running `start` cannot reset a book mid-season.
    """
    existing = (
        _tbl("arena_accounts")
        .select("agent_id")
        .eq("agent_id", agent_id)
        .eq("championship_id", championship_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    if existing:
        return
    _tbl("arena_accounts").insert(
        {
            "agent_id": agent_id,
            "championship_id": championship_id,
            "cash": round(float(starting_cash), 2),
            "updated_at": _now(),
        }
    ).execute()


# ── Positions ────────────────────────────────────────────────────────────────


def list_positions(agent_id: str) -> list[PositionRow]:
    res = (
        _tbl("arena_positions")
        .select("*")
        .eq("agent_id", agent_id)
        .eq("championship_id", _champ())
        .execute()
    )
    out: list[PositionRow] = []
    for r in res.data or []:
        opened = r.get("opened_at")
        out.append(
            PositionRow(
                ticker=r["ticker"],
                quantity=float(r["quantity"]),
                avg_cost=float(r["avg_cost"]),
                last_price=float(r["last_price"]) if r.get("last_price") else None,
                opened_at=datetime.fromisoformat(opened.replace("Z", "+00:00"))
                if isinstance(opened, str)
                else opened,
            )
        )
    return out


def upsert_position(
    agent_id: str,
    ticker: str,
    *,
    quantity: float,
    avg_cost: float,
    last_price: Optional[float] = None,
) -> None:
    payload = {
        "agent_id": agent_id,
        "championship_id": _champ(),
        "ticker": ticker.upper().strip(),
        "quantity": round(float(quantity), 4),
        "avg_cost": round(float(avg_cost), 4),
        "updated_at": _now(),
    }
    if last_price is not None:
        payload["last_price"] = round(float(last_price), 4)
        payload["marked_at"] = _now()
    _tbl("arena_positions").upsert(
        payload, on_conflict="championship_id,agent_id,ticker"
    ).execute()


def delete_position(agent_id: str, ticker: str) -> None:
    _tbl("arena_positions").delete().eq("agent_id", agent_id).eq(
        "championship_id", _champ()
    ).eq("ticker", ticker.upper().strip()).execute()


def mark_position(agent_id: str, ticker: str, price: float) -> None:
    _tbl("arena_positions").update(
        {"last_price": round(float(price), 4), "marked_at": _now()}
    ).eq("agent_id", agent_id).eq("championship_id", _champ()).eq(
        "ticker", ticker.upper().strip()
    ).execute()


# ── Portfolio assembly ───────────────────────────────────────────────────────


def load_portfolio(agent: dict[str, Any], as_of: Optional[date] = None) -> PortfolioSnapshot:
    cash = get_cash(agent["id"])
    if cash is None:
        cash = float(agent.get("starting_cash") or 0)
    return PortfolioSnapshot(
        agent_id=agent["id"],
        slug=agent["slug"],
        cash=float(cash),
        positions=list_positions(agent["id"]),
        as_of=as_of,
    )


# ── Orders ───────────────────────────────────────────────────────────────────


def insert_order(row: dict[str, Any]) -> dict[str, Any]:
    res = _tbl("arena_orders").insert(_scoped(row)).execute()
    return (res.data or [{}])[0]


def update_order(order_id: str, patch: dict[str, Any]) -> None:
    _tbl("arena_orders").update(patch).eq("id", order_id).execute()


def list_pending_orders(intended_for: Optional[date] = None) -> list[dict[str, Any]]:
    q = (
        _tbl("arena_orders")
        .select("*")
        .eq("status", "pending")
        .eq("championship_id", _champ())
    )
    if intended_for is not None:
        q = q.lte("intended_for", intended_for.isoformat())
    return q.order("submitted_at").execute().data or []


def list_agent_pending_orders(agent_id: str) -> list[dict[str, Any]]:
    return (
        _tbl("arena_orders")
        .select("*")
        .eq("agent_id", agent_id)
        .eq("championship_id", _champ())
        .eq("status", "pending")
        .order("submitted_at")
        .execute()
        .data
        or []
    )


def list_recent_orders(agent_id: str, limit: int = 25) -> list[dict[str, Any]]:
    return (
        _tbl("arena_orders")
        .select("*")
        .eq("agent_id", agent_id)
        .eq("championship_id", _champ())
        .order("submitted_at", desc=True)
        .limit(limit)
        .execute()
        .data
        or []
    )


def cancel_pending_for(agent_id: str, intended_for: date) -> int:
    """Void one agent's un-filled orders for a session before it decides again.

    A decision row is unique per (agent, date), so re-running a day overwrites
    the decision — but the orders from the first attempt are separate rows and
    would otherwise survive alongside the second attempt's, doubling the size of
    every trade. Cancelling is recorded so the re-run is visible in the ledger
    rather than silently erased.
    """
    rows = (
        _tbl("arena_orders")
        .select("id")
        .eq("agent_id", agent_id)
        .eq("championship_id", _champ())
        .eq("status", "pending")
        .eq("intended_for", intended_for.isoformat())
        .execute()
        .data
        or []
    )
    for r in rows:
        update_order(
            r["id"],
            {"status": "cancelled", "reject_reason": "superseded by a re-run of this decision"},
        )
    return len(rows)


def cancel_stale_orders(before: date) -> int:
    """Cancel pending orders that never found a session to fill in.

    An order intended for a date that has already been filled past is dead: the
    information it was based on is stale and filling it later would be a
    look-ahead. Cancelling is recorded, not silent.
    """
    rows = (
        _tbl("arena_orders")
        .select("id")
        .eq("status", "pending")
        .eq("championship_id", _champ())
        .lt("intended_for", before.isoformat())
        .execute()
        .data
        or []
    )
    for r in rows:
        update_order(
            r["id"],
            {
                "status": "cancelled",
                "reject_reason": f"expired unfilled before {before.isoformat()}",
            },
        )
    return len(rows)


# ── Decisions ────────────────────────────────────────────────────────────────


def open_decision(agent_id: str, decision_date: date, llm_model: Optional[str]) -> dict[str, Any]:
    """Start (or restart) today's decision row. Unique per (agent, date), so a
    re-run overwrites the attempt rather than doubling the record."""
    payload = {
        "agent_id": agent_id,
        "decision_date": decision_date.isoformat(),
        "status": "running",
        "llm_model": llm_model,
        "started_at": _now(),
        "finished_at": None,
        "error": None,
        "narrative": None,
    }
    res = (
        _tbl("arena_decisions")
        .upsert(_scoped(payload), on_conflict="championship_id,agent_id,decision_date")
        .execute()
    )
    return (res.data or [{}])[0]


def close_decision(decision_id: str, patch: dict[str, Any]) -> None:
    patch = {**patch, "finished_at": _now()}
    _tbl("arena_decisions").update(patch).eq("id", decision_id).execute()


def fail_stale_running_decisions(older_than_minutes: int = 90) -> int:
    """Mark abandoned decision rows as errored.

    A run that is killed mid-loop (a crash, a machine restart, a Ctrl-C) leaves
    its row at 'running'. Left alone those rows accumulate and make the record
    look like agents are still thinking hours later. The public view already
    hides them; this closes them out so the CLI and any diagnosis see the truth.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=older_than_minutes)
    rows = (
        _tbl("arena_decisions")
        .select("id")
        .eq("status", "running")
        .eq("championship_id", _champ())
        .lt("started_at", cutoff.isoformat())
        .execute()
        .data
        or []
    )
    for r in rows:
        _tbl("arena_decisions").update(
            {
                "status": "error",
                "error": f"abandoned — still 'running' after {older_than_minutes} minutes",
                "finished_at": _now(),
            }
        ).eq("id", r["id"]).execute()
    return len(rows)


def get_decision(agent_id: str, decision_date: date) -> Optional[dict[str, Any]]:
    res = (
        _tbl("arena_decisions")
        .select("*")
        .eq("agent_id", agent_id)
        .eq("championship_id", _champ())
        .eq("decision_date", decision_date.isoformat())
        .limit(1)
        .execute()
    )
    return (res.data or [None])[0]


# ── NAV history ──────────────────────────────────────────────────────────────


def latest_nav_row(agent_id: str, before: Optional[date] = None) -> Optional[dict[str, Any]]:
    q = (
        _tbl("arena_nav_history")
        .select("*")
        .eq("agent_id", agent_id)
        .eq("championship_id", _champ())
    )
    if before is not None:
        q = q.lt("as_of", before.isoformat())
    res = q.order("as_of", desc=True).limit(1).execute()
    return (res.data or [None])[0]


def peak_nav(agent_id: str, through: date) -> Optional[float]:
    """Running NAV peak, for drawdown. Ordered+limited rather than aggregated
    because PostgREST has no MAX() — the curve is one row per session, so this
    stays small for years."""
    res = (
        _tbl("arena_nav_history")
        .select("nav")
        .eq("agent_id", agent_id)
        .eq("championship_id", _champ())
        .lte("as_of", through.isoformat())
        .order("nav", desc=True)
        .limit(1)
        .execute()
    )
    rows = res.data or []
    return float(rows[0]["nav"]) if rows else None


def upsert_nav(row: dict[str, Any]) -> None:
    _tbl("arena_nav_history").upsert(
        _scoped(row), on_conflict="championship_id,agent_id,as_of"
    ).execute()


def list_nav_history(agent_id: str, limit: int = 500) -> list[dict[str, Any]]:
    return (
        _tbl("arena_nav_history")
        .select("*")
        .eq("agent_id", agent_id)
        .eq("championship_id", _champ())
        .order("as_of")
        .limit(limit)
        .execute()
        .data
        or []
    )


# ── Universe ─────────────────────────────────────────────────────────────────

_universe_cache: Optional[set[str]] = None


def tradeable_universe() -> set[str]:
    """Symbols an agent is allowed to trade: the actively-traded NYSE/NASDAQ
    names the rest of the platform already covers, plus the benchmark ETF.

    Restricting the universe is a fairness control, not a convenience: without
    it one agent can wander into illiquid tickers whose FMP bars are thin, and
    win or lose on data quality rather than on its approach.
    """
    global _universe_cache
    if _universe_cache is not None:
        return _universe_cache

    symbols: set[str] = set(BENCHMARK_SYMBOLS)
    page, size = 0, 1000
    while True:
        res = (
            _tbl("tickers")
            .select("symbol")
            .eq("is_actively_trading", True)
            .range(page * size, page * size + size - 1)
            .execute()
        )
        rows = res.data or []
        symbols.update((r["symbol"] or "").upper().strip() for r in rows if r.get("symbol"))
        if len(rows) < size:
            break
        page += 1

    _universe_cache = {s for s in symbols if s}
    return _universe_cache


#: ETFs every agent may hold regardless of the stock universe.
#:
#: The universe filter exists to keep agents out of illiquid names whose bars
#: are thin — so excluding the most heavily traded instruments in existence was
#: backwards. It first showed up when the pairs layer handed The Arbitrageur an
#: IVV/VOO signal (its single widest spread) that the broker then refused as
#: "not in the tradeable universe". These are all core index/sector ETFs whose
#: liquidity is not in question, and `ticker_pair_stats` carries pairs across
#: several of them.
BENCHMARK_SYMBOLS = (
    "SPY", "QQQ", "IVV", "VOO", "VTI", "DIA", "IWM",   # broad market
    "XLF", "XLE", "XLK", "XLV", "XLI", "XLY", "XLP",   # sectors
    "XLU", "XLB", "XLRE", "XLC", "SMH", "GLD", "TLT",
)
