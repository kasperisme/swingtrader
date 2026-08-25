"""A thesis is a causal chain, not a correlation.

The discovery loop (`strategylab/discover/`) tests *hypotheses*: atomic claims
of the form "feature X, transformed, predicts outcome Y at horizon H". That
grammar is finite and exhaustible, which is exactly what makes a null terminal
there. But it can only ever test what is already in the feature bank, and it has
no way to represent *why* a signal should work.

A **thesis** is the other kind of object. It is a mechanism — a story about how
information becomes price — decomposed into **links**, each of which is a
separately falsifiable claim, arranged so that the whole chain is only as strong
as its weakest link.

    L1 ── L2 ── L3 ── L4          every link must hold
     │     │     │     │
     └─────┴─────┴─────┴──▶ one FAILS ⇒ the thesis FAILS

Three properties fall out of that structure, and they are the entire reason for
this module:

* **A broken link is terminal.** You do not need to test L3 and L4 once L2 has
  failed; the mechanism cannot work. A grid search has no such shortcut because
  it has no notion of a mechanism.

* **Links can be ordered by price.** Each link declares what data it needs and
  what that data costs. The lab tests the *cheapest link that could kill the
  thesis* first, so a dead thesis dies before anyone buys a data subscription.
  This is the two-rung ladder in `discover/execute.py` generalised from "cheap
  statistic then expensive statistic" to "cheap evidence then expensive
  evidence".

* **The null is written down before the test.** Every link carries its `null`
  (what the world looks like if the claim is false), its matched `control`, and
  its `kill` condition — all pre-registered. A link without a stated kill
  condition cannot be added to a thesis; `Link.__post_init__` refuses it.

## On the significance bar

`discover.loop.significance_bar` raises the |t| a result must clear as the trial
count grows, because the maximum of N noise draws grows like sqrt(2 ln N). That
logic applies here too, but the count it should use is *not* obvious, so it is
made explicit rather than left to accident:

* A link with a **pre-registered direction** (`direction != 0`), anchored to a
  published result, is ONE test. It does not inherit the lab's trial count,
  because it is not the outcome of a search — it was specified in advance and
  can only be confirmed or refuted.
* A link with `direction == 0` is **exploratory**. Its bar counts every arm run
  inside that thesis, so a thesis that quietly sweeps twenty variants pays for
  twenty.
* The lab-wide count is reported next to every verdict regardless, so a reader
  can always see how much searching produced the number in front of them.

Getting this wrong in either direction is a real failure: inheriting the global
count would make an honest pre-registered replication unfalsifiable, and
ignoring the local count would let a thesis launder a grid search as a mechanism.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

import numpy as np

# What a link's evidence costs to obtain. The lab tests in this order, so a
# thesis dies on free data before anyone is asked to pay for the next tier.
COST_TIERS = ("free", "cheap", "paid", "manual")
COST_RANK = {c: i for i, c in enumerate(COST_TIERS)}

# Terminal states for a link.
PENDING = "PENDING"            # registered, not yet run
HOLDS = "HOLDS"                # cleared the bar, placebo clean, control beaten
FAILS = "FAILS"                # measured, and the claim is refuted — terminal
INCONCLUSIVE = "INCONCLUSIVE"  # measured, too little power to decide
BLOCKED = "BLOCKED"            # the data this link needs does not exist yet
SKIPPED = "SKIPPED"            # an upstream link already failed


@dataclass(frozen=True)
class Link:
    """One falsifiable claim inside a causal chain.

    `null`, `control` and `kill` are mandatory prose, not decoration. They are
    what turns "we looked and it seemed to work" into a test that can come back
    negative, and they must be written before the link runs.
    """

    id: str                       # "L2" — stable, used as the registry key
    claim: str                    # the causal assertion, in one sentence
    null: str                     # what the data looks like if the claim is false
    outcome: str                  # the quantity actually measured
    control: str                  # the matched control or placebo
    kill: str                     # the pre-registered condition that refutes it
    data: tuple[str, ...]         # data dependencies, by name
    cost: str = "free"            # COST_TIERS — sets the testing order
    direction: int = 0            # +1 / -1 pre-registered sign; 0 = exploratory
    anchor: str = ""              # published result this link replicates, if any
    pivotal: bool = False         # the link most likely to kill the thesis; runs
                                  # first within its cost tier

    def __post_init__(self) -> None:
        if self.cost not in COST_RANK:
            raise ValueError(f"{self.id}: cost must be one of {COST_TIERS}")
        for fieldname in ("claim", "null", "control", "kill"):
            if not str(getattr(self, fieldname)).strip():
                raise ValueError(
                    f"{self.id}: '{fieldname}' is empty. A link with no stated "
                    f"{fieldname} cannot be refuted, so it is not a test.")
        if self.direction not in (-1, 0, 1):
            raise ValueError(f"{self.id}: direction must be -1, 0 or +1")

    @property
    def preregistered(self) -> bool:
        """A directional claim anchored in advance is one test, not a search."""
        return self.direction != 0

    def key(self, thesis_id: str) -> str:
        return hashlib.sha1(f"{thesis_id}:{self.id}".encode()).hexdigest()[:16]


@dataclass
class LinkResult:
    """What running a link produced. Mirrors `discover.registry.ScoredHypothesis`
    so both can share reporting, but carries a verdict rather than a flag."""

    link_id: str
    verdict: str = PENDING
    effect: float = float("nan")
    t_stat: float = float("nan")
    n_obs: int = 0
    placebo_t: float = float("nan")
    control_effect: float = float("nan")
    bar: float = float("nan")
    vault_effect: float = float("nan")
    vault_t: float = float("nan")
    note: str = ""
    detail: dict = field(default_factory=dict)

    @property
    def terminal(self) -> bool:
        return self.verdict in (FAILS,)


@dataclass(frozen=True)
class Thesis:
    """A mechanism, decomposed into links that can each kill it."""

    id: str
    title: str
    mechanism: str                # the causal story, one paragraph
    links: tuple[Link, ...]
    source: str = ""              # literature / practitioner anchor
    notes: str = ""

    def __post_init__(self) -> None:
        seen = set()
        for ln in self.links:
            if ln.id in seen:
                raise ValueError(f"{self.id}: duplicate link id {ln.id!r}")
            seen.add(ln.id)
        if not self.links:
            raise ValueError(f"{self.id}: a thesis with no links tests nothing")

    def test_order(self) -> list[Link]:
        """Cheapest first; pivotal links first within a tier; then causal order.

        Declaration order is the *causal* order, which is what makes a thesis
        readable, but it is rarely the right order to test in. The link most
        likely to kill the chain should be measured first so the money is never
        spent, and that link is usually in the middle of the story rather than
        at its start. `pivotal` names it explicitly instead of relying on
        whoever wrote the thesis to also have written it in test order.
        """
        idx = {ln.id: i for i, ln in enumerate(self.links)}
        return sorted(self.links,
                      key=lambda ln: (COST_RANK[ln.cost], not ln.pivotal, idx[ln.id]))

    def verdict(self, results: dict[str, LinkResult]) -> tuple[str, str]:
        """Chain semantics. Returns (verdict, one-line reason).

        A chain FAILS on any broken link and only HOLDS when every link holds —
        there is no partial credit, because a mechanism with a missing step is
        not a mechanism.

        A refutation is checked BEFORE anything else, and the reason it has to
        be is the entire economics of this module. Walking the links in causal
        order and returning on the first PENDING would report a thesis whose
        pivotal link has just been refuted as "PENDING — L1 not yet run", which
        invites someone to go and run L1. But the point of ordering by cost is
        that the cheap decisive link runs FIRST and the rest never run at all;
        a verdict that hides a dead chain behind an unrun upstream link spends
        exactly the money the design exists to save.
        """
        broken = [ln for ln in self.links
                  if (r := results.get(ln.id)) is not None and r.verdict == FAILS]
        if broken:
            ln = broken[0]
            return FAILS, f"{ln.id} refuted: {ln.kill}"
        for ln in self.links:
            r = results.get(ln.id)
            if r is None or r.verdict == PENDING:
                return PENDING, f"{ln.id} not yet run"
            if r.verdict == BLOCKED:
                return BLOCKED, f"{ln.id} needs data not wired: {', '.join(ln.data)}"
            if r.verdict == INCONCLUSIVE:
                return INCONCLUSIVE, f"{ln.id} underpowered (n={r.n_obs})"
        return HOLDS, "every link holds"

    def data_requirements(self) -> dict[str, list[str]]:
        """Data name -> the links that need it, so a build order is obvious."""
        out: dict[str, list[str]] = {}
        for ln in self.links:
            for d in ln.data:
                out.setdefault(d, []).append(ln.id)
        return out


def link_bar(link: Link, local_trials: int, base: float = 2.0,
             margin: float = 0.5) -> float:
    """The |t| this link must clear.

    A pre-registered directional link is one test and gets the base bar. An
    exploratory link pays for every arm run inside its own thesis. See the
    module docstring for why the lab-wide count is deliberately not used here.
    """
    if link.preregistered:
        return float(base)
    n = max(1, int(local_trials))
    return float(max(base, np.sqrt(2.0 * np.log(max(n, 2))) + margin))
