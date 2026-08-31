"""The one thing each briefing asks the reader to do.

Every send used to end in two links that need no account — `/marketscreenings`
and `/pricing` — plus "edit your briefing". A subscriber could act on all three
while logged out, so the email, which is the only surface that reaches all of
them on a schedule, never once created the conditions for an account. 105
verified addresses; 19 accounts.

This module picks a single action per send, and the rule that makes it work is
narrow enough to state in one line: **name something specific that happened to
their own watchlist, and put it behind a door.** Not a feature pitch. The
subscriber is not being sold the product, they are being handed a thing they
already care about which happens to live inside it.

Three consequences of that rule, all of them constraints rather than options:

* **The action is derived, never generic.** "Open NVDA and AMD" is only offered
  when NVDA and AMD actually moved on scored news in the window. A briefing with
  a quiet watchlist gets a quieter, truthful ask — inventing urgency on a day
  when nothing happened is the fastest way to train someone to stop opening the
  email.

* **One action, not three.** The old stack offered a cross-sell, an upgrade and
  a settings link, which is three asks competing for the same click. The
  measured winners elsewhere in this product (screening detail at 22%) ask for
  exactly one thing, about the thing already on screen.

* **The destination must need an account.** Not to *reach* — every action link
  goes through `/auth/briefing`, which creates the account and writes the
  session before it honours the destination, so the rung is bought there. What
  the page has to supply is the reason: `/quote/<SYMBOL>` now hosts the chart
  workspace, and drawing a level on it or asking its AI analyst anything is
  something only an account keeps. That is the wall, and it is worth stepping
  over because the thing behind it is theirs.

Selection is deterministic and reads only what `gather_briefing` already
returned. No LLM, no second query: a send that has to think costs latency on the
fan-out and produces a different answer on a retry.
"""

from __future__ import annotations

import math
from typing import Any

# Sentiment is the direction; article count is the confidence. Multiplying a
# logged count by |sentiment| ranks "three stories all pointing the same way"
# above "one outlier at -0.9", which is the right way round for a person
# deciding what to open first.
def _weight(section: dict[str, Any]) -> float:
    n = int(section.get("article_count") or 0)
    if n <= 0:
        return 0.0
    return abs(float(section.get("avg_sentiment") or 0.0)) * math.log1p(n)


def _movers(briefing: dict[str, Any], limit: int = 2) -> list[dict[str, Any]]:
    ranked = sorted(
        (s for s in (briefing.get("tickers") or []) if (s.get("article_count") or 0) > 0),
        key=_weight,
        reverse=True,
    )
    return ranked[:limit]


def _join(names: list[str]) -> str:
    if len(names) == 1:
        return names[0]
    return f"{', '.join(names[:-1])} and {names[-1]}"


def _direction(section: dict[str, Any]) -> str:
    s = float(section.get("avg_sentiment") or 0.0)
    if s >= 0.15:
        return "positive"
    if s <= -0.15:
        return "negative"
    return "mixed"


def choose_action(briefing: dict[str, Any], *, tickers: list[str],
                  tags: list[str]) -> dict[str, Any]:
    """The single account-requiring action for this send.

    Returns ``{kind, label, sublabel, next_path}``.

    ``next_path`` used to be constrained to `/protected`, on the reasoning that
    a destination which renders logged out cannot move anyone up a rung. That
    reasoning belonged to the old CTAs, which were plain links. Every action
    here is wrapped by :func:`build_signin_url`, so the reader passes through
    `/auth/briefing` — which creates the account and writes the session before
    it honours the destination at all. The rung is bought by the token route,
    not by the page.

    What the destination still has to earn is the *reason* to be signed in.
    `/quote/<SYMBOL>` does: the chart workspace there keeps the levels they
    draw and opens the AI analyst, both only for an account.
    """
    movers = _movers(briefing)

    if movers:
        names = [str(s.get("ticker")) for s in movers]
        counts = sum(int(s.get("article_count") or 0) for s in movers)
        dirs = {_direction(s) for s in movers}
        if len(movers) == 1:
            tone = _direction(movers[0])
            sub = (
                f"{counts} scored stor{'y' if counts == 1 else 'ies'} in the last 24 hours, "
                f"leaning {tone}."
            )
        else:
            # "They disagree" means genuinely opposed, not "one of them is
            # unclear". A -0.30 next to a -0.08 is one clear read and one weak
            # one, and calling that a disagreement is the kind of small
            # overstatement that teaches a reader to discount the whole email.
            if "positive" in dirs and "negative" in dirs:
                sub = f"{counts} scored stories between them — and they disagree."
            elif dirs == {"positive"} or dirs == {"negative"}:
                sub = (f"{counts} scored stories between them, "
                       f"all leaning {next(iter(dirs))}.")
            else:
                sub = f"{counts} scored stories between them in the last 24 hours."
        # The chart is one ticker per page now, so the link lands on the
        # strongest mover — `_movers` is already ranked — even when the email
        # reports on two.
        return {
            "kind": "movers",
            "label": f"Open {names[0]} in your charts",
            "sublabel": sub,
            "next_path": f"/quote/{names[0]}",
        }

    # Nothing moved. The honest ask is the watchlist itself rather than
    # manufactured urgency — a quiet day is information, and an email that
    # cries wolf on one is an email that stops being opened.
    if tickers:
        watch = [t.upper() for t in tickers][:8]
        named = watch[:2]
        return {
            "kind": "quiet",
            "label": f"Open {watch[0]} in your charts",
            "sublabel": (
                "A quiet 24 hours — worth a look at where "
                f"{_join(named)} {'sit' if len(named) > 1 else 'sits'} "
                "going into tomorrow."
            ),
            "next_path": f"/quote/{watch[0]}",
        }

    # Tag-only subscribers have no symbol to open, so the equivalent surface is
    # the trend board rather than a chart. That board used to have its own page;
    # it now lives inside screenings, which is also the best-converting surface
    # in the product.
    if tags:
        return {
            "kind": "themes",
            "label": "Open the trend board for your themes",
            "sublabel": "See how "
                        f"{_join([t for t in tags][:2])} moved against everything else.",
            "next_path": "/protected/workspace",
        }

    return {
        "kind": "empty",
        "label": "Open your workspace",
        "sublabel": "",
        "next_path": "/protected",
    }
