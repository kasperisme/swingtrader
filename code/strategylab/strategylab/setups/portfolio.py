"""A setup book with a position cap — the strategy as it would actually be run.

Everything in `study.py` measures a setup in isolation: every qualifying trade
is taken, none competes with another, and the answer comes back as an average
R-multiple. A real account cannot do that. It has a finite number of slots, so
three things appear that per-trade statistics cannot show:

  * **Capacity binds.** When more setups fire than there are slots, some are
    skipped. Which ones, and whether the skipped ones were the good ones, is a
    question about the selection rule and not about the setup.
  * **Sizing is not free.** Risking a fixed 1% of equity on a stop 7% away means
    a 14% position. Ten of those is 140% of the account, so either the risk per
    trade or the gross exposure has to give. Here gross is capped at 100% and
    the binding constraint is reported.
  * **Returns compound and idle capital earns nothing.** A book that is 40%
    invested on average cannot be judged by the expectancy of the trades it did
    take.

Slot contention is resolved by an explicit rule rather than by accident of
ordering, and "random" is offered as the honest default: assuming the ranking
picks the better setup is assuming exactly what the rest of this project has
repeatedly failed to demonstrate.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

TRADING_DAYS = 252


@dataclass
class PortfolioSpec:
    max_positions: int = 10           # 0 = uncapped
    risk_per_trade: float = 0.01      # fraction of equity risked per position
    max_gross: float = 1.0            # total notional cap
    max_position_weight: float = 0.25
    selection: str = "random"         # "random" | "score" | "first"
    cash_annual: float = 0.0
    seed: int = 31


def run_setup_portfolio(panel, resolved: pd.DataFrame, spec: PortfolioSpec,
                        score: np.ndarray | None = None):
    """Walk the setups forward, honouring a slot cap, and return an equity curve.

    `resolved` is the output of `resolve_setups`: one row per setup with an
    entry day, an exit day and a realised R-multiple. The portfolio layer adds
    only what a real account adds — competition for slots, position sizing, and
    compounding.
    """
    if resolved.empty:
        return np.zeros(1), {"trades_taken": 0}
    n = panel.close.shape[0]
    rng = np.random.default_rng(spec.seed)

    df = resolved.copy()
    df["entry_day"] = df["day"].astype(int) + 1
    df["exit_idx"] = (df["entry_day"] + df["days_held"].astype(int)).clip(upper=n - 1)
    df = df[df["entry_day"] < n - 1].sort_values("entry_day")
    by_day: dict[int, list] = {}
    for r in df.itertuples():
        by_day.setdefault(int(r.entry_day), []).append(r)

    equity = 1.0
    curve = np.zeros(n)
    open_pos: list[dict] = []
    taken = skipped_full = skipped_size = 0
    gross_hist, slots_hist = [], []
    cash_daily = spec.cash_annual / TRADING_DAYS

    for k in range(n):
        # --- close what expires today -----------------------------------
        still = []
        for p in open_pos:
            if p["exit"] <= k:
                equity += p["risk_dollars"] * p["r"]
            else:
                still.append(p)
        open_pos = still

        # --- open new positions ------------------------------------------
        cands = by_day.get(k, [])
        if cands:
            cap = spec.max_positions if spec.max_positions > 0 else len(cands) + len(open_pos)
            free = max(0, cap - len(open_pos))
            if free < len(cands):
                if spec.selection == "score" and score is not None:
                    vals = np.array([score[int(c.day), int(c.col)] for c in cands],
                                    dtype=float)
                    vals = np.where(np.isfinite(vals), vals, -np.inf)
                    order = np.argsort(-vals, kind="stable")
                elif spec.selection == "first":
                    order = np.arange(len(cands))
                else:
                    order = rng.permutation(len(cands))
                skipped_full += len(cands) - free
                cands = [cands[i] for i in order[:free]]
            for c in cands:
                stop_pct = float(c.risk_pct)
                if not (stop_pct > 0):
                    continue
                w = min(spec.risk_per_trade / stop_pct, spec.max_position_weight)
                gross_now = sum(p["weight"] for p in open_pos)
                if gross_now + w > spec.max_gross:
                    w = max(0.0, spec.max_gross - gross_now)
                if w <= 1e-6:
                    skipped_size += 1
                    continue
                open_pos.append({"exit": int(c.exit_idx), "weight": w,
                                 "risk_dollars": equity * w * stop_pct,
                                 "r": float(c.r_net)})
                taken += 1

        gross_hist.append(sum(p["weight"] for p in open_pos))
        slots_hist.append(len(open_pos))
        curve[k] = equity

    ret = np.zeros(n)
    ret[1:] = curve[1:] / np.where(curve[:-1] > 0, curve[:-1], np.nan) - 1.0
    ret = np.where(np.isfinite(ret), ret, 0.0)
    idle = 1.0 - np.array(gross_hist)
    ret += np.clip(idle, 0.0, 1.0) * cash_daily

    diag = {
        "trades_taken": taken,
        "trades_skipped_capacity": skipped_full,
        "trades_skipped_sizing": skipped_size,
        "setups_available": int(len(df)),
        "take_rate": taken / max(1, len(df)),
        "avg_gross_exposure": float(np.mean(gross_hist)),
        "avg_open_positions": float(np.mean(slots_hist)),
        "max_open_positions": int(np.max(slots_hist)) if slots_hist else 0,
        # Which constraint actually bound: the slot cap or the notional cap.
        "binding": ("slots" if skipped_full > skipped_size else
                    "gross_exposure" if skipped_size else "neither"),
    }
    return ret, diag
