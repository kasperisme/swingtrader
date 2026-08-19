import random

import numpy as np

from strategylab.config import LabConfig
from strategylab.genome import SPACE, Genome, default_genome
from strategylab.reward import compute_reward, gate_report, sharpe_variance_across_trials
from strategylab.search import (OPERATORS, OperatorBandit, Proposal, TPESampler,
                                apply_operator, dedupe, diversify_against)
from strategylab.validation import Evaluation


def _ev(sharpe, folds, dd=0.15, trades=200, **extra):
    m = {"sharpe": sharpe, "max_drawdown": dd, "n_trades": trades,
         "turnover_annual": 6.0, "tail_ratio": 1.0, "avg_exposure": 0.6,
         "beta": 0.5, "alpha_t": 2.0, "skew": 0.0, "kurtosis": 3.0}
    m.update(extra)
    ev = Evaluation("h", 1, True, metrics=m)
    ev.fold_metrics = [{"fold": f"f{i}", "start": "2015-01-01", "end": "2016-01-01",
                        "sharpe": s, "return": 0.1, "max_drawdown": 0.1, "n_trades": 40,
                        "days": 250}
                       for i, s in enumerate(folds)]
    ev.daily_returns = np.random.default_rng(0).normal(0.0004, 0.01, 2000)
    return ev


def test_every_operator_produces_a_valid_genome():
    rng = random.Random(0)
    parent = default_genome()
    pool = [default_genome(), Genome({"entry.type": "rank_only"})]
    for op in OPERATORS:
        for _ in range(5):
            child = apply_operator(parent, op, rng, 0.25, {"direction_keys": list(SPACE)[:5]}, pool)
            assert set(child) == set(SPACE)
            for k, dim in SPACE.items():
                assert dim.clip(child[k]) == child[k], f"{op} produced out-of-range {k}"


def test_operators_actually_change_something():
    rng = random.Random(1)
    parent = default_genome()
    changed = sum(1 for op in OPERATORS
                  if apply_operator(parent, op, rng, 0.3, {}, [parent]).hash != parent.hash)
    assert changed >= len(OPERATORS) - 2


def test_bandit_converges_on_the_paying_operator():
    b = OperatorBandit(["good", "bad"], c=0.5)
    rng = random.Random(0)
    for _ in range(200):
        op = b.select(rng)
        b.update(op, 1.0 if op == "good" else -1.0)
    assert b.n["good"] > b.n["bad"] * 2


def test_reward_prefers_stability_over_a_single_lucky_fold():
    cfg = LabConfig()
    g = default_genome()
    steady = compute_reward(_ev(1.0, [0.9, 1.0, 1.1, 1.0, 0.95]), g, cfg)
    spiky = compute_reward(_ev(1.0, [-0.4, 3.2, -0.3, 0.2, 1.0]), g, cfg)
    assert steady.value > spiky.value


def test_reward_does_not_punish_an_unusually_GOOD_fold():
    """Standard deviation treats upside dispersion as risk. That blindness cost
    a real 30% Sharpe improvement: a qualification screen lifted the folds to a
    better median AND a better worst case, but one fold was so good that the
    two-sided penalty cancelled the entire gain."""
    cfg = LabConfig()
    g = default_genome()
    flat = compute_reward(_ev(0.51, [0.72, 0.52, 0.44, 0.49, 0.36]), g, cfg)
    better = compute_reward(_ev(0.67, [0.62, 1.24, 0.75, 0.39, 0.47]), g, cfg)
    assert better.value > flat.value, (
        f"reward punished a better median AND a better worst fold: "
        f"{better.value:.3f} vs {flat.value:.3f}")


def test_reward_still_punishes_a_bad_worst_fold():
    """The fix must not become 'ignore dispersion'. A deep negative fold is
    exactly the fragility the penalty exists for."""
    cfg = LabConfig()
    g = default_genome()
    ok = compute_reward(_ev(0.8, [0.7, 0.8, 0.9, 0.75, 0.85]), g, cfg)
    fragile = compute_reward(_ev(0.8, [-0.9, 0.8, 0.9, 0.75, 2.0]), g, cfg)
    assert ok.value > fragile.value


def test_reward_penalises_excess_drawdown_and_turnover():
    cfg = LabConfig()
    g = default_genome()
    calm = compute_reward(_ev(1.0, [1.0] * 5, dd=0.10), g, cfg)
    wild = compute_reward(_ev(1.0, [1.0] * 5, dd=0.50), g, cfg)
    assert calm.value > wild.value
    churny = compute_reward(_ev(1.0, [1.0] * 5, turnover_annual=60.0), g, cfg)
    assert calm.value > churny.value


def test_reward_penalises_complexity():
    cfg = LabConfig()
    simple = default_genome().patched({"gates.use_fundamentals": False, "gates.use_news": False})
    complex_ = default_genome().patched({"gates.use_fundamentals": True, "gates.use_news": True,
                                         "regime.breadth_enabled": True,
                                         "exit.exit_on_sma_break": True})
    ev = _ev(1.0, [1.0] * 5)
    assert compute_reward(ev, simple, cfg).value > compute_reward(ev, complex_, cfg).value


def test_invalid_evaluation_scores_far_below_any_valid_one():
    cfg = LabConfig()
    bad = Evaluation("h", 1, False, reason="too few trades")
    assert compute_reward(bad, default_genome(), cfg).value < -1.0


def test_gate_tightens_as_the_search_widens():
    cfg = LabConfig()
    ev = _ev(1.2, [1.1, 1.3, 1.2, 1.0, 1.4])
    few = gate_report(ev, cfg, n_trials=5, sr_variance=0.25)
    many = gate_report(ev, cfg, n_trials=5000, sr_variance=0.25)
    assert few["deflated_sharpe"] > many["deflated_sharpe"]
    assert not many["checks"]["deflated_sharpe"]["pass"]


def test_dedupe_and_diversify():
    g = default_genome()
    props = [Proposal(genome=g, source="x"), Proposal(genome=g, source="y")]
    assert len(dedupe(props, set())) == 1
    near = g.patched({"pf.risk_pct": g["pf.risk_pct"] + 0.001})
    assert len(diversify_against([Proposal(genome=near, source="x")], [g])) == 1  # falls back


def test_tpe_moves_toward_the_good_region():
    rng = random.Random(0)
    obs = []
    for _ in range(80):
        r = rng.random()
        gg = default_genome().patched({"pf.max_positions": 4 if r < 0.5 else 28})
        obs.append((gg, 2.0 if r < 0.5 else -1.0))
    picks = TPESampler(min_observations=10).propose(obs, rng, 12)
    low = sum(1 for p in picks if p["pf.max_positions"] < 16)
    assert low >= 8, f"TPE ignored the observed good region ({low}/12)"


def test_sharpe_variance_has_a_sane_prior():
    assert sharpe_variance_across_trials([]) > 0
    assert sharpe_variance_across_trials([1.0, 0.5, -0.2, 0.9]) > 0
