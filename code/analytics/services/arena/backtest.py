"""
Historical replay — run the arena forward over past sessions.

## What this is honest about, and what it is not

The **prices are point-in-time**. Each session fills at that session's own open
and marks to that session's own close, exactly as live trading does. Nothing in
the accounting can see the future.

The **research is not**. Every agent's tools (`get_top_articles`,
`get_priced_in`, `get_pair_signals`, the FMP endpoints…) read from *now*, because
that is the only state those sources have. An agent replaying 2026-06-10 is
reasoning over data that did not exist until months later, and in the case of
news impact scores, over scores that were literally backfilled in bulk after the
fact — before April 2026, **zero** articles were scored within 24h of
publication.

So a replayed return demonstrates that the machinery runs end to end. It is
**not evidence that an approach makes money**, and the leaderboard says so:
every row written here carries `is_backtest = true`, and the public page marks
the replayed segment of each curve.

`--point-in-time` gates the sources that CAN be rewound honestly (currently the
screening boards, via `run_at`). It is off by default, because switching it on
for some agents and not others makes the agents non-comparable — a handicap
applied unevenly is worse than one applied to nobody.

## Shape of a run

For each session, in order:

    fill    orders queued by the previous decision execute at this open
    mark    positions marked to this close, NAV row appended
    decide  agents decide for the next session          (every N sessions)

Decisions are the expensive part — roughly 140s per LLM agent, so seven agents
is ~17 minutes per decision day. `--decide-every N` runs fills and marks on every
session (they are cheap and deterministic) while spacing out the LLM work; N=5
turns a 70-session replay from ~19 hours into ~4.

Runs are **resumable**. Progress is derived from the NAV rows already written,
so re-invoking with the same window picks up at the first unmarked session
rather than starting over or double-counting.
"""

from __future__ import annotations

import logging
import math
import uuid
from datetime import date, timedelta
from typing import Any, Optional

from . import scheduler, store
from . import tools as arena_tools
from .marks import PriceBook
from .roster import ROSTER

log = logging.getLogger(__name__)

_CALENDAR_TICKER = "SPY"

#: Bars are fetched once for the whole window rather than per session. Without
#: this a 70-session replay would make 70 FMP calls per ticker.
_PRELOAD_PAD_DAYS = 45


# ── Session calendar ─────────────────────────────────────────────────────────


def sessions_between(start: date, end: date, prices: PriceBook) -> list[date]:
    """Trading sessions in [start, end], from the benchmark's own bars."""
    prices.load([_CALENDAR_TICKER], start - timedelta(days=_PRELOAD_PAD_DAYS), end)
    bars = prices._bars.get(_CALENDAR_TICKER, {})  # noqa: SLF001 — same package
    return sorted(
        d
        for iso in bars
        if start <= (d := date.fromisoformat(iso)) <= end
    )


# ── Wipe / re-fund ───────────────────────────────────────────────────────────


def wipe_and_refund(slugs: list[str], funded_on: date) -> list[str]:
    """Delete every trading row for these agents and re-open their accounts.

    Destructive and deliberate: it discards live trades so the replay and the
    live record form ONE continuous curve rather than two that disagree about
    where the money is. The agents' definitions (prompt, tools, limits) are
    untouched — only their trading history.
    """
    sb = store.get_supabase_client().schema("swingtrader")
    wiped = []
    for slug in slugs:
        agent = store.get_agent(slug)
        if not agent:
            log.warning("arena/backtest: no agent %r to wipe", slug)
            continue
        # Scoped to the ACTIVE championship. Deleting by agent alone would take
        # every other season's history with it — the whole point of a
        # championship is that its book is separate.
        champ_id = store.active_championship()
        for table in (
            "arena_orders",
            "arena_positions",
            "arena_decisions",
            "arena_nav_history",
        ):
            q = sb.table(table).delete().eq("agent_id", agent["id"])
            if champ_id:
                q = q.eq("championship_id", champ_id)
            q.execute()
        store.set_cash(agent["id"], float(agent.get("starting_cash") or 100_000))
        sb.table("arena_agents").update({"funded_on": funded_on.isoformat()}).eq(
            "id", agent["id"]
        ).execute()
        wiped.append(slug)
    log.info("arena/backtest: wiped and re-funded %d agents on %s", len(wiped), funded_on)
    return wiped


# ── Resume ───────────────────────────────────────────────────────────────────


def last_marked_session(slugs: list[str]) -> Optional[date]:
    """The newest session every named agent already has a NAV row for.

    The MINIMUM across agents, not the maximum: if a run died partway through a
    session's mark pass, resuming from the furthest-ahead agent would skip the
    ones that never got marked and leave a hole in their curves.
    """
    marks: list[date] = []
    for slug in slugs:
        agent = store.get_agent(slug)
        if not agent:
            continue
        row = store.latest_nav_row(agent["id"])
        if row is None:
            return None  # someone has no history at all — start from the top
        marks.append(date.fromisoformat(str(row["as_of"])[:10]))
    return min(marks) if marks else None


