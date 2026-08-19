"""Momentum as a long-short factor portfolio — the object the literature studies.

Almost every published momentum result is measured on WML ("winners minus
losers"): rank the cross-section on past return, go long the top decile and
short the bottom, equal- or value-weight, rebalance monthly, no stops, no
position limits, free resizing.

That is not the same object as a swing strategy with entries, stops and a
holding period, and a result established on one does not automatically hold on
the other. Building WML here makes the difference testable rather than
assumed — and lets a claimed improvement be replicated on its native object
before anyone tries to port it.
"""

from .wml import WMLResult, build_wml, scale_variants  # noqa: F401
