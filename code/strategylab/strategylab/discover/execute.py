"""Run one hypothesis and score it against a matched null.

Two rungs, mirroring the successive halving the genome search already uses.
Rung 0 is cheap and answers "is this worth measuring properly"; rung 1 pays for
the placebo, the control and the vault. Most hypotheses are noise, and paying
full price to establish that is how a search burns its budget on nothing.

Every score is a *paired* comparison where one exists — a signal is measured
against a shuffled version of itself, and a setup conditioner against the same
conditioner applied to the no-trigger control book. The effect that survives is
the excess, never the raw number.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from ..momentum import ic as icmod
from ..momentum.signals import CONTROLS, compute_all
from ..setups.study import _cluster, _monthly, conditioner_report
from .hypothesis import SIGNAL_PRIMITIVES, Hypothesis, apply_transform
from .registry import ScoredHypothesis

log = logging.getLogger(__name__)


class Context:
    """Everything a hypothesis needs, built once and reused across the loop."""

    def __init__(self, panel, bank, mask, dev_slice, vault_slice,
                 setups=None, controls=None):
        self.panel = panel
        self.bank = bank
        self.mask = mask
        self.dev = dev_slice            # (lo, hi) row indices
        self.vault = vault_slice
        self.setups = setups            # resolved pullback setups, dev+vault
        self.controls = controls        # resolved pseudo-setups
        self._fwd: dict[int, np.ndarray] = {}
        self._ctrl_scores = None

    def forward(self, horizon: int) -> np.ndarray:
        if horizon not in self._fwd:
            self._fwd[horizon] = icmod.forward_returns(self.panel, horizon)
        return self._fwd[horizon]

    def masked(self, lo: int, hi: int) -> np.ndarray:
        m = np.zeros_like(self.mask)
        m[lo:hi] = self.mask[lo:hi]
        return m

    def control_scores(self):
        if self._ctrl_scores is None:
            self._ctrl_scores = compute_all(self.bank, CONTROLS, mask=self.mask)
        return self._ctrl_scores


def build_signal(ctx: Context, h: Hypothesis) -> np.ndarray | None:
    name, kw = SIGNAL_PRIMITIVES[h.primitive]
    try:
        raw = np.asarray(ctx.bank.get(name, **kw), dtype=np.float64)
    except Exception as exc:
        log.error("primitive %s failed: %s", h.primitive, exc)
        return None
    try:
        return apply_transform(raw, h.transform)
    except Exception as exc:
        log.error("transform %s failed: %s", h.transform, exc)
        return None


# ----------------------------------------------------------------------
def _score_ic(ctx: Context, h: Hypothesis, sig: np.ndarray, rung: int) -> ScoredHypothesis:
    lo, hi = ctx.dev
    mask = ctx.masked(lo, hi)
    s = np.where(mask, sig, np.nan)
    fwd = ctx.forward(h.horizon)
    ic = icmod.daily_ic(s, fwd, mask)
    r = icmod.ic_summary(ic, h.horizon)
    out = ScoredHypothesis(key=h.key, name=h.name, rung=rung)
    if not r.get("available"):
        out.detail = {"unavailable": r}
        return out
    out.effect = r["ic_mean"]
    out.t_stat = r["t_newey_west"]
    out.n_obs = r["days"]
    out.detail = {"ic": r}
    if rung == 0:
        return out

    p = icmod.placebo_ic(s, fwd, mask, h.horizon, seeds=3)
    out.placebo_t = p.get("t_mean", float("nan"))
    # Incremental over the momentum controls — on a universe that IS a momentum
    # screen, a standalone IC mostly measures how much of the screen a signal
    # has re-encoded.
    scores = dict(ctx.control_scores())
    scores["_candidate"] = s
    inc = icmod.incremental_ic(scores, ctx.panel, mask, h.horizon, CONTROLS)
    c = inc["coefficients"].get("_candidate", {})
    out.control_effect = c.get("mean_bps_per_sigma", float("nan"))
    if c.get("available"):
        # The incremental t is the number that decides; the standalone one is
        # reported but never gates.
        out.t_stat = c["t_newey_west"]
        out.effect = c["mean_bps_per_sigma"] / 1e4
    out.detail |= {"placebo": p, "incremental": c}
    return out


def _score_setup(ctx: Context, h: Hypothesis, sig: np.ndarray, rung: int) -> ScoredHypothesis:
    out = ScoredHypothesis(key=h.key, name=h.name, rung=rung)
    if ctx.setups is None or ctx.setups.empty:
        out.detail = {"unavailable": "no setup book"}
        return out
    lo, hi = ctx.dev
    col = f"_h_{h.key}"
    frames = {}
    for label, df in (("real", ctx.setups), ("ctrl", ctx.controls)):
        if df is None or df.empty:
            continue
        d = df[(df["day"] >= lo) & (df["day"] < hi)].copy()
        if d.empty:
            continue
        d[col] = sig[d["day"].to_numpy(), d["col"].to_numpy()]
        frames[label] = d
    if "real" not in frames or len(frames["real"]) < 400:
        out.detail = {"unavailable": "too few setups"}
        return out

    class _S:
        reward_multiple = 2.0
    rep = conditioner_report(frames["real"], [col], _S(), n_variants=1,
                             control=frames.get("ctrl"))
    row = rep["rows"].get(col, {})
    if not row.get("available"):
        out.detail = {"unavailable": row}
        return out
    out.effect = row.get("top_minus_bottom_r") or float("nan")
    out.t_stat = row.get("t_r") or float("nan")
    out.n_obs = row.get("n", 0)
    out.placebo_t = row.get("placebo_t") or float("nan")
    out.control_effect = row.get("control_top_minus_bottom") or float("nan")
    out.detail = {"conditioner": row}
    return out


def evaluate(ctx: Context, h: Hypothesis, rung: int = 1) -> ScoredHypothesis:
    sig = build_signal(ctx, h)
    if sig is None:
        return ScoredHypothesis(key=h.key, name=h.name, rung=rung,
                                detail={"unavailable": "signal failed to build"})
    if h.outcome == "ic":
        return _score_ic(ctx, h, sig, rung)
    return _score_setup(ctx, h, sig, rung)


def confirm_on_vault(ctx: Context, h: Hypothesis) -> dict:
    """The one out-of-sample look, taken only for a hypothesis that cleared the
    bar on dev. Each use is logged, because a holdout tested repeatedly is a
    training set."""
    sig = build_signal(ctx, h)
    if sig is None:
        return {}
    lo, hi = ctx.vault
    if h.outcome == "ic":
        mask = ctx.masked(lo, hi)
        s = np.where(mask, sig, np.nan)
        r = icmod.ic_summary(icmod.daily_ic(s, ctx.forward(h.horizon), mask), h.horizon)
        return {"effect": r.get("ic_mean"), "t": r.get("t_newey_west"),
                "n": r.get("days")}
    if ctx.setups is None or ctx.setups.empty:
        return {}
    d = ctx.setups[(ctx.setups["day"] >= lo) & (ctx.setups["day"] < hi)].copy()
    if len(d) < 200:
        return {}
    col = f"_v_{h.key}"
    d[col] = sig[d["day"].to_numpy(), d["col"].to_numpy()]
    d = d.dropna(subset=[col])
    q = pd.qcut(d[col], 5, labels=False, duplicates="drop")
    top, bot = d[q == q.max()], d[q == q.min()]
    a, b = _monthly(top, "r_net"), _monthly(bot, "r_net")
    both = a.index.intersection(b.index)
    if len(both) < 6:
        return {}
    c = _cluster((a.loc[both] - b.loc[both]).to_numpy())
    return {"effect": c.get("mean"), "t": c.get("t"), "n": int(len(d))}
