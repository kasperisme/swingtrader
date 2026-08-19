"""Stochastic search over the genome space.

The response surface here is noisy, non-differentiable, partly categorical, and
expensive to sample. That rules out gradient methods and makes brute-force grid
search wasteful, so the lab runs three complementary samplers and lets a bandit
decide how to spend the budget between their operators:

* **Mutation** — local moves within one coherent block (all the exit knobs, all
  the gates). Coherent moves matter: nudging one scalar at a time makes the
  search walk, and walking is slow in 70 dimensions.
* **TPE surrogate** — a Tree-structured Parzen Estimator over the ledger. It
  models P(genome | good) and P(genome | bad) per dimension and proposes points
  maximising their ratio. This is the component that exploits everything the
  search has already learned, and it costs no backtests to run.
* **Random** — a uniform draw. Small but non-zero, because every other sampler
  is biased toward what has already worked, and that is how a search collapses
  onto a local optimum and stops learning.

Operator selection is UCB1 on realised reward improvement, so an operator that
stops paying off stops getting budget — without ever being switched off, since
the confidence term keeps pulling neglected arms back for a retry.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

import numpy as np

from .genome import (BLOCKS, CONDITIONAL, SPACE, Boolean, Choice, Genome, Integer,
                     Real, random_genome)


@dataclass
class Proposal:
    genome: Genome
    source: str                     # llm | tpe | mutate | crossover | random | seed
    operator: str = ""
    parent_hash: str | None = None
    hypothesis: str = ""
    meta: dict = field(default_factory=dict)


# ----------------------------------------------------------------------
# Operators
# ----------------------------------------------------------------------
OPERATORS: list[str] = [
    "tune_gates", "loosen_gates", "tighten_gates",
    "tune_exits", "widen_stops", "tighten_stops", "let_winners_run",
    "tune_entry", "switch_entry_type",
    "tune_ranking", "focus_ranking",
    "tune_portfolio", "concentrate", "diversify",
    "tune_universe", "tune_regime",
    "enable_shorts", "tune_shorts", "tighten_short_gates", "loosen_short_gates",
    "toggle_overlay",
    "diagnostic_directed",
    "crossover",
]


def _perturb(g: Genome, key: str, rng: random.Random, strength: float) -> None:
    dim = SPACE[key]
    if isinstance(dim, Boolean):
        if rng.random() < min(0.9, strength * 1.5):
            g[key] = not g[key]
    elif isinstance(dim, Choice):
        if rng.random() < min(0.9, strength * 1.2):
            g[key] = rng.choice([o for o in dim.options if o != g[key]] or list(dim.options))
    else:
        u = dim.unit(g[key])
        u = min(1.0, max(0.0, u + rng.gauss(0.0, strength)))
        g[key] = dim.from_unit(u)


def _nudge(g: Genome, key: str, rng: random.Random, direction: int, strength: float) -> None:
    """Move a numeric key deliberately up (+1) or down (-1) in unit space."""
    dim = SPACE[key]
    if isinstance(dim, Boolean):
        g[key] = direction > 0
        return
    if isinstance(dim, Choice):
        _perturb(g, key, rng, strength)
        return
    u = dim.unit(g[key]) + direction * abs(rng.gauss(strength, strength / 2))
    g[key] = dim.from_unit(min(1.0, max(0.0, u)))


def _active(g: Genome, key: str) -> bool:
    cond = CONDITIONAL.get(key)
    return not cond or g.get(cond[0]) == cond[1]


def apply_operator(parent: Genome, operator: str, rng: random.Random,
                   strength: float = 0.18, context: dict | None = None,
                   pool: list[Genome] | None = None) -> Genome:
    g = Genome(dict(parent))
    ctx = context or {}

    def touch(keys, n=3, direction=None):
        keys = [k for k in keys if _active(g, k)]
        if not keys:
            return
        for k in rng.sample(keys, min(n, len(keys))):
            if direction is None:
                _perturb(g, k, rng, strength)
            else:
                _nudge(g, k, rng, direction, strength)

    if operator == "tune_gates":
        touch(BLOCKS["gates"], 3)
    elif operator == "loosen_gates":
        # "Loosen" = admit more names: lower minimums, raise maximums.
        touch(["gates.rs_rank_min", "gates.min_pct_above_52w_low",
               "gates.min_up_down_vol", "gates.adr_min", "gates.min_base_tightness"],
              2, direction=-1)
        touch(["gates.max_pct_below_52w_high", "gates.adr_max",
               "gates.max_dist_from_sma50"], 2, direction=+1)
    elif operator == "tighten_gates":
        touch(["gates.rs_rank_min", "gates.min_pct_above_52w_low",
               "gates.min_up_down_vol"], 2, direction=+1)
        touch(["gates.max_pct_below_52w_high", "gates.max_dist_from_sma50"], 2, direction=-1)

    elif operator == "tune_exits":
        touch(BLOCKS["exit"], 3)
    elif operator == "widen_stops":
        touch(["exit.stop_atr_mult", "exit.stop_pct"], 2, direction=+1)
    elif operator == "tighten_stops":
        touch(["exit.stop_atr_mult", "exit.stop_pct"], 2, direction=-1)
    elif operator == "let_winners_run":
        touch(["exit.max_hold_days", "exit.trail_atr_mult", "exit.target_r"], 3, direction=+1)
        g["exit.trail_enabled"] = True

    elif operator == "tune_entry":
        touch(BLOCKS["entry"], 3)
    elif operator == "switch_entry_type":
        opts = [o for o in SPACE["entry.type"].options if o != g["entry.type"]]
        g["entry.type"] = rng.choice(opts)
        touch(BLOCKS["entry"], 2)

    elif operator == "tune_ranking":
        touch(BLOCKS["rank"], 4)
    elif operator == "focus_ranking":
        # Collapse onto one factor — the MDL-friendly end of the ranking space.
        keys = [k for k in SPACE if k.startswith("rank.w_")]
        winner = rng.choice(keys)
        for k in keys:
            g[k] = 1.0 if k == winner else 0.0

    elif operator == "tune_portfolio":
        touch(BLOCKS["pf"], 3)
    elif operator == "concentrate":
        _nudge(g, "pf.max_positions", rng, -1, strength)
        _nudge(g, "pf.max_weight", rng, +1, strength)
        _nudge(g, "pf.risk_pct", rng, +1, strength)
    elif operator == "diversify":
        _nudge(g, "pf.max_positions", rng, +1, strength)
        _nudge(g, "pf.max_weight", rng, -1, strength)
        _nudge(g, "pf.max_sector_positions", rng, -1, strength)

    elif operator == "tune_universe":
        touch(BLOCKS["universe"], 3)
    elif operator == "tune_regime":
        g["regime.enabled"] = True
        touch(["regime.ma_len", "regime.slope_days", "regime.breadth_enabled",
               "regime.breadth_min"], 2)

    elif operator == "enable_shorts":
        # Turning the sleeve ON is its own move: it costs ~15 active parameters
        # of complexity, so it has to be tried as a package rather than reached
        # by accident through a scalar nudge.
        g["short.enabled"] = True
        touch(BLOCKS["short"], 3)
    elif operator == "tune_shorts":
        g["short.enabled"] = True
        touch(BLOCKS["short"], 4)
    elif operator == "tighten_short_gates":
        g["short.enabled"] = True
        touch(["short.rs_rank_max", "short.max_pct_above_52w_low",
               "short.max_up_down_vol"], 3, direction=-1)
        touch(["short.min_pct_below_52w_high", "short.min_price",
               "short.min_dollar_vol"], 2, direction=+1)
    elif operator == "loosen_short_gates":
        g["short.enabled"] = True
        touch(["short.rs_rank_max", "short.max_pct_above_52w_low",
               "short.max_up_down_vol"], 3, direction=+1)
        touch(["short.min_pct_below_52w_high"], 1, direction=-1)

    elif operator == "toggle_overlay":
        key = rng.choice(["gates.use_fundamentals", "gates.use_news", "regime.breadth_enabled",
                          "exit.regime_exit", "exit.exit_on_sma_break",
                          "gates.rs_line_new_high", "short.enabled"])
        g[key] = not g[key]
        if key == "gates.use_news" and g[key]:
            g["rank.w_news"] = max(g["rank.w_news"], 0.3)

    elif operator == "diagnostic_directed":
        keys = [k for k in ctx.get("direction_keys", []) if k in SPACE and _active(g, k)]
        if keys:
            for k in rng.sample(keys, min(3, len(keys))):
                _perturb(g, k, rng, strength * 1.4)
        else:
            touch(list(SPACE), 3)

    elif operator == "crossover" and pool:
        other = rng.choice(pool)
        # Block-wise crossover keeps each parent's internally consistent ideas
        # intact instead of blending them into something neither parent was.
        for block, keys in BLOCKS.items():
            if rng.random() < 0.5:
                for k in keys:
                    g[k] = other[k]
        _perturb(g, rng.choice(list(SPACE)), rng, strength)

    else:
        touch(list(SPACE), 3)

    return g.repair()


# ----------------------------------------------------------------------
# UCB1 bandit over operators
# ----------------------------------------------------------------------
class OperatorBandit:
    """Credit assignment across move types.

    The reward signal is the *improvement over the parent*, not the absolute
    reward — otherwise every operator applied to a strong elite looks good and
    every operator applied to a weak one looks bad, and the bandit learns the
    quality of the parents instead of the quality of the moves.
    """

    def __init__(self, operators: list[str] | None = None, c: float = 1.2):
        self.operators = list(operators or OPERATORS)
        self.c = c
        self.n: dict[str, int] = {o: 0 for o in self.operators}
        self.total: dict[str, float] = {o: 0.0 for o in self.operators}

    def load(self, stats: dict[str, dict]) -> None:
        for op, s in stats.items():
            if op in self.n:
                self.n[op] = int(s.get("n", 0))
                self.total[op] = float(s.get("sum", 0.0))

    def select(self, rng: random.Random) -> str:
        total_n = sum(self.n.values())
        if total_n < len(self.operators):
            untried = [o for o in self.operators if self.n[o] == 0]
            if untried:
                return rng.choice(untried)
        best, best_score = self.operators[0], -1e18
        for o in self.operators:
            n = self.n[o]
            if n == 0:
                return o
            mean = self.total[o] / n
            bonus = self.c * math.sqrt(math.log(max(total_n, 2)) / n)
            score = mean + bonus
            if score > best_score:
                best, best_score = o, score
        return best

    def update(self, operator: str, improvement: float) -> None:
        if operator not in self.n:
            self.operators.append(operator)
            self.n[operator] = 0
            self.total[operator] = 0.0
        self.n[operator] += 1
        # Squash so one freak result cannot own the bandit for the rest of the run.
        self.total[operator] += float(np.tanh(improvement))

    def table(self) -> list[dict]:
        rows = []
        for o in self.operators:
            n = self.n[o]
            rows.append({"operator": o, "n": n,
                         "mean_improvement": round(self.total[o] / n, 4) if n else None})
        return sorted(rows, key=lambda r: (r["mean_improvement"] is None,
                                           -(r["mean_improvement"] or 0)))


# ----------------------------------------------------------------------
# TPE surrogate
# ----------------------------------------------------------------------
class TPESampler:
    """Tree-structured Parzen Estimator over the ledger's observed trials.

    Splits history into the top `gamma` quantile (`good`) and the rest (`bad`),
    fits a 1-D Parzen window per dimension in unit space, then draws candidates
    from `l(x)` and keeps the ones maximising `l(x)/g(x)`. The per-dimension
    independence assumption is TPE's standard simplification: it gives up joint
    structure in exchange for working from a handful of observations, which is
    the regime this search is always in.
    """

    def __init__(self, gamma: float = 0.25, n_candidates: int = 64,
                 min_observations: int = 12):
        self.gamma = gamma
        self.n_candidates = n_candidates
        self.min_obs = min_observations

    def _bandwidth(self, n: int) -> float:
        # Scott-style rule, floored so a tiny `good` set does not collapse the
        # density onto its own points and stop exploring.
        return max(0.08, 1.0 / math.sqrt(max(n, 1)))

    @staticmethod
    def _log_density(u: float, samples: np.ndarray, bw: float) -> float:
        if samples.size == 0:
            return math.log(1.0)          # uniform prior on [0,1]
        z = (u - samples) / bw
        dens = np.exp(-0.5 * z * z).sum() / (samples.size * bw * math.sqrt(2 * math.pi))
        dens = 0.85 * dens + 0.15 * 1.0   # mixed with a uniform component
        return math.log(max(dens, 1e-12))

    def propose(self, observations: list[tuple[Genome, float]], rng: random.Random,
                n: int = 1) -> list[Genome]:
        obs = [(g, r) for g, r in observations if np.isfinite(r)]
        if len(obs) < self.min_obs:
            return [random_genome(rng) for _ in range(n)]

        obs.sort(key=lambda gr: -gr[1])
        n_good = max(3, int(math.ceil(self.gamma * len(obs))))
        good, bad = [g for g, _ in obs[:n_good]], [g for g, _ in obs[n_good:]]
        keys = sorted(SPACE)

        gu = {k: np.array([SPACE[k].unit(g[k]) for g in good]) for k in keys}
        bu = {k: np.array([SPACE[k].unit(g[k]) for g in bad]) for k in keys}
        bw_g, bw_b = self._bandwidth(len(good)), self._bandwidth(len(bad))

        out: list[Genome] = []
        for _ in range(n):
            best_vals, best_score = None, -1e18
            for _ in range(self.n_candidates):
                vals, score = {}, 0.0
                for k in keys:
                    base = float(rng.choice(list(gu[k]))) if gu[k].size else rng.random()
                    u = min(1.0, max(0.0, base + rng.gauss(0.0, bw_g)))
                    vals[k] = SPACE[k].from_unit(u)
                    score += self._log_density(u, gu[k], bw_g) - self._log_density(u, bu[k], bw_b)
                if score > best_score:
                    best_vals, best_score = vals, score
            out.append(Genome(best_vals))
        return out


# ----------------------------------------------------------------------
def dedupe(proposals: list[Proposal], seen: set[str]) -> list[Proposal]:
    """Drop repeats. Re-evaluating a genome buys no information and inflates
    the trial count that the deflated Sharpe is computed against."""
    out = []
    for p in proposals:
        h = p.genome.hash
        if h in seen:
            continue
        seen.add(h)
        out.append(p)
    return out


def diversify_against(proposals: list[Proposal], elites: list[Genome],
                      min_distance: float = 0.02) -> list[Proposal]:
    """Reject proposals that are numerically indistinguishable from an elite.

    Without this, a converged search spends its whole budget re-measuring the
    same point through slightly different floats."""
    if not elites:
        return proposals
    E = np.array([g.to_unit_vector() for g in elites])
    out = []
    for p in proposals:
        v = np.array(p.genome.to_unit_vector())
        d = np.sqrt(((E - v) ** 2).mean(axis=1)).min()
        if d >= min_distance:
            out.append(p)
    return out or proposals[:1]
