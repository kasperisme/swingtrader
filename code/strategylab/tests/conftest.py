import numpy as np
import pandas as pd
import pytest

from strategylab.data.prices import Panel


def synthetic_panel(n_days: int = 900, n_symbols: int = 40, seed: int = 0) -> Panel:
    """Geometric random walks with a mild upward drift and realistic volume.

    Deterministic given `seed`, so a test can perturb one region of the panel
    and attribute any behaviour change to that region alone.
    """
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2015-01-01", periods=n_days).values.astype("datetime64[D]")
    drift = rng.normal(0.0004, 0.0004, n_symbols)
    vol = rng.uniform(0.012, 0.035, n_symbols)
    shocks = rng.normal(drift, vol, (n_days, n_symbols))
    close = 30.0 * np.exp(np.cumsum(shocks, axis=0)) * rng.uniform(0.5, 3.0, n_symbols)

    intraday = np.abs(rng.normal(0, 0.012, (n_days, n_symbols)))
    high = close * (1 + intraday)
    low = close * (1 - intraday)
    open_ = np.clip(close * (1 + rng.normal(0, 0.006, (n_days, n_symbols))), low, high)
    volume = rng.lognormal(13.5, 0.55, (n_days, n_symbols))

    return Panel(dates=dates, symbols=[f"SYM{i:03d}" for i in range(n_symbols)],
                 open=open_, high=high, low=low, close=close, volume=volume)


@pytest.fixture
def panel():
    return synthetic_panel()
