"""
storylines — the deterministic story finder for arena creatives.

A weekly table graphic that just says "here is the table" is a report. What
makes a sports table interesting is the *sentence someone puts on top of it* —
and that sentence is nearly always one of a small, recurring set: the leader
changed, an underdog is embarrassing a favourite, someone is on a run, someone
is in freefall.

So the set is enumerated here as detectors rather than left to the director's
judgement each week. Two reasons:

1. **The best story is often the least flattering one.** A human picking a hook
   week after week drifts towards the flattering read; a detector that fires on
   "a random number generator is beating three of our AI agents" does not get
   embarrassed. That hook is also the most credible thing this project can say,
   so it must not be quietly skippable.
2. **An event-triggered format needs a trigger.** The same detectors decide
   whether an UPSET ALERT is worth rendering at all, which is what keeps a
   "breaking" strap from firing on a day when nothing broke.

Each detector returns a candidate with a ``priority`` (higher wins) and a
ready-to-use ``headline`` in the broadcast register. The skill may rewrite the
words; it should not have to find the story.

``detail`` is always literally true against the numbers passed in. Nothing here
extrapolates, predicts, or describes a paper result as an achievable return.
"""

from __future__ import annotations

from typing import Any, Optional

#: Below this many closed trades a win rate is noise, not a story.
_MIN_TRADES_FOR_WINRATE = 5

#: A drawdown story needs a real hole, not a wobble.
_BLOWUP_RETURN = -0.05

#: Two agents inside this many return-points are "level on points".
_TIGHT_BAND = 0.005  # 0.5pt


def _ord(n: int) -> str:
    """1 -> 1st, 2 -> 2nd, 11 -> 11th. League position, written the way it is said."""
    if 10 <= n % 100 <= 20:
        return f"{n}th"
    suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _pt(x: float) -> str:
    """Return as table points, the way a league table prints them."""
    return f"{x * 100:+.2f}%"


def _controls(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in rows if str(r.get("engine") or "").lower() == "deterministic"]


def _llms(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in rows if str(r.get("engine") or "").lower() != "deterministic"]


