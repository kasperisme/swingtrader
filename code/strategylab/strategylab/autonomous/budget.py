"""Stopping rules — the part that matters most when nobody is watching.

A search left running indefinitely does not converge on truth; it converges on
whatever the sample happens to reward. This project measured that directly:

    41 configurations   PBO = 0.255   selection carried real information
    110 configurations  PBO = 0.590   the in-sample winner landed in the bottom
                                      half out of sample more often than not

The winner did not get better between those two points. The *evidence for it*
got worse, because the deflated Sharpe deflates against the expected best of N
and N kept growing. A 24/7 researcher with no stopping rule will run that
process forever and produce a confident, worthless answer by morning.

So the budget is not a cost control. It is a statistical control, and it is
enforced rather than advised.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum


class StopReason(str, Enum):
    NONE = "none"
    TRIAL_BUDGET = "trial_budget_exhausted"
    PBO_DEGRADED = "pbo_degraded"
    PLATEAU = "no_improvement"
    PROPOSALS_EXHAUSTED = "proposal_space_exhausted"
    WALL_CLOCK = "wall_clock_limit"
    GATE_CLEARED = "acceptance_gate_cleared"
    OPERATOR = "stopped_by_operator"


@dataclass
class SearchBudget:
    """Limits for a single search campaign."""

    # Past roughly this many configurations, PBO rose from 0.255 to 0.59 in
    # this project's own measurements. Treated as a soft ceiling: the search
    # stops here unless it is still improving.
    soft_trial_budget: int = 60
    hard_trial_budget: int = 150

    # Stop after this many iterations with no improvement in the best reward.
    # Five runs here plateaued within 6-8 iterations and never recovered, and
    # every additional trial after that lowered the eventual deflated Sharpe.
    patience: int = 6
    min_improvement: float = 0.02      # smaller than this is noise, not progress

    max_pbo: float = 0.45              # above this, selection has stopped informing
    pbo_check_after: int = 40          # PBO needs a population before it means anything

    max_wall_clock_hours: float = 8.0
    min_iterations: int = 3            # never stop before the seed has been probed


@dataclass
class CampaignState:
    started: float = field(default_factory=time.time)
    iterations: int = 0
    best_reward: float = float("-inf")
    best_at_iteration: int = 0
    history: list[float] = field(default_factory=list)
    stop_reason: StopReason = StopReason.NONE
    notes: list[str] = field(default_factory=list)

    @property
    def hours(self) -> float:
        return (time.time() - self.started) / 3600.0

    @property
    def stale_iterations(self) -> int:
        return self.iterations - self.best_at_iteration

    def observe(self, iteration: int, best_reward: float,
                min_improvement: float = 0.02) -> None:
        """Record an iteration, and decide whether it counts as progress.

        Only an improvement of at least `min_improvement` resets the patience
        clock. A search inching up by 0.0005 an iteration is sampling noise, and
        if that counts as progress the campaign never ends — the reward drifts
        up forever and the stopping rule never fires. The reward differences
        this project could actually distinguish were around 0.15; anything an
        order of magnitude below that is not a signal.
        """
        self.iterations = iteration
        self.history.append(best_reward)
        improvement = best_reward - self.best_reward
        if improvement > 1e-12:
            self.best_reward = best_reward
            if improvement >= min_improvement or self.best_at_iteration == 0:
                self.best_at_iteration = iteration


def should_stop(state: CampaignState, budget: SearchBudget, n_trials: int,
                pbo: float | None = None, proposals_available: int = 1,
                gate_cleared: bool = False) -> tuple[bool, StopReason, str]:
    """Decide whether to keep going. Order matters: cheapest checks first."""
    if state.iterations < budget.min_iterations:
        return False, StopReason.NONE, ""

    if gate_cleared:
        return True, StopReason.GATE_CLEARED, (
            "acceptance gate cleared — further search can only lower the "
            "deflated Sharpe of the result already in hand")

    if proposals_available < 1:
        return True, StopReason.PROPOSALS_EXHAUSTED, (
            "every proposal duplicated something already evaluated; the space "
            "around the current elites is exhausted")

    if state.hours >= budget.max_wall_clock_hours:
        return True, StopReason.WALL_CLOCK, (
            f"wall-clock limit of {budget.max_wall_clock_hours:.1f}h reached")

    if n_trials >= budget.hard_trial_budget:
        return True, StopReason.TRIAL_BUDGET, (
            f"hard trial budget of {budget.hard_trial_budget} reached; every "
            "further configuration raises the bar the winner must clear")

    if pbo is not None and n_trials >= budget.pbo_check_after and pbo > budget.max_pbo:
        return True, StopReason.PBO_DEGRADED, (
            f"PBO {pbo:.3f} exceeds {budget.max_pbo:.2f} after {n_trials} "
            "configurations — selecting on backtest performance has stopped "
            "carrying information, so the search is now fitting noise")

    if state.stale_iterations >= budget.patience:
        return True, StopReason.PLATEAU, (
            f"{state.stale_iterations} iterations without improvement; the "
            "local optimum has been mapped")

    if n_trials >= budget.soft_trial_budget and state.stale_iterations >= 2:
        return True, StopReason.TRIAL_BUDGET, (
            f"past the soft budget ({budget.soft_trial_budget}) and no longer "
            "improving — continuing trades statistical power for nothing")

    return False, StopReason.NONE, ""


@dataclass
class DailyBudget:
    """Resource ceilings for the daemon as a whole, over a rolling day."""

    max_campaigns_per_day: int = 6
    max_backtests_per_day: int = 4000
    max_llm_calls_per_day: int = 800
    max_holdout_uses_per_week: int = 3     # the scarcest resource in the system

    campaigns: int = 0
    backtests: int = 0
    llm_calls: int = 0
    day_started: float = field(default_factory=time.time)

    def roll_if_needed(self) -> bool:
        if time.time() - self.day_started >= 86400:
            self.campaigns = self.backtests = self.llm_calls = 0
            self.day_started = time.time()
            return True
        return False

    def can_start_campaign(self) -> tuple[bool, str]:
        self.roll_if_needed()
        if self.campaigns >= self.max_campaigns_per_day:
            return False, f"daily campaign limit ({self.max_campaigns_per_day}) reached"
        if self.backtests >= self.max_backtests_per_day:
            return False, f"daily backtest limit ({self.max_backtests_per_day}) reached"
        if self.llm_calls >= self.max_llm_calls_per_day:
            return False, f"daily LLM limit ({self.max_llm_calls_per_day}) reached"
        return True, ""

    def summary(self) -> dict:
        return {"campaigns": f"{self.campaigns}/{self.max_campaigns_per_day}",
                "backtests": f"{self.backtests}/{self.max_backtests_per_day}",
                "llm_calls": f"{self.llm_calls}/{self.max_llm_calls_per_day}",
                "hours_into_day": round((time.time() - self.day_started) / 3600, 1)}
