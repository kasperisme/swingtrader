"""Lab configuration — everything that is NOT part of the search space.

Anything the optimiser may change lives in `genome.py`. Anything that defines
the *experiment protocol* (dates, costs, folds, reward shape, acceptance gates)
lives here, so the protocol stays frozen while the strategy evolves. Changing a
value here invalidates cross-run comparability — bump `protocol_version`.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = PROJECT_ROOT / "output"
CACHE_ROOT = OUTPUT_ROOT / "cache"

_ENV_LOADED = False


def load_env() -> None:
    """Load ./.env, then fall back to the sibling analytics .env so an existing
    swingtrader checkout works with zero extra configuration."""
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover
        _ENV_LOADED = True
        return
    for candidate in (PROJECT_ROOT / ".env", PROJECT_ROOT.parent / "analytics" / ".env"):
        if candidate.exists():
            load_dotenv(candidate, override=False)
    _ENV_LOADED = True


@dataclass
class Costs:
    """Execution frictions. Deliberately pessimistic — a strategy that only
    survives at zero cost is not a strategy."""

    commission_bps: float = 1.0          # per side
    slippage_bps: float = 8.0            # per side, versus the open print
    spread_bps: float = 4.0              # half-spread paid per side
    # Capacity realism: an order above this share of 20d ADV is truncated,
    # and market impact is charged in proportion to participation.
    max_adv_participation: float = 0.05
    impact_coef_bps: float = 25.0        # bps of impact at 100% participation


@dataclass
class Splits:
    """Purged walk-forward protocol.

    dev_*   : the only data the search is ever allowed to see.
    vault_* : untouched until a genome clears the dev gate. Opened ONCE.
    embargo : trading days dropped after each fold so a position still open at
              a boundary cannot leak information into the next fold.
    """

    warmup_start: str = "2013-01-01"     # history for 200d MAs / 52w stats
    dev_start: str = "2014-01-01"
    dev_end: str = "2023-12-31"
    vault_start: str = "2024-01-01"
    vault_end: str = "2026-06-30"
    # A second unseen period, EARLIER than the dev window. Not "future" data,
    # but statistically out-of-sample all the same: no search has touched it.
    # It exists because ~250 configurations have already burned 2014-2023 while
    # the vault is too short to judge a strategy on, and because it contains two
    # systemic crises that the dev decade lacks entirely.
    #
    # It is a scarce resource. Every use is logged to the ledger, because a
    # holdout tested repeatedly is just another training set.
    holdout_start: str = "1998-01-01"
    holdout_end: str = "2013-12-31"
    n_folds: int = 5
    embargo_days: int = 10


@dataclass
class RewardWeights:
    """Reward shaping. The objective is deliberately NOT raw Sharpe — raw
    Sharpe is trivially gamed by a search with enough trials."""

    dd_budget: float = 0.25              # drawdown tolerated free of charge
    turnover_budget: float = 12.0        # annual portfolio turnover, x
    lambda_stability: float = 0.60       # penalty on dispersion of fold Sharpes
    lambda_drawdown: float = 1.20
    lambda_turnover: float = 0.25
    # Per active parameter, on a Sharpe scale. Calibrated so the incumbent's
    # ~35 active parameters cost ~0.18 — enough to break ties toward simpler
    # rule sets, not enough to dominate a base of ~0.5 and turn the search into
    # a race to the emptiest strategy.
    lambda_complexity: float = 0.005
    lambda_tail: float = 0.35            # penalty for fat left tails
    min_trades: int = 60                 # over the full dev period
    min_trades_per_fold: int = 8
    min_exposure: float = 0.10           # avg gross exposure
    max_single_fold_dd: float = 0.45     # any fold worse than this = invalid


@dataclass
class DeployGate:
    """Acceptance criteria. All must hold on DEV before the vault is opened,
    and the vault criteria again before anything lands in `deploy/`."""

    min_sharpe: float = 1.00
    min_deflated_sharpe: float = 0.95    # DSR probability, trial-count adjusted
    min_fold_win_rate: float = 0.60      # share of folds with positive Sharpe
    max_drawdown: float = 0.30
    min_trades: int = 60
    max_pbo: float = 0.35                # probability of backtest overfitting
    min_alpha_t: float = 1.50            # t-stat of alpha vs the benchmark
    vault_sharpe_floor: float = 0.60     # the vault may decay, not collapse
    vault_sharpe_ratio_floor: float = 0.50   # vault Sharpe / dev Sharpe


@dataclass
class SearchConfig:
    """How the stochastic search spends its budget."""

    proposals_per_iteration: int = 8
    # Proposal mix: LLM = structural/creative moves, TPE = exploit the observed
    # response surface, mutation = local refinement, random = anti-collapse.
    mix_llm: float = 0.375
    mix_surrogate: float = 0.25
    mix_mutation: float = 0.25
    mix_random: float = 0.125
    # Successive halving: every candidate is scored on a cheap rung, only the
    # top fraction is promoted to the full walk-forward. Multi-fidelity search
    # buys statistical power without paying for it on every candidate.
    promote_fraction: float = 0.35
    min_promoted: int = 2
    # The cheap rung spans the LAST `rung0_folds` dev folds rather than one.
    # A single fold is one regime: screening on it discards genomes that are
    # merely out of phase with that window, which is exactly the fragility the
    # reward is supposed to punish, not select for.
    rung0_folds: int = 2
    rung0_universe_cap: int = 400
    llm_context_elites: int = 6
    llm_context_recent: int = 10
    ucb_c: float = 1.20                  # exploration constant, operator bandit
    tpe_gamma: float = 0.25              # top quantile treated as "good"
    tpe_candidates: int = 64


@dataclass
class LabConfig:
    run_id: str = "default"
    # 1.2.0 — two protocol changes, so rewards are not comparable across it:
    #   * a qualification PRE-FILTER can now gate the universe before the
    #     genome sees it (see `prefilter`), and
    #   * the stability penalty measures DOWNSIDE fold dispersion rather than
    #     standard deviation, which had been penalising unusually good folds
    #     and hid a 30% Sharpe improvement from the search.
    # 1.1.0 added the short sleeve (73 -> 95 genome dimensions), which changed
    # genome hashes; metrics recorded under earlier versions remain valid for
    # their own run.
    protocol_version: str = "1.2.0"
    # A qualification screen applied BEFORE the genome sees anything. It lives
    # here rather than in the genome precisely so the search cannot switch it
    # off — that is what makes it a prior rather than another tuned parameter.
    # See prefilter.SCREENS; supports "all:", "any:" and "KofN:" ensembles.
    prefilter: str = "none"
    benchmark: str = "SPY"
    initial_equity: float = 100_000.0
    risk_free_annual: float = 0.02
    costs: Costs = field(default_factory=Costs)
    splits: Splits = field(default_factory=Splits)
    reward: RewardWeights = field(default_factory=RewardWeights)
    gate: DeployGate = field(default_factory=DeployGate)
    search: SearchConfig = field(default_factory=SearchConfig)
    llm_model: str = "claude-opus-5"
    llm_effort: str = "high"
    seed: int = 7

    @property
    def run_dir(self) -> Path:
        p = OUTPUT_ROOT / "runs" / self.run_id
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def ledger_path(self) -> Path:
        return self.run_dir / "ledger.sqlite"

    @property
    def deploy_dir(self) -> Path:
        p = self.run_dir / "deploy"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def to_dict(self) -> dict:
        return asdict(self)


def _cache(name: str) -> Path:
    p = CACHE_ROOT / name
    p.mkdir(parents=True, exist_ok=True)
    return p


def price_cache_dir() -> Path:
    return _cache("prices")


def meta_cache_dir() -> Path:
    return _cache("meta")


def fundamentals_cache_dir() -> Path:
    return _cache("fundamentals")


def news_cache_dir() -> Path:
    return _cache("news")


def fmp_key() -> str:
    load_env()
    key = os.environ.get("FMP_API_KEY") or os.environ.get("APIKEY")
    if not key:
        raise RuntimeError(
            "FMP_API_KEY (or APIKEY) not set — copy .env.example to .env, "
            "or run from a checkout with code/analytics/.env present."
        )
    return key