# ── The replay ───────────────────────────────────────────────────────────────


def run_backtest(
    start: date,
    end: date,
    *,
    slugs: Optional[list[str]] = None,
    decide_every: int = 1,
    wipe: bool = False,
    resume: bool = True,
    point_in_time: bool = False,
    concurrency: int = scheduler.DEFAULT_CONCURRENCY,
    run_id: Optional[str] = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Replay the arena over [start, end].

    Returns a summary dict. Every row written is stamped ``is_backtest`` and
    grouped under ``run_id`` so a bad replay can be removed wholesale.
    """
    slugs = slugs or [s.slug for s in ROSTER]
    run_id = run_id or str(uuid.uuid4())

    prices = PriceBook()
    sessions = sessions_between(start, end, prices)
    if not sessions:
        return {"error": f"no trading sessions between {start} and {end}"}

    if wipe and not dry_run:
        wipe_and_refund(slugs, funded_on=sessions[0])
    elif resume and not dry_run:
        done_through = last_marked_session(slugs)
        if done_through is not None:
            remaining = [s for s in sessions if s > done_through]
            if not remaining:
                return {
                    "run_id": run_id,
                    "status": "already_complete",
                    "marked_through": done_through.isoformat(),
                    "sessions": 0,
                }
            log.info(
                "arena/backtest: resuming after %s — %d of %d sessions remain",
                done_through, len(remaining), len(sessions),
            )
            sessions = remaining

    decision_days = sessions[::decide_every] if decide_every > 1 else sessions

    plan = {
        "run_id": run_id,
        "sessions": len(sessions),
        "first": sessions[0].isoformat(),
        "last": sessions[-1].isoformat(),
        "decision_days": len(decision_days),
        "agents": slugs,
        "decide_every": decide_every,
        "point_in_time": point_in_time,
        "concurrency": concurrency,
        # Wall-clock, not CPU: with N agents in flight the per-session cost is
        # ceil(agents / concurrency) waves of ~140s, not agents * 140s.
        "estimated_hours": round(
            len(decision_days)
            * math.ceil(_llm_agent_count(slugs) / max(1, concurrency))
            * 140 / 3600,
            1,
        ),
    }
    if dry_run:
        return {**plan, "status": "dry_run"}

    log.info(
        "arena/backtest: %d agents x %d sessions %s..%s, ~%.1fh",
        len(slugs), plan["sessions"], plan["first"], plan["last"],
        plan["estimated_hours"],
    )
    if point_in_time:
        log.info(
            "arena/backtest: point-in-time ON — news (published_at), ticker "
            "sentiment, attention trends and the screening boards are bounded "
            "by each session. Priced-in, pair z-scores, the relationship graph "
            "and FMP fundamentals have no historical version and remain "
            "look-ahead; see UNBOUNDED_IN_REPLAY in services/arena/tools.py."
        )

    # Warm every ticker the agents already hold, plus the benchmark, across the
    # whole window in one pass. Names bought later are loaded on demand.
    _preload(prices, slugs, sessions[0], sessions[-1])

    store.set_backtest_mode(run_id)
    stats = {"filled": 0, "rejected": 0, "marks": 0, "decisions": 0, "errors": 0}
    completed: list[str] = []
    try:
        decision_set = set(decision_days)
        for a_i, slug in enumerate(slugs, 1):
            agent_sessions = _remaining_for(slug, sessions, resume=resume and not wipe)
            if not agent_sessions:
                log.info("arena/backtest: [agent %d/%d] %s already complete", a_i, len(slugs), slug)
                completed.append(slug)
                continue

            log.info(
                "arena/backtest: [agent %d/%d] %s — %d sessions (%s..%s)",
                a_i, len(slugs), slug, len(agent_sessions),
                agent_sessions[0], agent_sessions[-1],
            )
            halted = _sweep_agent(
                slug, agent_sessions, decision_set, sessions, prices,
                concurrency=concurrency, point_in_time=point_in_time, stats=stats,
            )
            if halted:
                stats["halted_on"] = halted
                log.error(
                    "arena/backtest: backend refused %s on %s — stopping. %d of %d "
                    "agents complete; re-run the same command to resume.",
                    slug, halted, len(completed), len(slugs),
                )
                break
            completed.append(slug)
            log.info("arena/backtest: %s COMPLETE (%d/%d)", slug, len(completed), len(slugs))
    finally:
        # Always drop both clocks, including on a crash — leaving either set
        # would silently mark the next LIVE run as simulated, or bound its
        # research to a past date.
        store.set_backtest_mode(None)
        arena_tools.set_as_of(None)

    return {**plan, "status": "complete", "agents_completed": completed, **stats}


def _sweep_agent(
    slug: str,
    agent_sessions: list[date],
    decision_set: set,
    all_sessions: list[date],
    prices: PriceBook,
    *,
    concurrency: int,
    point_in_time: bool,
    stats: dict[str, Any],
) -> Optional[str]:
    """Run ONE agent through its remaining sessions, in order.

    Returns the session it was blocked on, or None if it completed.

    Agent-major rather than session-major, and the two produce identical books:
    agents share no mutable state — separate cash rows, positions, decisions and
    in-memory portfolios — so agent A's entire run cannot influence agent B's.
    What must stay ordered is the sessions WITHIN one agent, because session N+1
    fills what N decided.

    The reason to prefer it is the failure mode. Session-major spreads an outage
    across every agent at once: the previous replay lost its LLM backend partway
    through and left nine agents each holding a stale book through a month of
    tape, which is unusable. Agent-major turns the same outage into "six agents
    finished, three untouched", and lets a single agent be re-run after a prompt
    change without redoing the rest.
    """
    for i, session in enumerate(agent_sessions, 1):
        log.info("arena/backtest: %s [%d/%d] %s", slug, i, len(agent_sessions), session)

        fills = scheduler.run_fill(session, prices, only=[slug])
        stats["filled"] += fills.get("filled", 0)
        stats["rejected"] += fills.get("rejected", 0)

        marked = scheduler.run_mark(session, prices, only=[slug])
        stats["marks"] += len(marked)

        if session not in decision_set:
            continue

        # Bound the rewindable sources to this session before the agent
        # researches it. Set per session, not once per run.
        arena_tools.set_as_of(session if point_in_time else None)

        # It decides on this session's close for the NEXT session it will be
        # filled in — which, when decisions are spaced out, is the next session
        # in the replay, not merely the next calendar day.
        nxt = _next_in(all_sessions, session) or scheduler.next_session_after(session)
        results = scheduler.run_decide(
            session, nxt, prices, only=[slug], concurrency=concurrency
        )
        stats["decisions"] += len(results)
        stats["errors"] += sum(1 for r in results if r.get("status") == "error")

        # Stop on a wall rather than walking into it for every remaining
        # session. A replay is resumable, so stopping loses nothing and keeps
        # the completed agents clean.
        if _all_llm_blocked(results):
            return session.isoformat()
    return None


def _remaining_for(slug: str, sessions: list[date], *, resume: bool) -> list[date]:
    """Sessions this agent still needs. Resume is per-agent in agent-major order."""
    if not resume:
        return sessions
    done_through = last_marked_session([slug])
    if done_through is None:
        return sessions
    return [s for s in sessions if s > done_through]


#: Backend refusals that mean "stop", not "this agent had a bad day".
_BLOCKED_MARKERS = (
    "usage limit", "rate limit", "quota",
    "upgrade for higher limits", "returned 429",
)


def _all_llm_blocked(results: list[dict[str, Any]]) -> bool:
    """True when no LLM agent got through and at least one was refused outright.

    In agent-major order a decision pass usually holds a SINGLE agent, so a
    threshold of "three or more blocked" would never fire. What matters is the
    distinction between kinds of failure: a refusal (quota, rate limit) means the
    next session fails identically and the run should stop, while a timeout or a
    crash is that agent having a bad day and is not grounds for abandoning it.
    """
    # Any LLM agent that got through means the backend is up and this is not an
    # outage — the deterministic controls do not count, they never call it.
    if any(r.get("status") == "ok" and r.get("rounds") is not None for r in results):
        return False
    return any(
        r.get("status") == "error"
        and any(m in str(r.get("error", "")).lower() for m in _BLOCKED_MARKERS)
        for r in results
    )


def _next_in(sessions: list[date], current: date) -> Optional[date]:
    idx = sessions.index(current)
    return sessions[idx + 1] if idx + 1 < len(sessions) else None


def _llm_agent_count(slugs: list[str]) -> int:
    by_slug = {s.slug: s for s in ROSTER}
    return sum(1 for s in slugs if (spec := by_slug.get(s)) and spec.engine == "llm")


def _preload(prices: PriceBook, slugs: list[str], start: date, end: date) -> None:
    tickers = {_CALENDAR_TICKER, *store.BENCHMARK_SYMBOLS}
    for slug in slugs:
        agent = store.get_agent(slug)
        if agent:
            tickers.update(p.ticker for p in store.list_positions(agent["id"]))
    prices.load(sorted(tickers), start - timedelta(days=_PRELOAD_PAD_DAYS), end)


# ── Removing a bad run ───────────────────────────────────────────────────────


def delete_run(run_id: str) -> dict[str, int]:
    """Remove every row a replay wrote. Live rows are untouched.

    Positions are NOT deleted here — they are current state, not history, and a
    replay that is being thrown away should be followed by a wipe-and-refund
    rather than left with a book nothing explains.
    """
    sb = store.get_supabase_client().schema("swingtrader")
    out = {}
    for table in ("arena_nav_history", "arena_orders", "arena_decisions"):
        res = sb.table(table).delete().eq("backtest_run_id", run_id).execute()
        out[table] = len(res.data or [])
    return out
