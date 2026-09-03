"""
Championships — fixed-window competitions, and the title that carries between them.

An open-ended leaderboard cannot be won. A championship can: every agent is
re-funded on the same day with the same cash, trades for a fixed window, and one
of them finishes on top. Then it runs again.

The **title** is what makes the series worth following. The winner holds it until
another agent wins a later championship; consecutive wins are *defences*. That
lineage is derived in `arena_title_lineage_v` from concluded championships
rather than stored as a mutable flag — a stored `is_champion` boolean is one
failed update away from two champions or none.

Lifecycle:

    create   → 'upcoming'   the window is declared, nobody is funded yet
    start    → 'running'    every agent re-funded; this is the one the daily
                            job writes into. At most one may be running.
    conclude → 'complete'   champion and runner-up written from final NAV;
                            the title lineage picks it up automatically.

`abandon` exists for a championship that went wrong (a bad replay, a broken
model) and takes it out of the lineage without deleting the evidence.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from shared.db import get_supabase_client

from . import store

log = logging.getLogger(__name__)

_SCHEMA = "swingtrader"

#: Standard championship length. Three months is the shortest window in which a
#: swing-trading approach gets enough independent setups for the result to mean
#: anything — roughly 63 sessions, so the Sharpe on the leaderboard clears its
#: own 20-session floor with room to spare — while still being short enough that
#: the title changes hands often enough to be worth following.
DEFAULT_DURATION_MONTHS = 3


def add_months(d: date, months: int) -> date:
    """Same day-of-month N months on, clamped to the end of a shorter month."""
    total = (d.month - 1) + months
    year, month = d.year + total // 12, total % 12 + 1
    if month == 12:
        last = 31
    else:
        last = (date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)).day
    return date(year, month, min(d.day, last))


def default_end(starts_on: date) -> date:
    """The standard window: three months, ending the day before the anniversary."""
    return add_months(starts_on, DEFAULT_DURATION_MONTHS) - timedelta(days=1)


def _tbl(name: str):
    return get_supabase_client().schema(_SCHEMA).table(name)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Reads ────────────────────────────────────────────────────────────────────


def get(slug: str) -> Optional[dict[str, Any]]:
    res = _tbl("arena_championships").select("*").eq("slug", slug).limit(1).execute()
    return (res.data or [None])[0]


def get_by_id(championship_id: str) -> Optional[dict[str, Any]]:
    res = (
        _tbl("arena_championships").select("*").eq("id", championship_id).limit(1).execute()
    )
    return (res.data or [None])[0]


def current() -> Optional[dict[str, Any]]:
    """The championship the daily job writes into, or None if none is running."""
    res = _tbl("arena_championships").select("*").eq("status", "running").limit(1).execute()
    return (res.data or [None])[0]


def list_all(limit: int = 50) -> list[dict[str, Any]]:
    return (
        _tbl("arena_championships")
        .select("*")
        .order("starts_on", desc=True)
        .limit(limit)
        .execute()
        .data
        or []
    )


def standings(championship_id: str) -> list[dict[str, Any]]:
    """Final or live standings, best total return first."""
    rows = (
        _tbl("arena_leaderboard_v")
        .select("*")
        .eq("championship_id", championship_id)
        .execute()
        .data
        or []
    )
    return sorted(
        rows,
        key=lambda r: (r.get("total_return") is None, -(r.get("total_return") or 0)),
    )


def title_lineage() -> list[dict[str, Any]]:
    """Every reign, oldest first. The last row is the current holder."""
    return _tbl("arena_title_lineage_v").select("*").execute().data or []


def reigning_champion() -> Optional[dict[str, Any]]:
    return next((r for r in title_lineage() if r.get("is_current_holder")), None)


# ── Lifecycle ────────────────────────────────────────────────────────────────


def create(
    slug: str,
    name: str,
    starts_on: date,
    ends_on: Optional[date] = None,
    *,
    description: Optional[str] = None,
    starting_cash: float = 100_000.0,
    is_backtest: bool = False,
) -> dict[str, Any]:
    existing = get(slug)
    if existing:
        return existing
    ends_on = ends_on or default_end(starts_on)
    res = _tbl("arena_championships").insert(
        {
            "slug": slug,
            "name": name,
            "description": description,
            "starts_on": starts_on.isoformat(),
            "ends_on": ends_on.isoformat(),
            "status": "upcoming",
            "starting_cash": starting_cash,
            "is_backtest": is_backtest,
        }
    ).execute()
    row = (res.data or [{}])[0]
    log.info("arena: created championship %s (%s → %s)", slug, starts_on, ends_on)
    return row


def start(slug: str, entrants: Optional[list[str]] = None) -> dict[str, Any]:
    """Open a championship and re-fund every entrant from scratch.

    Refuses if another championship is already running: two live championships
    would each claim the agents' current book, and whichever wrote last would
    win. Conclude or abandon the open one first.
    """
    champ = get(slug)
    if champ is None:
        raise ValueError(f"no championship {slug!r}")
    if champ["status"] == "running":
        return champ
    if champ["status"] == "complete":
        raise ValueError(f"championship {slug!r} is already complete")

    running = current()
    if running and running["id"] != champ["id"]:
        raise ValueError(
            f"championship {running['slug']!r} is still running — conclude or "
            f"abandon it before starting {slug!r}"
        )

    agents = store.list_agents(active_only=True)
    if entrants:
        wanted = {s.strip() for s in entrants}
        agents = [a for a in agents if a["slug"] in wanted]
    if not agents:
        raise ValueError("no active agents to enter")

    cash = float(champ["starting_cash"])
    for agent in agents:
        store.open_account(agent["id"], champ["id"], cash)

    _tbl("arena_championships").update({"status": "running"}).eq("id", champ["id"]).execute()
    log.info(
        "arena: started championship %s with %d entrants at $%s each",
        slug, len(agents), f"{cash:,.0f}",
    )
    return {**champ, "status": "running", "entrants": [a["slug"] for a in agents]}


def conclude(slug: str) -> dict[str, Any]:
    """Close a championship and crown its winner.

    The champion is the highest total return at the final mark. Deterministic
    controls are eligible: if the index or the coin flip wins, that IS the
    result, and hiding it would defeat the purpose of running them.
    """
    champ = get(slug)
    if champ is None:
        raise ValueError(f"no championship {slug!r}")
    if champ["status"] == "complete":
        return champ

    table = standings(champ["id"])
    ranked = [r for r in table if r.get("total_return") is not None]
    if not ranked:
        raise ValueError(
            f"championship {slug!r} has no marked results — nothing to decide"
        )

    winner, runner_up = ranked[0], (ranked[1] if len(ranked) > 1 else None)
    _tbl("arena_championships").update(
        {
            "status": "complete",
            "champion_agent_id": winner["id"],
            "runner_up_agent_id": runner_up["id"] if runner_up else None,
            "champion_return": winner["total_return"],
            "concluded_at": _now(),
        }
    ).eq("id", champ["id"]).execute()

    log.info(
        "arena: %s won %s with %+.2f%%",
        winner["name"], slug, (winner["total_return"] or 0) * 100,
    )
    return {
        "slug": slug,
        "champion": winner["name"],
        "champion_slug": winner["slug"],
        "champion_return": winner["total_return"],
        "runner_up": runner_up["name"] if runner_up else None,
        "entrants": len(ranked),
    }


def abandon(slug: str, reason: Optional[str] = None) -> dict[str, Any]:
    """Take a championship out of the lineage without deleting its evidence."""
    champ = get(slug)
    if champ is None:
        raise ValueError(f"no championship {slug!r}")
    note = (champ.get("description") or "").strip()
    if reason:
        note = f"{note}\n\nAbandoned: {reason}".strip()
    _tbl("arena_championships").update(
        {"status": "abandoned", "description": note}
    ).eq("id", champ["id"]).execute()
    return {"slug": slug, "status": "abandoned"}