def detect(standings: dict[str, Any]) -> list[dict[str, Any]]:
    """Every storyline the current table supports, best first."""
    rows: list[dict[str, Any]] = standings.get("rows") or []
    if not rows:
        return []

    out: list[dict[str, Any]] = []
    leader = rows[0]
    bottom = rows[-1]
    controls = _controls(rows)
    llms = _llms(rows)

    # ── 1. A control is top of the table ────────────────────────────────────
    if leader in controls:
        beaten = len([r for r in llms if r["return"] < leader["return"]])
        out.append(
            {
                "key": "control_leads",
                "priority": 100,
                "agents": [leader["slug"]],
                "headline": f"{leader['name']} is top of the table. It has made one trade.",
                "detail": (
                    f"{leader['name']} — the control that buys SPY and does nothing — leads "
                    f"at {_pt(leader['return'])}, ahead of {beaten} AI strategies."
                ),
            }
        )

    # ── 2. The coinflip is beating thinking agents ──────────────────────────
    coin = next((r for r in rows if r["slug"] == "burton-malarkey"), None)
    if coin:
        beaten = [r for r in llms if r["return"] < coin["return"]]
        if beaten:
            out.append(
                {
                    "key": "coinflip_beats_llms",
                    "priority": 95 + len(beaten),
                    "agents": [coin["slug"], *[r["slug"] for r in beaten]],
                    "headline": (
                        f"A random number generator is beating "
                        f"{len(beaten)} of our AI strategies."
                    ),
                    "detail": (
                        f"{coin['name']} picks at random on a fixed seed and sits "
                        f"{_ord(coin['rank'])} at {_pt(coin['return'])} — above "
                        + ", ".join(r["name"] for r in beaten)
                        + "."
                    ),
                }
            )

    # ── 3. Freefall ─────────────────────────────────────────────────────────
    if bottom["return"] <= _BLOWUP_RETURN:
        gap = leader["return"] - bottom["return"]
        out.append(
            {
                "key": "freefall",
                "priority": 80,
                "agents": [bottom["slug"]],
                "headline": f"{bottom['name']} is {gap * 100:.1f} points adrift.",
                "detail": (
                    f"{bottom['name']} sits bottom at {_pt(bottom['return'])} with a worst "
                    f"drawdown of {bottom['drawdown'] * 100:.1f}%."
                ),
            }
        )

    # ── 4. Nothing is landing ───────────────────────────────────────────────
    for r in rows:
        if r["trades"] >= _MIN_TRADES_FOR_WINRATE and (r.get("winRate") or 0) == 0:
            out.append(
                {
                    "key": "no_wins",
                    "priority": 78,
                    "agents": [r["slug"]],
                    "headline": f"{r['name']}: {r['trades']} closed trades, {r['trades']} losers.",
                    "detail": (
                        f"{r['name']} has closed {r['trades']} trades this season and won none "
                        f"of them. It is {_ord(r['rank'])} at {_pt(r['return'])}."
                    ),
                }
            )

    # ── 5. The best AI on the board ─────────────────────────────────────────
    if llms:
        best = llms[0]
        above = [r for r in rows if r["rank"] < best["rank"]]
        out.append(
            {
                "key": "best_llm",
                "priority": 60 if above else 90,
                "agents": [best["slug"]],
                "headline": (
                    f"{best['name']} leads the field."
                    if not above
                    else f"{best['name']} is the best of the thinking agents."
                ),
                "detail": (
                    f"{best['name']} — {best['tagline']} — is {_ord(best['rank'])} at "
                    f"{_pt(best['return'])} over {best['trades']} closed "
                    f"trade{'' if best['trades'] == 1 else 's'}."
                ),
            }
        )

    # ── 6. Biggest climber / faller ─────────────────────────────────────────
    movers = [r for r in rows if r.get("move")]
    if movers:
        climber = max(movers, key=lambda r: r["move"])
        faller = min(movers, key=lambda r: r["move"])
        look = standings.get("moveLookback", 5)
        if climber["move"] > 0:
            out.append(
                {
                    "key": "climber",
                    "priority": 55,
                    "agents": [climber["slug"]],
                    "headline": f"{climber['name']} is up {climber['move']} places.",
                    "detail": (
                        f"{climber['name']} has climbed {climber['move']} places in "
                        f"{look} sessions to {_ord(climber['rank'])}."
                    ),
                }
            )
        if faller["move"] < 0:
            out.append(
                {
                    "key": "faller",
                    "priority": 54,
                    "agents": [faller["slug"]],
                    "headline": f"{faller['name']} has dropped {abs(faller['move'])} places.",
                    "detail": (
                        f"{faller['name']} has fallen {abs(faller['move'])} places in "
                        f"{look} sessions to {_ord(faller['rank'])}."
                    ),
                }
            )

    # ── 7. On a run ─────────────────────────────────────────────────────────
    hot = max(rows, key=lambda r: r.get("streak") or 0)
    if (hot.get("streak") or 0) >= 3:
        out.append(
            {
                "key": "streak",
                "priority": 50,
                "agents": [hot["slug"]],
                "headline": f"{hot['name']} has won {hot['streak']} sessions in a row.",
                "detail": f"{hot['name']} is {_ord(hot['rank'])} at {_pt(hot['return'])} and rising.",
            }
        )

    # ── 8. Level on points ──────────────────────────────────────────────────
    for a, b in zip(rows, rows[1:]):
        if abs(a["return"] - b["return"]) <= _TIGHT_BAND:
            out.append(
                {
                    "key": "tight",
                    "priority": 45,
                    "agents": [a["slug"], b["slug"]],
                    "headline": f"{a['name']} and {b['name']} cannot be separated.",
                    "detail": (
                        f"{_pt(a['return'])} against {_pt(b['return'])} — "
                        f"{abs(a['return'] - b['return']) * 100:.2f} points between them."
                    ),
                }
            )
            break

    out.sort(key=lambda d: d["priority"], reverse=True)
    return out


def headline(standings: dict[str, Any], prefer: Optional[str] = None) -> dict[str, Any]:
    """The one storyline to strap across the top.

    ``prefer`` pins a detector key when the director wants a specific angle —
    the default is whatever the table itself makes loudest.
    """
    found = detect(standings)
    if not found:
        return {
            "key": "table",
            "priority": 0,
            "agents": [],
            "headline": "Nine AI agents. $100,000 each. One market.",
            "detail": "The board updates every session.",
        }
    if prefer:
        for c in found:
            if c["key"] == prefer:
                return c
    return found[0]
