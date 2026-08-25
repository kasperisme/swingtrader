"""News repricing — trading the effect that killed the pairs book.

The FDP study found that divergences carrying firm-specific news do NOT
converge: the spread moves to a new level and stays there. That is a statement
about *repricing*, and it is the mechanism behind post-earnings-announcement
drift. The same effect, traded from the other side.

The move to a directional event book is not a change of subject, it is where
this project's own evidence points. Across two research programmes the only
effect that replicated, survived falsification and confirmed on sealed data was
the news axis. And the economics are different in the way that matters: a
26bp round trip against a 37bp pairs edge is 70% of the gross; against a
multi-percent post-announcement drift it is a rounding error.
"""

from .eventstudy import EventSpec, build_events, pseudo_events
from .study import PREREGISTERED_TESTS, preregister, run_tests, verdict

__all__ = ["EventSpec", "build_events", "pseudo_events",
           "PREREGISTERED_TESTS", "preregister", "run_tests", "verdict"]
