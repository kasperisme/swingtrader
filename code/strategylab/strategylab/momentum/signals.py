"""The signal registry.

Every candidate predictor this project has produced, expressed the same way: a
cross-sectional score per name per day, higher meaning more attractive. Not
trades, not positions — scores. The combination happens once, downstream, so
signals can be compared and stacked instead of each spawning its own book.

**Momentum is a mandatory control.** `mom_12_1` and `rs_rank` carry
`is_control=True`, and `ic.py` reports every other signal's IC *after* them.
That is not a stylistic preference, it is the direct lesson of the last
experiment: conditioning post-announcement drift on the trend template tripled
its raw spread and lifted the matched no-news control by more, so the apparent
improvement was momentum wearing a different name. Any signal on this universe
is exposed to the same confusion by construction, because the universe IS a
momentum screen. Measuring incremental-to-momentum is the only way the system
can tell a new signal from a re-labelled old one.

Signs are set so that HIGH always means "expected to outperform". A reversal
signal is therefore the NEGATIVE of the recent return.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

import numpy as np

log = logging.getLogger(__name__)


@dataclass
class Signal:
    name: str
    fn: Callable                 # (bank) -> (n_days, n_symbols) float
    family: str
    description: str
    is_control: bool = False


def _neg(x: np.ndarray) -> np.ndarray:
    return -x


# ----------------------------------------------------------------------
def _mom_12_1(bank):
    return bank.get("momo_12m_1m")


def _rs_rank(bank):
    return bank.get("rs_rank")


def _residual_momentum(bank):
    return bank.get("residual_momentum")


def _proximity_high(bank):
    return -bank.get("pct_below_52w_high")


def _extension(bank):
    """Distance above the 50-day MA. Ambiguous by design: momentum says more is
    better, mean reversion says extended names snap back. The registry does not
    take a view; the IC table does."""
    return bank.get("dist_from_sma", length=50)


def _reversal(days: int):
    def f(bank):
        return -bank.get("ret", days=days)
    return f


def _volume_confirmation(bank):
    return bank.get("up_down_volume")


def _volume_surge(bank):
    return bank.get("volume_ratio")


def _tightness(bank):
    """Volatility contraction: tighter is better, so the sign is flipped."""
    return -bank.get("tightness")


def _squeeze(bank):
    return bank.get("squeeze")


def _low_adr(bank):
    return -bank.get("adr_pct")


def _info_discreteness(bank):
    """Da, Gurun & Warachka: momentum delivered in many small moves persists;
    momentum delivered in a few jumps does not."""
    return bank.get("info_discreteness")


def _rs_line_high(bank):
    return bank.get("rs_line_high")


def _gap_fade(bank):
    return -bank.get("gap_pct")


def _above_low(bank):
    return bank.get("pct_above_52w_low")


REGISTRY: dict[str, Signal] = {
    s.name: s for s in [
        # --- the mandatory controls -------------------------------------
        Signal("mom_12_1", _mom_12_1, "momentum",
               "12-month return skipping the most recent month", is_control=True),
        Signal("rs_rank", _rs_rank, "momentum",
               "relative-strength percentile vs the benchmark", is_control=True),
        # --- momentum variants ------------------------------------------
        Signal("residual_momentum", _residual_momentum, "momentum",
               "momentum after removing the market component"),
        Signal("proximity_52w_high", _proximity_high, "momentum",
               "closeness to the 52-week high"),
        Signal("pct_above_52w_low", _above_low, "momentum",
               "distance already travelled off the 52-week low"),
        Signal("rs_line_high", _rs_line_high, "momentum",
               "relative-strength line making new highs"),
        Signal("info_discreteness", _info_discreteness, "momentum",
               "momentum delivered smoothly rather than in jumps"),
        # --- reversal ----------------------------------------------------
        Signal("reversal_5d", _reversal(5), "reversal",
               "negative of the 5-day return"),
        Signal("reversal_21d", _reversal(21), "reversal",
               "negative of the 21-day return"),
        Signal("extension_from_sma50", _extension, "reversal",
               "distance above the 50-day MA (sign is an open question)"),
        Signal("gap_fade", _gap_fade, "reversal",
               "negative of the overnight gap"),
        # --- volatility / structure --------------------------------------
        Signal("tightness", _tightness, "volatility",
               "volatility contraction — tighter ranges score higher"),
        Signal("squeeze", _squeeze, "volatility",
               "Bollinger/Keltner squeeze"),
        Signal("low_adr", _low_adr, "volatility",
               "negative average daily range"),
        # --- volume ------------------------------------------------------
        Signal("volume_confirmation", _volume_confirmation, "volume",
               "up-volume versus down-volume"),
        Signal("volume_surge", _volume_surge, "volume",
               "volume relative to its 50-day average"),
    ]
}

CONTROLS = [n for n, s in REGISTRY.items() if s.is_control]


def compute_all(bank, names: list[str] | None = None,
                mask: np.ndarray | None = None) -> dict[str, np.ndarray]:
    """Score matrices for the requested signals, NaN outside the universe.

    Masking here rather than downstream matters: a cross-sectional rank is
    relative to whoever is in the cross-section, so ranking against names the
    strategy would never hold produces a score the strategy cannot act on.
    """
    out: dict[str, np.ndarray] = {}
    for name in (names or list(REGISTRY)):
        sig = REGISTRY.get(name)
        if sig is None:
            log.warning("unknown signal %r — skipped", name)
            continue
        try:
            v = np.asarray(sig.fn(bank), dtype=np.float64)
        except Exception as exc:
            # Loud, not debug: a signal that silently vanishes from the report
            # reads as "tested and found wanting" when it was never computed.
            # `extension_from_sma50` asked for a feature name that does not
            # exist and disappeared from a whole IC table before this was raised.
            log.error("SIGNAL %s FAILED and is absent from the report: %s", name, exc)
            continue
        if mask is not None:
            v = np.where(mask, v, np.nan)
        out[name] = v
    return out
