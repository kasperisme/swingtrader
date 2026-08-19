"""Reward shaping and the deployment gate.

The reward is not Sharpe. A search with a few hundred trials will always find
*something* with a high in-sample Sharpe, and if that is the objective, that is
precisely what it will return: a fragile, over-traded, drawdown-heavy curve
fitted to one regime.

So the objective is the *median* fold Sharpe — robust to a single lucky
window — minus explicit prices for the things that make a backtest fail live:

    dispersion across folds   fragility; works in one regime only
    drawdown beyond budget    the strategy gets abandoned before it pays off
    turnover beyond budget    edge consumed by frictions and taxes
    complexity                every extra active knob is another chance to fit noise
    left-tail heaviness       the return shape that ruins accounts

Every penalty is one-sided and hinge-shaped: inside budget it costs nothing, so
the search is not pushed toward degenerate no-trade solutions.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .config import LabConfig
from .genome import Genome
from .validation import Evaluation

INVALID_REWARD = -5.0


@dataclass
class Reward:
    value: float
    base: float = 0.0
    penalties: dict = field(default_factory=dict)
    note: str = ""

    def to_dict(self) -> dict:
        return {"reward": self.value, "base": self.base,
                "penalties": self.penalties, "note": self.note}


def compute_reward(ev: Evaluation, g: Genome, cfg: LabConfig) -> Reward:
    if not ev.valid:
        return Reward(INVALID_REWARD, note=ev.reason or "invalid")

    w = cfg.reward
    m = ev.metrics

    # ---- base: robust central tendency of out-of-sample fold Sharpes -----
    fold_sr = [f["sharpe"] for f in ev.fold_metrics] if ev.fold_metrics else []
    if fold_sr:
        base = float(np.median(fold_sr))
        # DOWNSIDE dispersion only. Standard deviation treats an unusually good
        # fold as risk: adding a qualification screen lifted the folds from
        # [0.72, 0.52, 0.44, 0.49, 0.36] to [0.62, 1.24, 0.75, 0.39, 0.47] —
        # a better median AND a better worst fold — but std rose from 0.13 to
        # 0.34 and the penalty cancelled the entire gain. The reward was blind
        # to a 30% Sharpe improvement because one fold was too good.
        #
        # Deviation below the median is what "does this work in more than one
        # regime" actually means; the same asymmetry as Sortino versus Sharpe.
        arr = np.array(fold_sr, dtype=float)
        below = np.minimum(arr - np.median(arr), 0.0)
        dispersion = float(np.sqrt((below ** 2).mean())) if arr.size > 1 else 0.0
    else:
        base = float(m.get("sharpe", 0.0))
        dispersion = 0.0

    pen: dict[str, float] = {}
    # Scaled up because downside deviation is roughly half the size of the
    # two-sided figure it replaces, so the effective weight is preserved.
    pen["stability"] = 2.0 * w.lambda_stability * dispersion

    dd = float(m.get("max_drawdown", 0.0))
    pen["drawdown"] = w.lambda_drawdown * max(0.0, dd - w.dd_budget) / max(w.dd_budget, 1e-9)

    to = float(m.get("turnover_annual", 0.0))
    pen["turnover"] = w.lambda_turnover * max(0.0, to - w.turnover_budget) / max(w.turnover_budget, 1e-9)

    pen["complexity"] = w.lambda_complexity * g.complexity()

    tail = float(m.get("tail_ratio", 1.0))
    pen["tail"] = w.lambda_tail * max(0.0, 1.0 - tail)

    # A strategy whose returns are just the index re-levered is not an edge.
    beta = abs(float(m.get("beta", 0.0)))
    pen["beta_reliance"] = 0.25 * max(0.0, beta - 1.0)

    total = base - sum(pen.values())
    return Reward(value=float(total), base=base, penalties=pen)


def gate_report(ev: Evaluation, cfg: LabConfig, n_trials: int,
                sr_variance: float, pbo: float | None = None,
                vault: Evaluation | None = None) -> dict:
    """Check a genome against the deployment criteria.

    `n_trials` and `sr_variance` are what make this honest: the Deflated Sharpe
    is computed against the expected best-of-N, so a strategy found after 400
    experiments has to clear a materially higher bar than one found after 20.
    """
    from .metrics import deflated_sharpe

    gcfg = cfg.gate
    m = ev.metrics
    fold_sr = [f["sharpe"] for f in ev.fold_metrics]
    fold_win = (sum(1 for s in fold_sr if s > 0) / len(fold_sr)) if fold_sr else 0.0

    nz = ev.daily_returns[ev.daily_returns != 0] if ev.daily_returns is not None else np.array([])
    dsr = deflated_sharpe(
        observed_sr=float(m.get("sharpe", 0.0)),
        n_obs=int(nz.size),
        skew=float(m.get("skew", 0.0)),
        kurt=float(m.get("kurtosis", 3.0)),
        n_trials=max(1, n_trials),
        sr_variance=max(sr_variance, 1e-6),
    )

    checks = {
        "sharpe": (float(m.get("sharpe", 0.0)), gcfg.min_sharpe, ">="),
        "deflated_sharpe": (dsr, gcfg.min_deflated_sharpe, ">="),
        "fold_win_rate": (fold_win, gcfg.min_fold_win_rate, ">="),
        "max_drawdown": (float(m.get("max_drawdown", 1.0)), gcfg.max_drawdown, "<="),
        "n_trades": (int(m.get("n_trades", 0)), gcfg.min_trades, ">="),
        "alpha_t": (float(m.get("alpha_t", 0.0)), gcfg.min_alpha_t, ">="),
    }
    if pbo is not None and np.isfinite(pbo):
        checks["pbo"] = (float(pbo), gcfg.max_pbo, "<=")

    if vault is not None and vault.valid:
        vm = vault.metrics
        vs = float(vm.get("sharpe", 0.0))
        checks["vault_sharpe"] = (vs, gcfg.vault_sharpe_floor, ">=")
        dev_sr = float(m.get("sharpe", 0.0))
        ratio = vs / dev_sr if dev_sr > 1e-9 else 0.0
        checks["vault_retention"] = (ratio, gcfg.vault_sharpe_ratio_floor, ">=")

    results = {}
    for name, (actual, threshold, op) in checks.items():
        ok = actual >= threshold if op == ">=" else actual <= threshold
        results[name] = {"actual": actual, "threshold": threshold, "op": op, "pass": bool(ok)}

    return {
        "pass": all(v["pass"] for v in results.values()),
        "checks": results,
        "n_trials_considered": n_trials,
        "deflated_sharpe": dsr,
        "pbo": pbo,
        "failed": [k for k, v in results.items() if not v["pass"]],
    }


def sharpe_variance_across_trials(sharpes: list[float]) -> float:
    """Variance of the Sharpes the search has produced.

    This is the DSR's estimate of how much the search space itself scatters —
    a wide-open space produces a high expected maximum by luck alone, and the
    deflation has to know that.
    """
    vals = [s for s in sharpes if np.isfinite(s)]
    if len(vals) < 3:
        return 0.25 ** 2
    return float(np.var(vals, ddof=1))
