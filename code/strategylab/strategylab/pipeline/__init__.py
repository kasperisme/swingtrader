"""The middle layer — and first, whether one can exist.

The pipeline as it stands is two steps: a screen that says which names are
eligible, and a setup rule that says when to buy one. The proposal is a third
step in between, selecting the names most likely to outperform before any setup
is looked for.

Before building that layer it is worth asking whether it is possible, and the
question can be posed far more strongly than anything asked so far. Every test
in this project has been univariate — one signal, one horizon, does its rank
correlate with a forward return. Twenty-eight of those, plus 440 single
hypotheses in the discovery loop. None of them can see an INTERACTION: a feature
that only matters when another is high, a rule that only holds in one regime.

A joint model can. So `attainability.py` fits one on every feature at once and
reports two numbers that bound the whole question:

    the ORACLE   — what perfect selection would have earned, the ceiling on any
                   middle layer whatsoever
    the AUC      — how much of that ceiling is reachable from information
                   available at the time, measured out of sample

If a gradient-boosted model over twenty-plus features cannot beat a coin on
held-out data, no middle layer exists to be built, and that is worth knowing
before building one.
"""

from .attainability import (LabelSpec, build_dataset, oracle_bound,
                            learnability_test)

__all__ = ["LabelSpec", "build_dataset", "oracle_bound", "learnability_test"]
