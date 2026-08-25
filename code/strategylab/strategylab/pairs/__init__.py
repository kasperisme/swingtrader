"""Flow-Discriminated Pairs (FDP) — classify divergences, then trade the classes.

The claim under test is not "spreads mean-revert" (they do, weakly, and the
literature has already arbitraged most of it away). It is narrower: *the kind of
shock that caused a divergence predicts whether it converges*. Engelberg, Gao &
Jagannathan (2009) established the news axis of that taxonomy; the flow axis is
the untested half.

This package implements the runnable part — pair formation, divergence events,
and the news-axis discriminator (H1), which is the positive control the earlier
flow-inertia work never had. The flow axis (H2-H4) needs 13F/reconstitution
data that is not wired up here; `research/FDP-STAGE1-FINDINGS.md` says so.
"""

from .formation import FormationSpec, Pair, form_pairs
from .events import EventSpec, DivergenceEvent, collect_events
from .discriminate import RegimeSpec, classify

__all__ = ["FormationSpec", "Pair", "form_pairs", "EventSpec", "DivergenceEvent",
           "collect_events", "RegimeSpec", "classify"]
