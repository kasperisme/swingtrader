"""
The daily clock.

Three passes, in this order, each idempotent per (agent, session):

    fill    yesterday's queued orders execute at TODAY's open
    mark    positions are marked to TODAY's close; the NAV row is appended
    decide  each agent reads the closed session and queues for the NEXT one

Order matters and is not arbitrary. Marking before filling would value a book
that does not exist yet; deciding before marking would show an agent a stale
NAV. Running all three in one nightly invocation (``run_day``) keeps them in
step, which is why the cron calls that rather than the three separately.

Sessions are US equity trading days, derived from the benchmark's own bars: if
SPY printed a bar, the market was open. That avoids carrying a holiday calendar
that would silently drift out of date, and it fails in the safe direction — no
bar means no session means no trading.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import date, datetime, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

from . import championships, controls, decide, store
from .broker import Broker
from .marks import PriceBook
from .roster import ROSTER, spec_to_row

log = logging.getLogger(__name__)

_ET = ZoneInfo("America/New_York")
_CALENDAR_TICKER = "SPY"


# ── Roster sync ──────────────────────────────────────────────────────────────


def sync_roster(fund: bool = True, funded_on: Optional[date] = None) -> list[dict[str, Any]]:
    """Write ``roster.py`` into ``arena_agents``.

    Definitions only. Funding is no longer done here — an agent is funded when a
    CHAMPIONSHIP starts, once per championship, so there is exactly one place
    that decides an agent has $100,000 and when. Safe to re-run: editing a prompt
    and re-syncing never touches a book.
    """
    out = []
    for spec in ROSTER:
        row = store.upsert_agent(spec_to_row(spec))
        out.append({"slug": spec.slug, "id": row.get("id"), "engine": spec.engine})
    return out


def bind_championship(slug: Optional[str] = None) -> dict[str, Any]:
    """Resolve and activate the championship every subsequent write belongs to.

    Defaults to whichever one is running. Fails loudly rather than inventing one:
    with no championship open there is no correct place to record a trade, and a
    silent fallback would scatter rows across seasons.
    """
    champ = championships.get(slug) if slug else championships.current()
    if champ is None:
        raise RuntimeError(
            f"no {'championship ' + repr(slug) if slug else 'running championship'} — "
            "create and start one first (cli.py championship create / start)."
        )
    store.set_championship(champ["id"])
    return champ


# ── Session calendar ─────────────────────────────────────────────────────────


def _calendar_book(through: date, book: Optional[PriceBook] = None, lookback_days: int = 30) -> PriceBook:
    """Ensure ``book`` holds the calendar ticker's bars.

    Takes an existing book so ``run_day`` makes one SPY call for the whole day
    rather than one per pass. An empty PriceBook is truthy, so callers must not
    test the book itself for freshness — ``has()`` is the check that matters.
    """
    book = book if book is not None else PriceBook()
    if not book.has(_CALENDAR_TICKER):
        book.load([_CALENDAR_TICKER], through - timedelta(days=lookback_days), through)
    return book


def last_closed_session(through: Optional[date] = None, book: Optional[PriceBook] = None) -> Optional[date]:
    """The most recent session with a printed close at or before ``through``.

    Before 16:00 ET the current day's close is not final, so it is excluded —
    otherwise a run started at lunchtime would mark the book against a partial
    bar and write a NAV row that changes underneath itself.
    """
    now_et = datetime.now(_ET)
    through = through or now_et.date()
    if through == now_et.date() and now_et.hour < 16:
        through = through - timedelta(days=1)

    book = _calendar_book(through, book)
    _, session = book.last_close_on_or_before(_CALENDAR_TICKER, through)
    return session


def next_session_after(session: date, book: Optional[PriceBook] = None) -> date:
    """The next session the market opens after ``session``.

    Only bars already printed can be confirmed, so a future date is estimated by
    skipping weekends. A holiday estimated wrong is harmless: the fill pass
    matches pending orders with ``intended_for <= session``, so the order simply
    fills on the next real session instead.
    """
    candidate = session + timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return candidate


# ── The three passes ─────────────────────────────────────────────────────────


def run_fill(
    session: date, prices: PriceBook, *, only: Optional[list[str]] = None
) -> dict[str, Any]:
    """Fill every pending order at ``session``'s open.

    ``only`` restricts the pass to a subset of the roster — required by a
    replay scoped to some agents, so the rest are not dragged into a historical
    session they are not taking part in.
    """
    agents = {a["id"]: a for a in _scoped_agents(only, active_only=False)}

    pending = store.list_pending_orders(intended_for=session)
    tickers = sorted({o["ticker"] for o in pending})
    if tickers:
        prices.load(tickers, session - timedelta(days=10), session)

    broker = Broker(prices)
    stats = broker.fill_pending(session, agents)

    # Anything still pending from before today missed its window entirely.
    # Scoped to the agents in this pass — see cancel_stale_orders.
    stats["expired"] = store.cancel_stale_orders(
        before=session, agent_ids=[a["id"] for a in agents.values()]
    )
    log.info("arena: fill %s — %s", session, stats)
    return stats


def run_mark(
    session: date, prices: PriceBook, *, only: Optional[list[str]] = None
) -> list[dict[str, Any]]:
    """Mark each agent's book to ``session``'s close and append the NAV curve.

    ``only`` matters more here than anywhere else. Marking the WHOLE roster
    during a replay scoped to two agents writes a flat $100,000 NAV row, for
    every historical session, for seven agents that never participated — a
    fabricated curve that then reads on the leaderboard as though they had
    traded and gone nowhere.
    """
    agents = _scoped_agents(only, active_only=False)

    tickers: set[str] = set()
    for agent in agents:
        tickers.update(p.ticker for p in store.list_positions(agent["id"]))
    if tickers:
        prices.load(sorted(tickers), session - timedelta(days=15), session)

    broker = Broker(prices)
    rows = []
    for agent in agents:
        row = broker.mark_to_market(agent, session)
        if row:
            rows.append({"slug": agent["slug"], "nav": row["nav"], "as_of": row["as_of"]})
    log.info("arena: mark %s — %d agents", session, len(rows))
    return rows


def _warm_fmp_catalogue(agents: list[dict[str, Any]]) -> None:
    """Populate the FMP MCP schema cache before any event loop is running."""
    import os

    from .roster import BY_SLUG

    wants_fmp = any(
        (spec := BY_SLUG.get(a.get("strategy_key") or a["slug"])) and spec.include_fmp
        for a in agents
    )
    if not wants_fmp or not os.environ.get("FMP_API_KEY"):
        return
    try:
        from services.agent.fmp_tools import get_fmp_tool_schemas

        schemas = get_fmp_tool_schemas()
        log.info("arena: FMP catalogue warmed — %d tools available", len(schemas))
    except Exception as exc:
        log.warning("arena: could not warm the FMP catalogue: %s", exc)


def _scoped_agents(only: Optional[list[str]], *, active_only: bool) -> list[dict[str, Any]]:
    agents = store.list_agents(active_only=active_only)
    if not only:
        return agents
    wanted = {s.strip() for s in only}
    return [a for a in agents if a["slug"] in wanted]


#: Default LLM agents in flight at once. They share one Ollama backend and one
#: FMP key, so this is a throughput knob, not a free multiplier.
DEFAULT_CONCURRENCY = int(os.environ.get("ARENA_CONCURRENCY", "4"))

#: Hard deadline on one agent's decision. Normal is 140-250s alone, up to ~600s
#: under concurrency; anything past this is a stuck connection, not thinking.
DECISION_TIMEOUT_S = int(os.environ.get("ARENA_DECISION_TIMEOUT", "900"))


def run_decide(
    session: date,
    intended_for: date,
    prices: PriceBook,
    *,
    only: Optional[list[str]] = None,
    dry_run: bool = False,
    concurrency: int = DEFAULT_CONCURRENCY,
) -> list[dict[str, Any]]:
    """Run every active agent's decision for the next session.

    LLM agents run CONCURRENTLY, bounded by ``concurrency``; the deterministic
    controls run inline first. A failure is recorded on that agent's decision
    row and the rest of the roster continues.
    """
    agents = _scoped_agents(only, active_only=True)

    # Warm the FMP tool catalogue ONCE, here, on a thread with no running event
    # loop. `get_fmp_tool_schemas()` fetches over MCP via `asyncio.run()`, which
    # raises "cannot be called from a running event loop" when an agent builds
    # its registry inside `asyncio.run(run_decision(...))`. The failure was
    # swallowed as a warning, so every FMP-enabled agent had silently been
    # running without any FMP tools at all. Warming the module-level cache up
    # front means the in-loop call is a dict lookup.
    _warm_fmp_catalogue(agents)

    broker = Broker(prices)

    # The deterministic controls are pure Python and take milliseconds; run them
    # first and inline. They also mutate their own books only, so ordering
    # against the LLM agents is irrelevant.
    results: list[dict[str, Any]] = []
    llm_agents = []
    for agent in agents:
        if agent.get("engine") == "deterministic":
            try:
                results.append(controls.run_control(
                    agent, session=session, intended_for=intended_for,
                    broker=broker, dry_run=dry_run,
                ))
            except Exception as exc:
                log.exception("arena: %s failed", agent["slug"])
                results.append({"slug": agent["slug"], "status": "error", "error": str(exc)})
        else:
            llm_agents.append(agent)

    if llm_agents:
        results.extend(
            asyncio.run(
                _decide_llm_agents(
                    llm_agents,
                    session=session,
                    intended_for=intended_for,
                    broker=broker,
                    dry_run=dry_run,
                    concurrency=concurrency,
                )
            )
        )
    return results


async def _decide_llm_agents(
    agents: list[dict[str, Any]],
    *,
    session: date,
    intended_for: date,
    broker: Broker,
    dry_run: bool,
    concurrency: int,
) -> list[dict[str, Any]]:
    """Run the LLM agents concurrently under one event loop.

    Safe to parallelise because agents share no mutable state: each has its own
    cash row, positions, decision row and in-memory portfolio, and the broker
    validates every order against that agent's own book. The module-level
    championship / replay / as-of clocks ARE shared, but they are per-run
    constants that every agent in the pass reads identically.

    What is NOT parallelisable is sessions: session N+1 fills what N decided, so
    the outer loop stays strictly sequential.

    ``concurrency`` bounds it because the agents share one Ollama backend and one
    FMP key; unbounded fan-out trades timeouts for speed.
    """
    sem = asyncio.Semaphore(max(1, concurrency))

    async def one(agent: dict[str, Any]) -> dict[str, Any]:
        async with sem:
            log.info("arena: deciding — %s (for %s)", agent["slug"], intended_for)
            try:
                return await asyncio.wait_for(
                    decide.run_decision(
                        agent,
                        session=session,
                        intended_for=intended_for,
                        broker=broker,
                        dry_run=dry_run,
                    ),
                    timeout=DECISION_TIMEOUT_S,
                )
            except asyncio.TimeoutError:
                # A single agent once ran for 98 minutes and consumed more wall
                # clock than the twelve sessions around it. The loop retries
                # transient backend errors but has no overall deadline, so one
                # degraded connection can stall an entire replay. Abandon it and
                # carry on: a missed decision is one flat day for that agent, a
                # stalled replay is every day for all of them.
                log.warning(
                    "arena: %s exceeded %ds — abandoning this decision",
                    agent["slug"], DECISION_TIMEOUT_S,
                )
                if not dry_run:
                    # Cancellation never reaches run_decision's own handler, so
                    # the row would otherwise sit at 'running' forever.
                    try:
                        store.fail_decision(
                            agent["id"], intended_for,
                            f"abandoned after {DECISION_TIMEOUT_S}s",
                        )
                    except Exception:
                        log.exception("arena: could not close out %s", agent["slug"])
                return {"slug": agent["slug"], "status": "error", "error": "timeout"}
            except Exception as exc:  # one bad agent must not end the roster's day
                log.exception("arena: %s failed", agent["slug"])
                return {"slug": agent["slug"], "status": "error", "error": str(exc)}

    return list(await asyncio.gather(*(one(a) for a in agents)))


def run_day(
    session: Optional[date] = None,
    *,
    only: Optional[list[str]] = None,
    skip_decide: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """One full arena day: fill, then mark, then decide.

    This is what the nightly cron calls. ``session`` defaults to the last
    session with a printed close.
    """
    if store.active_championship() is None:
        try:
            bind_championship()
        except RuntimeError as exc:
            return {"error": str(exc)}

    prices = PriceBook()
    session = session or last_closed_session(book=prices)
    if session is None:
        return {"error": "no closed session found — is the price feed up?"}

    intended_for = next_session_after(session)
    log.info("arena: running day for %s (orders will target %s)", session, intended_for)

    stale = store.fail_stale_running_decisions()
    if stale:
        log.warning("arena: closed out %d abandoned decision rows", stale)

    fills = run_fill(session, prices, only=only)
    marks = run_mark(session, prices, only=only)
    decisions = (
        [] if skip_decide else run_decide(session, intended_for, prices, only=only, dry_run=dry_run)
    )

    champ = championships.get_by_id(store.active_championship()) or {}
    return {
        "championship": champ.get("slug"),
        "session": session.isoformat(),
        "intended_for": intended_for.isoformat(),
        "fills": fills,
        "marks": marks,
        "decisions": decisions,
    }
