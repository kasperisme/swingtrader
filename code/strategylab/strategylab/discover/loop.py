"""The loop: propose, register, test, raise the bar, repeat.

The stopping conditions are the design. A search without them does not converge
on truth, it converges on whatever noise it has looked at most.

  1. **A confirmed finding** — cleared the rising bar on dev, placebo clean,
     control beaten, and confirmed out of sample on the vault.
  2. **The space is exhausted** — every hypothesis in the grammar has been
     tested. This is a real answer: "none of these works" is knowledge.
  3. **The budget is spent.**

None of them is "it started to look promising", which is the condition that
ends most searches and is the reason most searches are wrong.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .execute import Context, confirm_on_vault, evaluate
from .hypothesis import Hypothesis, HypothesisSpace
from .registry import Registry, ScoredHypothesis

log = logging.getLogger(__name__)


def significance_bar(n_trials: int, base: float = 2.0, margin: float = 0.5) -> float:
    """The |t| a result must clear after `n_trials` hypotheses.

    The maximum of N independent standard normals grows like sqrt(2 ln N), so a
    fixed threshold of 2.0 is guaranteed to be breached by noise once N passes
    roughly 20. The bar therefore tracks that expected maximum plus a margin:
    3.2 at ten hypotheses, 4.1 at a hundred, 4.8 at a thousand.

    This is the same idea as the deflated Sharpe ratio already used on the
    genome search, applied to t-statistics instead of Sharpes.
    """
    n = max(1, int(n_trials))
    return float(max(base, np.sqrt(2.0 * np.log(max(n, 2))) + margin))


@dataclass
class LoopConfig:
    max_iterations: int = 200
    rung0_batch: int = 12          # hypotheses screened cheaply per iteration
    promote_top: int = 3           # how many go on to the full battery
    rung0_min_abs_t: float = 1.0   # screen-out threshold, deliberately generous
    placebo_max_abs_t: float = 2.0
    require_control_beaten: bool = True
    vault_min_abs_t: float = 1.5
    time_budget_s: float = 0.0     # 0 = no limit
    seed: int = 17


@dataclass
class LoopState:
    iterations: int = 0
    tested: int = 0
    promoted: int = 0
    confirmed: list = field(default_factory=list)
    stopped_because: str = ""


class DiscoveryLoop:
    def __init__(self, ctx: Context, registry: Registry, space: HypothesisSpace,
                 cfg: LoopConfig | None = None):
        self.ctx = ctx
        self.reg = registry
        self.space = space
        self.cfg = cfg or LoopConfig()
        self.state = LoopState()

    # ------------------------------------------------------------------
    def _judge(self, s: ScoredHypothesis, bar: float) -> bool:
        if not np.isfinite(s.t_stat):
            return False
        if abs(s.t_stat) < bar:
            return False
        if np.isfinite(s.placebo_t) and abs(s.placebo_t) > self.cfg.placebo_max_abs_t:
            log.warning("%s cleared the bar but its PLACEBO also fired (t=%.2f) — "
                        "rejecting; that is a broken control, not a discovery",
                        s.name, s.placebo_t)
            return False
        if self.cfg.require_control_beaten and np.isfinite(s.control_effect):
            # For setup conditioners the control effect is a like-for-like
            # number; the candidate must exceed it, not merely be positive.
            if s.name.endswith("|setup|H0") and abs(s.control_effect) >= abs(s.effect):
                return False
        return True

    def step(self) -> dict:
        cfg = self.cfg
        tested = self.reg.tested_keys()
        batch = self.space.next_untested(tested, cfg.rung0_batch)
        if not batch:
            self.state.stopped_because = "space exhausted"
            return {"done": True, "reason": self.state.stopped_because}

        for h in batch:
            self.reg.register(h)

        # --- rung 0: cheap screen -------------------------------------
        rung0 = []
        for h in batch:
            s = evaluate(self.ctx, h, rung=0)
            rung0.append((h, s))
        ranked = sorted(rung0, key=lambda kv: -abs(kv[1].t_stat)
                        if np.isfinite(kv[1].t_stat) else 0.0)
        promote = [(h, s) for h, s in ranked
                   if np.isfinite(s.t_stat) and abs(s.t_stat) >= cfg.rung0_min_abs_t
                   ][:cfg.promote_top]

        # Everything screened out is still RECORDED as tested. It happened; it
        # counts toward the bar. Discarding it silently is how a search lies
        # about how hard it looked.
        promoted_keys = {h.key for h, _ in promote}
        for h, s in rung0:
            if h.key in promoted_keys:
                continue
            s.bar = significance_bar(self.reg.n_tested() + 1)
            self.reg.record(s)
            self.state.tested += 1

        # --- rung 1: the full battery ---------------------------------
        results = []
        for h, _ in promote:
            s = evaluate(self.ctx, h, rung=1)
            bar = significance_bar(self.reg.n_tested() + 1)
            s.bar = bar
            s.cleared = self._judge(s, bar)
            if s.cleared:
                v = confirm_on_vault(self.ctx, h)
                s.vault_effect = v.get("effect", float("nan")) or float("nan")
                s.vault_t = v.get("t", float("nan")) or float("nan")
                s.confirmed = bool(np.isfinite(s.vault_t)
                                   and abs(s.vault_t) >= cfg.vault_min_abs_t
                                   and np.sign(s.vault_effect or 0) == np.sign(s.effect or 0))
                self.reg.log("vault_use", {"hypothesis": h.name, "t": s.vault_t})
            self.reg.record(s)
            self.state.tested += 1
            self.state.promoted += 1
            results.append(s)
            if s.confirmed:
                self.state.confirmed.append(s.to_dict())

        self.state.iterations += 1
        return {"done": False, "batch": len(batch), "promoted": len(promote),
                "results": [s.to_dict() for s in results],
                "bar": significance_bar(self.reg.n_tested()),
                "tested_total": self.reg.n_tested()}

    def run(self, on_step=None) -> LoopState:
        started = time.time()
        self.reg.log("loop_start", {"space_size": self.space.size(),
                                    "already_tested": self.reg.n_tested()})
        while self.state.iterations < self.cfg.max_iterations:
            out = self.step()
            if on_step:
                on_step(out)
            if out.get("done"):
                break
            if self.state.confirmed:
                self.state.stopped_because = "confirmed finding"
                break
            if self.cfg.time_budget_s and (time.time() - started) > self.cfg.time_budget_s:
                self.state.stopped_because = "time budget"
                break
        else:
            self.state.stopped_because = "iteration budget"
        self.reg.log("loop_stop", {"reason": self.state.stopped_because,
                                   "tested": self.reg.n_tested()})
        return self.state
