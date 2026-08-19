"""Flow-Inertia Momentum (FIM) — testing whether momentum is the output of a
persistent flow process rather than a property of price.

Implements the Tier-1 (daily-OHLCV-only) estimator set from the research spec:

    f_t      signed dollar volume — the forcing function
    rho      persistence of that forcing — the inertia coefficient
    T_half   flow memory time, in weeks — the system's relaxation time
    Q_break  dollars required to move price 1 sigma — the inertia to break
    F        realised flow / Q_break — forcing over resistance
    gap      realised move minus flow-implied move — unobserved flow or damping

The order of work is fixed by the spec and is not negotiable: establish panel
evidence that rho x F predicts returns beyond price momentum BEFORE building any
portfolio. If the interaction is not significant with controls in, the programme
stops there.
"""

from .signals import FlowSignals, compute_flow_signals  # noqa: F401
