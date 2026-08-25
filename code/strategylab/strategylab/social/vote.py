"""The price as a vote among competing analyst models.

The reverse DCF answers "what does this price require" by picking a discount
rate, a terminal growth rate and a margin, and then solving. Every one of those
is a guess, and Crocs showed how much they matter: the implied CAGR moved nine
points across three dates purely on which year's FCF margin was used.

This is the non-parametric alternative, and it is a better question. Analysts
publish competing models of the same company, each with a number attached. The
price sits somewhere in that distribution. **Where it sits is the market voting
on whose model it finds most credible** — no discount rate required, because the
professionals already did that work and disagreed in public.

Crocs, July 2026: Goldman at $95 with a Sell, Baird at $163, price $122.11,
median $138. The market is not "in the range". It is paying well below the
median, which says it leans bearish — and it is simultaneously **declining to
take** Baird's +34%, and **declining to accept** Goldman's -22%.

That two-sided rejection is the useful output, because it gives a category the
corpus veto could not:

    not in the corpus            -> unverifiable, and probably just vague
    in the corpus, price agrees  -> priced in, nothing to do
    in the corpus, price REJECTS -> KNOWN BUT NOT BELIEVED  <- the target

The third cell is where the work belongs. The argument exists, a professional
with a full model published it, and the market has looked at it and declined.
The question stops being "what has nobody thought of" — which asks a language
model to be original, and it is not — and becomes "**is the market right to
reject this specific published case?**" That is answerable, investigable, and
does not depend on the generator having an idea.

**Linking the model to its author.** A target row carries a firm and sometimes an
analyst name; the earnings call names its questioners. Matching them means each
rejected model arrives with its author's own question to management attached —
which is that analyst telling you, in public, the uncertainty their model turns
on. Firm-level matching is used as well as name-level, since roughly half the
target rows carry no name but the covering analyst per firm is stable.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field

import numpy as np

log = logging.getLogger(__name__)

# Targets within this band of the price are treated as the market's own view
# rather than as a disagreement with it.
ENDORSED_BAND = 0.08
# A model has to imply at least this much move to count as REJECTED rather than
# merely different — otherwise every stale target becomes a trade idea.
REJECTED_MIN_MOVE = 0.15
# Below this many published models the distribution is not a vote, it is a
# handful of stale numbers. Three targets spread over four months cannot say
# what the market is declining to pay for, and reading them as a consensus is
# how a thinly-covered name manufactures a false disagreement.
MIN_TARGETS = 5


@dataclass
class Position:
    firm: str
    analyst: str
    target: float
    published: str
    implied_move: float               # from the CURRENT price, not price-when-posted
    stance: str                       # endorsed | rejected_bull | rejected_bear | neutral
    headline: str = ""
    url: str = ""
    call_question: str = ""           # what this analyst asked management
    answered_by: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Vote:
    ticker: str
    price: float
    as_of: str
    n_targets: int
    low: float
    high: float
    median: float
    price_percentile: float           # fraction of targets below the price
    spread_ratio: float               # high / low
    median_gap: float = 0.0           # price / median - 1; the lean measure
    positions: list = field(default_factory=list)
    lean: str = ""
    note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def rejected(self) -> list:
        return [p for p in self.positions if p.stance.startswith("rejected")]

    @property
    def endorsed(self) -> list:
        return [p for p in self.positions if p.stance == "endorsed"]

    @property
    def consensus_position(self):
        """The endorsed model closest to the price — the single best statement
        of what the price contains, and the one worth reconstructing in full."""
        end = self.endorsed or [p for p in self.positions if p.stance == "neutral"]
        if not end:
            return None
        return min(end, key=lambda p: abs(p.implied_move))

    def brief(self) -> str:
        out = [f"THE PRICE AS A VOTE — {self.ticker} @ ${self.price:,.2f} "
               f"(as of {self.as_of})",
               f"  {self.n_targets} published models: ${self.low:,.0f} .. "
               f"${self.high:,.0f} (median ${self.median:,.0f}, "
               f"{self.spread_ratio:.1f}x spread)",
               f"  {self.lean}"]
        end = self.endorsed
        if end:
            out.append(f"  ENDORSED — the market is roughly paying these "
                       f"({len(end)} models). THIS IS WHAT THE PRICE CONTAINS:")
            for p in end[:8]:
                out.append(f"    {p.firm} ${p.target:,.0f} ({p.implied_move:+.0%})"
                           + (f" — {p.analyst}" if p.analyst else ""))
                if p.headline:
                    out.append(f"        \"{p.headline[:86]}\"")
                if p.call_question:
                    out.append(f"        asked management: \"{p.call_question[:130]}\"")
        neu = [p for p in self.positions if p.stance == "neutral"]
        if neu:
            out.append(f"  NEAR-CONSENSUS ({len(neu)} more within 8-15% of price): "
                       + ", ".join(f"{p.firm} ${p.target:,.0f}" for p in neu[:8]))
        rej = self.rejected
        if rej:
            out.append("\n  REJECTED — published, therefore known, and the price "
                       "declines to pay it. This is the investigable set:")
            for p in rej:
                arrow = "BULL" if p.stance == "rejected_bull" else "BEAR"
                out.append(f"    [{arrow}] {p.firm} ${p.target:,.0f} "
                           f"({p.implied_move:+.0%}) — {p.analyst or 'analyst unnamed'}"
                           f"  {p.published}")
                if p.headline:
                    out.append(f"           \"{p.headline[:88]}\"")
                if p.call_question:
                    out.append(f"           asked management: "
                               f"\"{p.call_question[:150]}\"")
        if self.note:
            out.append(f"\n  {self.note}")
        return "\n".join(out)


def _match_question(firm: str, analyst: str, questions: list,
                    firm_roster: dict) -> tuple[str, str]:
    """Find this analyst's question on the call, by name then by firm."""
    if analyst:
        surname = analyst.split()[-1].lower()
        for q in questions:
            if q.analyst.split()[-1].lower() == surname:
                return q.text, q.answered_by
    who = firm_roster.get(firm)
    if who:
        for q in questions:
            if q.analyst == who:
                return q.text, q.answered_by
    return "", ""


