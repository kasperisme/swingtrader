"""Setup timing — the Minervini trade, and what predicts whether it works.

The trade is fixed, not searched: enter on a breakout from a base, stop at the
support underneath it with the risk capped, take profit at 2R. Fixing it is what
makes the research question sharp. With a 2R target against a 1R stop the
outcome is BINARY — the setup either reaches the target before the stop or it
does not — and the breakeven hit rate is exactly 1/3. Every question about
timing then reduces to one number: does this condition lift p above 1/3?

That is a far better-posed question than anything asked earlier in this project.
An information coefficient measures the conditional MEAN of a forward return,
which is the wrong statistic for a payoff that is truncated at -1R and capped at
+2R. A first-passage probability is the right one, and it is the same machinery
the pairs study used for spread convergence.
"""

from .detect import SetupSpec, detect_setups, pseudo_setups
from .outcomes import resolve_setups, OutcomeSpec
from .study import PREREGISTERED_TESTS, breakeven_rate, preregister, run_tests, verdict

__all__ = ["SetupSpec", "detect_setups", "pseudo_setups",
           "OutcomeSpec", "resolve_setups",
           "PREREGISTERED_TESTS", "breakeven_rate", "preregister", "run_tests", "verdict"]
