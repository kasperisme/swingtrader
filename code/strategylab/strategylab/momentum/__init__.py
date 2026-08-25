"""The momentum universe, and everything measured against it.

A standing decision: from here on, strategies are built for ONE universe — the
Minervini trend template on NYSE + NASDAQ. Fixing it buys three things the
earlier studies each lacked in some form:

  * **Reproducibility.** Runs stopped being comparable because the cached
    symbol set grew from 800 to 2,357, so "the 800 most liquid" selected
    different names every restart. A pinned universe carries a fingerprint and
    refuses to run against a panel it was not built on.
  * **A smaller hypothesis space.** Committing to a screen on domain grounds
    rather than fitting it removes dimensions from every downstream search, so
    the same result clears a lower deflated-Sharpe bar.
  * **A stated assumption.** "We only trade Stage-2 uptrends" is a claim
    someone can argue with.

It also carries a known cost, measured rather than assumed. Conditioning on the
trend template roughly triples the raw post-announcement spread — and lifts the
matched no-news control by at least as much, so it adds momentum, not
information. That is why `signals.py` marks momentum as a MANDATORY control and
`ic.py` reports incremental IC after it. A signal that only works because it is
riding the screen must show up here as adding nothing.
"""

from .universe import MomentumUniverse, UniverseSpec, pin_universe
from .signals import REGISTRY, Signal, compute_all
from .ic import ic_report, incremental_ic, signal_correlations

__all__ = ["MomentumUniverse", "UniverseSpec", "pin_universe",
           "REGISTRY", "Signal", "compute_all",
           "ic_report", "incremental_ic", "signal_correlations"]
