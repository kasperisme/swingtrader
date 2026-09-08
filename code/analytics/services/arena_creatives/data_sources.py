"""
data_sources — the deterministic half of the arena creative package.

Everything a table graphic or a league-table race needs, read from the arena's
**public** views only (``arena_leaderboard_v``, ``arena_nav_history_public_v``,
``arena_championships_public_v``). Reading the public views rather than the base
tables is not squeamishness: those views filter on ``is_published`` in the view,
so a creative can never publish an agent that is still being tuned — the same
guarantee the Next.js side relies on.

No creative choices are made here. This module produces standings, movement,
form and race keyframes; the ``nis-arena-report`` skill picks the story and
writes the words.

Three derived quantities the leaderboard view does not carry, because they are
broadcast conventions rather than accounting:

``move``
    Rank change against a lookback session — the ``▲2`` / ``▼1`` chevron. Ranks
    are recomputed from the NAV history at that date rather than stored, so a
    re-run is reproducible and a backfilled session cannot silently rewrite last
    week's graphic.

``form``
    The last N sessions as W/L/D, from ``daily_return``. The football form guide,
    and the cheapest possible way to make a static table feel like it is moving.

``streak``
    The current run, signed. ``+4`` = four winning sessions. This is what a
    commentator reaches for when the table itself has not changed.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any, Optional

from shared.db import get_supabase_client

log = logging.getLogger(__name__)

_SCHEMA = "swingtrader"

#: A session's move counts as a draw inside this band. Daily NAV noise on a
#: mostly-cash book is not a result, and rendering it as a win inflates every
#: form guide on the board.
_FLAT_BAND = 0.0005  # 5bp


def _tbl(name: str):
    return get_supabase_client().schema(_SCHEMA).table(name)


# ── championship selection ───────────────────────────────────────────────────


def resolve_championship(slug: Optional[str] = None) -> dict[str, Any]:
    """The championship a creative is about.

    Defaults to the one that is ``running`` — a creative is nearly always about
    the season in progress. Falls back to the most recently started, so the
    pipeline still renders in the gap between one season concluding and the next
    starting rather than failing on an empty result.
    """
    q = _tbl("arena_championships_public_v").select("*")
    if slug:
        rows = q.eq("slug", slug).limit(1).execute().data
        if not rows:
            raise LookupError(f"no championship with slug {slug!r}")
        return rows[0]

    rows = q.eq("status", "running").order("starts_on", desc=True).limit(1).execute().data
    if rows:
        return rows[0]
    rows = (
        _tbl("arena_championships_public_v")
        .select("*")
        .order("starts_on", desc=True)
        .limit(1)
        .execute()
        .data
    )
    if not rows:
        raise LookupError("no championships exist yet — run `cli championship create`")
    log.warning("no running championship; falling back to %s", rows[0].get("slug"))
    return rows[0]


# ── raw pulls ────────────────────────────────────────────────────────────────


def fetch_leaderboard(championship_id: str) -> list[dict[str, Any]]:
    return (
        _tbl("arena_leaderboard_v")
        .select("*")
        .eq("championship_id", championship_id)
        .execute()
        .data
        or []
    )


def fetch_nav_history(championship_id: str) -> list[dict[str, Any]]:
    """Every NAV row for the championship, oldest first.

    A season is one row per agent per session — on the order of a few hundred
    rows for a 3-month window with nine agents, so this is a single pull rather
    than a paged one. PostgREST caps a request at 1000 rows by default, so pages
    are walked explicitly: a silently truncated curve is a wrong graphic, not a
    slow one.
    """
    out: list[dict[str, Any]] = []
    page, size = 0, 1000
    while True:
        rows = (
            _tbl("arena_nav_history_public_v")
            .select("agent_slug, as_of, nav, cumulative_return, daily_return, drawdown, n_positions")
            .eq("championship_id", championship_id)
            .order("as_of")
            .range(page * size, page * size + size - 1)
            .execute()
            .data
            or []
        )
        out.extend(rows)
        if len(rows) < size:
            break
        page += 1
    return out


# ── derived: the broadcast conventions ───────────────────────────────────────


def _sessions(nav_rows: list[dict[str, Any]]) -> list[str]:
    return sorted({str(r["as_of"])[:10] for r in nav_rows if r.get("as_of")})


def _by_agent(nav_rows: list[dict[str, Any]]) -> dict[str, dict[str, dict[str, Any]]]:
    """``{slug: {session: row}}``."""
    out: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for r in nav_rows:
        slug = r.get("agent_slug")
        day = str(r.get("as_of") or "")[:10]
        if slug and day:
            out[slug][day] = r
    return out


def _ranks_at(by_agent: dict[str, dict[str, dict[str, Any]]], session: str) -> dict[str, int]:
    """Rank (1 = leader) at a session, by cumulative return.

    An agent with no row at that session is skipped rather than ranked last —
    it had not started, and inventing a last place for it fabricates a rank
    move the next session.
    """
    vals: list[tuple[str, float]] = []
    for slug, days in by_agent.items():
        row = days.get(session)
        if row is None:
            continue
        vals.append((slug, float(row.get("cumulative_return") or 0.0)))
    vals.sort(key=lambda kv: kv[1], reverse=True)
    return {slug: i + 1 for i, (slug, _) in enumerate(vals)}


def _form(days: dict[str, dict[str, Any]], sessions: list[str], n: int) -> list[str]:
    """Last ``n`` sessions as W / L / D, oldest first."""
    out: list[str] = []
    for s in sessions[-n:]:
        row = days.get(s)
        if row is None:
            continue
        dr = row.get("daily_return")
        if dr is None:
            continue
        dr = float(dr)
        out.append("D" if abs(dr) <= _FLAT_BAND else ("W" if dr > 0 else "L"))
    return out


def _streak(form: list[str]) -> int:
    """Current run as a signed count; 0 when the last session was flat."""
    if not form:
        return 0
    last = form[-1]
    if last == "D":
        return 0
    n = 0
    for ch in reversed(form):
        if ch != last:
            break
        n += 1
    return n if last == "W" else -n


def build_standings(
    *,
    championship_slug: Optional[str] = None,
    form_len: int = 5,
    move_lookback: int = 5,
) -> dict[str, Any]:
    """The full table, ready to render: rank, movement, form, streak.

    ``move_lookback`` is in SESSIONS, not days — five sessions is "since this
    time last week" for a weekday market, and it stays correct across a holiday
    week where five calendar days is not.
    """
    champ = resolve_championship(championship_slug)
    champ_id = champ["id"]

    board = fetch_leaderboard(champ_id)
    if not board:
        raise LookupError(f"no leaderboard rows for championship {champ.get('slug')}")

    nav_rows = fetch_nav_history(champ_id)
    sessions = _sessions(nav_rows)
    by_agent = _by_agent(nav_rows)

    now_session = sessions[-1] if sessions else None
    prev_session = (
        sessions[-(move_lookback + 1)] if len(sessions) > move_lookback else (sessions[0] if sessions else None)
    )
    ranks_prev = _ranks_at(by_agent, prev_session) if prev_session else {}

    board.sort(key=lambda r: float(r.get("total_return") or 0.0), reverse=True)

    rows: list[dict[str, Any]] = []
    for i, r in enumerate(board):
        slug = str(r.get("slug") or "")
        rank = i + 1
        prev_rank = ranks_prev.get(slug)
        form = _form(by_agent.get(slug, {}), sessions, form_len)
        rows.append(
            {
                "rank": rank,
                "slug": slug,
                "name": r.get("name"),
                "tagline": r.get("tagline"),
                "inspiration": r.get("inspiration"),
                "engine": r.get("engine"),
                "nav": float(r.get("nav") or 0.0),
                "return": float(r.get("total_return") or 0.0),
                "drawdown": float(r.get("max_drawdown") or 0.0),
                "sharpe": None if r.get("sharpe") is None else float(r["sharpe"]),
                "trades": int(r.get("closed_trades") or 0),
                "filledOrders": int(r.get("filled_orders") or 0),
                "winRate": None if r.get("win_rate") is None else float(r["win_rate"]),
                "positions": int(r.get("n_positions") or 0),
                # positive = climbed the table
                "move": None if prev_rank is None else prev_rank - rank,
                "form": form,
                "streak": _streak(form),
            }
        )

    return {
        "championship": {
            "slug": champ.get("slug"),
            "name": champ.get("name"),
            "status": champ.get("status"),
            "startsOn": champ.get("starts_on"),
            "endsOn": champ.get("ends_on"),
            "startingCash": float(champ.get("starting_cash") or 0.0),
            "isBacktest": bool(champ.get("is_backtest")),
        },
        "asOf": now_session,
        "session": len(sessions),
        "sessions": len(sessions),
        "moveLookback": move_lookback,
        "rows": rows,
    }


# ── derived: the race ────────────────────────────────────────────────────────


def build_race_keyframes(
    *,
    championship_slug: Optional[str] = None,
    max_keyframes: int = 60,
) -> dict[str, Any]:
    """One keyframe per session: every agent's cumulative return.

    Two things worth knowing:

    * **The metric is return, not NAV.** Nine books between $90k and $103k are
      nine bars of visually identical length; the same nine as −9.9%…+2.9% is a
      race. The renderer draws them diverging from a zero line for the same
      reason.
    * **Values carry forward across a gap.** An agent missing a session (a
      failed run, a late backfill) holds its last known value rather than
      dropping to zero, which would render as a catastrophic crash and an
      instant recovery.

    ``max_keyframes`` evenly downsamples a long season so the race stays legible
    — the last session is always kept, because that is the one the outro freezes
    on and the one every caption is written against.
    """
    champ = resolve_championship(championship_slug)
    nav_rows = fetch_nav_history(champ["id"])
    if not nav_rows:
        raise LookupError(f"no NAV history for championship {champ.get('slug')}")

    sessions = _sessions(nav_rows)
    by_agent = _by_agent(nav_rows)
    slugs = sorted(by_agent.keys())

    if max_keyframes and len(sessions) > max_keyframes:
        step = len(sessions) / max_keyframes
        idx = sorted({int(i * step) for i in range(max_keyframes)} | {len(sessions) - 1})
        sessions = [sessions[i] for i in idx]

    last_seen: dict[str, float] = {s: 0.0 for s in slugs}
    keyframes: list[dict[str, Any]] = []
    for day in sessions:
        entries = []
        for slug in slugs:
            row = by_agent[slug].get(day)
            if row is not None and row.get("cumulative_return") is not None:
                last_seen[slug] = float(row["cumulative_return"])
            entries.append({"id": slug, "value": round(last_seen[slug], 6)})
        keyframes.append({"t": day, "label": _day_label(day), "entries": entries})

    return {
        "championship": champ.get("slug"),
        "sessions": len(sessions),
        "agents": slugs,
        "keyframes": keyframes,
    }


_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _day_label(iso: str) -> str:
    """``2026-09-04`` -> ``Sep 4``."""
    try:
        y, m, d = iso.split("-")
        return f"{_MONTHS[int(m) - 1]} {int(d)}"
    except Exception:
        return iso