def build(view, price: float) -> Vote:
    """`view` is an `analyst.AnalystView`; `price` the current quote."""
    tg = list(view.targets)
    if tg and price and len(tg) < MIN_TARGETS:
        vals_ = np.array([t.target for t in tg], dtype=float)
        return Vote(ticker=view.ticker, price=price, as_of=view.as_of,
                    n_targets=len(tg), low=float(vals_.min()),
                    high=float(vals_.max()), median=float(np.median(vals_)),
                    price_percentile=float(np.mean(vals_ < price)),
                    spread_ratio=float(vals_.max() / vals_.min()) if vals_.min() else 0.0,
                    positions=[], lean="insufficient coverage",
                    note=(f"REFUSED: only {len(tg)} published target(s) in the window "
                          f"(need {MIN_TARGETS}). A handful of stale numbers is not a "
                          f"vote, and treating it as one invents a disagreement on a "
                          f"name nobody is arguing about."))
    if not tg or not price:
        return Vote(ticker=view.ticker, price=price or 0.0, as_of=view.as_of,
                    n_targets=0, low=0, high=0, median=0, price_percentile=0.0,
                    spread_ratio=0.0, note="no published targets in the window")

    # Firm -> the analyst who asked on the call, learned from the NAMED target
    # rows. Half the rows carry no name, but the covering analyst per firm is
    # stable, so one named row teaches the firm's questioner for all of them.
    firm_roster: dict[str, str] = {}
    for t in tg:
        if not t.analyst:
            continue
        surname = t.analyst.split()[-1].lower()
        for q in view.questions:
            if q.analyst.split()[-1].lower() == surname:
                firm_roster[t.company] = q.analyst

    vals = np.array([t.target for t in tg], dtype=float)
    lo, hi, med = float(vals.min()), float(vals.max()), float(np.median(vals))
    pct = float(np.mean(vals < price))

    # Unadjusted-split guard, at the DISTRIBUTION level.
    #
    # Monster returned eleven targets, every one of them a "rejected bull", and
    # NOTHING endorsed — which is the tell. A real target distribution brackets
    # the price; one that sits entirely to one side at a clean multiple is a
    # feed that has not been adjusted for a stock split. The single-target check
    # in `expectations.py` catches this per number; here the whole set has to be
    # refused, because emitting eleven bogus "known but not believed" bull cases
    # would send the investigation stage after nothing.
    ratio = med / price if price else 0.0
    # Near-integer split factors are the common case, but not the only one:
    # O'Reilly's 15:1 split left a median target 16x the price, and Carvana
    # showed 4.5-6.7x. Checking only 2/3/4 let those through and they landed
    # in the extreme bucket of a backtest, where they looked like the signal.
    # A plain implausibility bound catches whatever the factor list misses.
    for f_ in (2.0, 3.0, 4.0, 5.0, 10.0, 15.0, 20.0,
               0.5, 1.0 / 3.0, 0.25, 0.2, 0.1):
        if abs(ratio / f_ - 1.0) <= 0.08:
            return Vote(
                ticker=view.ticker, price=price, as_of=view.as_of,
                n_targets=len(tg), low=lo, high=hi, median=med,
                price_percentile=pct, spread_ratio=(hi / lo) if lo else 0.0,
                median_gap=ratio - 1.0, positions=[], lean="unusable",
                note=(f"REFUSED: the median target ${med:,.0f} is {ratio:.2f}x the "
                      f"${price:,.2f} price — within 8% of a {f_:g}x split factor, so "
                      f"the target feed is almost certainly unadjusted. No positions "
                      f"emitted; a split artefact would otherwise read as {len(tg)} "
                      f"published bull cases the market rejects."))

    positions = []
    for t in tg:
        move = t.target / price - 1.0
        if abs(move) <= ENDORSED_BAND:
            stance = "endorsed"
        elif move >= REJECTED_MIN_MOVE:
            stance = "rejected_bull"
        elif move <= -REJECTED_MIN_MOVE:
            stance = "rejected_bear"
        else:
            stance = "neutral"
        q, by = _match_question(t.company, t.analyst, view.questions, firm_roster)
        positions.append(Position(
            firm=t.company, analyst=t.analyst, target=t.target,
            published=t.published, implied_move=move, stance=stance,
            headline=t.headline, url=t.url, call_question=q, answered_by=by))
    positions.sort(key=lambda p: -p.target)

    # Lean is measured against the MEDIAN, not by counting targets above and
    # below. Crocs sits at the 42nd percentile — which reads as "mid-
    # distribution, no clear side" — while the price is 12% below the median and
    # six of twelve models imply +23% or more. The count is misled by a cluster
    # at $150: the targets above are far above, the ones below are close. What
    # matters is how far the price is from the middle, not how many sit on each
    # side of it.
    gap = price / med - 1.0 if med else 0.0
    if gap <= -0.08:
        lean = (f"the market is {abs(gap):.0%} BELOW the median target — it leans "
                f"bearish against the published set")
    elif gap >= 0.08:
        lean = (f"the market is {gap:.0%} ABOVE the median target — it leans bullish "
                f"against the published set")
    else:
        lean = (f"the market is within {abs(gap):.0%} of the median target — it broadly "
                f"agrees with the middle of the published set")
    lean += f" (price at the {pct:.0%} percentile by count)"

    n_bull = sum(1 for p in positions if p.stance == "rejected_bull")
    n_bear = sum(1 for p in positions if p.stance == "rejected_bear")
    note = ""
    if n_bull and n_bear:
        note = (f"The price rejects BOTH tails — {n_bull} bull case(s) it will not "
                f"pay for and {n_bear} bear case(s) it will not accept. Both are "
                f"published, so both are known; the question for each is not "
                f"whether anyone has thought of it but whether the market is right "
                f"to decline it.")
    elif n_bull:
        note = (f"{n_bull} published bull case(s) the price will not pay for. Known, "
                f"not believed.")
    elif n_bear:
        note = (f"{n_bear} published bear case(s) the price will not accept.")
    return Vote(ticker=view.ticker, price=price, as_of=view.as_of, n_targets=len(tg),
                low=lo, high=hi, median=med, price_percentile=pct,
                # Set here as well as on the refusal path above. It was only set
                # there, so every persisted row carried median_gap = 0.0 while
                # the `lean` string built from the same quantity read "12% BELOW
                # the median" — a field that is silently zero next to prose that
                # is correct is worse than one that is obviously missing.
                median_gap=(price / med - 1.0) if med else 0.0,
                spread_ratio=(hi / lo) if lo else 0.0, positions=positions,
                lean=lean, note=note)
