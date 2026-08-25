"""A research loop that can return "no alpha" as a finished answer.

The purpose is iteration — propose, test, learn, propose again — but a loop that
runs "until it finds alpha" finds alpha with probability 1, because the maximum
of N noise draws grows without bound. Every unguarded result produced in this
project looked real until a control killed it: the trend screen appeared to
triple post-announcement drift, a rolling anchor produced 81% spread convergence
out of random walks, two conditioners appeared to time the breakout. The
discipline is not decoration around the search, it IS the search.

So three properties are built in rather than bolted on:

  * **The bar rises with the trial count.** Significance is measured against
    `sqrt(2 ln N)` — the expected maximum |t| of N independent null draws — not
    against a fixed 2.0. The thousandth hypothesis has to be visibly better than
    the tenth to count as the same discovery.
  * **Every hypothesis is registered before it runs**, including the ones that
    fail, because a bar computed from the hypotheses you remember is not a bar.
  * **Termination is defined.** The space is finite and enumerable, so the loop
    ends either with a confirmed finding or with "n hypotheses tested, none
    cleared the bar" — which is a result, not a failure to produce one.
"""

from .hypothesis import Hypothesis, HypothesisSpace, SIGNAL_PRIMITIVES, TRANSFORMS
from .registry import Registry, ScoredHypothesis
from .execute import evaluate
from .loop import DiscoveryLoop, LoopConfig, significance_bar

__all__ = ["Hypothesis", "HypothesisSpace", "SIGNAL_PRIMITIVES", "TRANSFORMS",
           "Registry", "ScoredHypothesis", "evaluate",
           "DiscoveryLoop", "LoopConfig", "significance_bar"]
