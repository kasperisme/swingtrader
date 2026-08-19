"""End-to-end: context -> evaluate -> investigate -> search loop -> finalize.

Runs on synthetic prices with the LLM policy disabled, so it exercises the
whole machine deterministically and offline.
"""

import numpy as np
import pytest

from strategylab.config import LabConfig
from strategylab.features import FeatureBank
from strategylab.genome import default_genome
from strategylab.investigate import investigate
from strategylab.ledger import Ledger
from strategylab.loop import Lab
from strategylab.validation import DataContext, evaluate, evaluate_vault
from tests.conftest import synthetic_panel


@pytest.fixture(scope="module")
def ctx():
    panel = synthetic_panel(n_days=1700, n_symbols=60, seed=7)
    cfg = LabConfig(run_id="pytest")
    cfg.splits.warmup_start = "2015-01-01"
    cfg.splits.dev_start = "2016-01-01"
    cfg.splits.dev_end = "2019-12-31"
    cfg.splits.vault_start = "2020-01-01"
    cfg.splits.vault_end = "2021-12-31"
    cfg.splits.n_folds = 4
    cfg.search.rung0_universe_cap = 30
    cfg.search.proposals_per_iteration = 4
    # These tests exercise LOOP MECHANICS, not the incumbent's trade count. On
    # 60 random-walk symbols the production thresholds reject almost every
    # genome, which would make the tests about the synthetic data rather than
    # about the loop.
    cfg.reward.min_trades = 15
    cfg.reward.min_trades_per_fold = 2
    cfg.reward.min_exposure = 0.02

    bench = panel.close[:, 0]
    bench_ret = np.zeros(len(bench))
    bench_ret[1:] = bench[1:] / bench[:-1] - 1.0
    bank = FeatureBank(panel, bench)
    sectors = {s: ("Tech" if i % 3 else "Health") for i, s in enumerate(panel.symbols)}
    return DataContext(cfg, panel.symbols, sectors, panel, bank, bench, bench_ret)


@pytest.fixture
def loose_genome():
    return default_genome().patched({
        "universe.min_dollar_vol_20d": 5e5,
        "universe.min_price": 2.0,
        "gates.rs_rank_min": 30,
        "gates.min_up_down_vol": 0.6,
        "regime.enabled": False,
    })


def test_folds_are_contiguous_disjoint_and_embargoed(ctx):
    folds = ctx.folds()
    assert len(folds) >= 3
    for a, b in zip(folds, folds[1:]):
        assert a.i1 <= b.i0, "folds overlap"
        assert b.i0 - a.i1 >= ctx.cfg.splits.embargo_days - 1, "embargo not applied"
    i0, i1 = ctx.dev_range()
    v0, v1 = ctx.vault_range()
    assert folds[0].i0 >= i0 and folds[-1].i1 <= i1
    assert i1 <= v0, "dev window overlaps the vault"


def test_evaluate_produces_folds_and_metrics(ctx, loose_genome):
    ev = evaluate(loose_genome, ctx, rung=1)
    assert ev.metrics
    assert len(ev.fold_metrics) == len(ctx.folds())
    assert np.isfinite(ev.metrics["sharpe"])
    assert ev.daily_returns is not None


def test_rung0_is_cheaper_than_rung1(ctx, loose_genome):
    fast = evaluate(loose_genome, ctx, rung=0)
    full = evaluate(loose_genome, ctx, rung=1)
    assert fast.universe_size <= ctx.cfg.search.rung0_universe_cap
    assert full.universe_size > fast.universe_size
    assert len(fast.daily_returns) < len(full.daily_returns)


def test_vault_is_a_different_period_from_dev(ctx, loose_genome):
    dev = evaluate(loose_genome, ctx, rung=1)
    vault = evaluate_vault(loose_genome, ctx)
    assert vault.rung == 2
    assert len(vault.dates) > 0
    assert vault.dates[0] > dev.dates[-1]


def test_investigation_returns_actionable_findings(ctx, loose_genome):
    ev = evaluate(loose_genome, ctx, rung=1)
    d = investigate(ev, loose_genome, ctx)
    assert d.tables
    assert isinstance(d.brief(), str)
    from strategylab.genome import SPACE
    for f in d.findings:
        assert f.severity in {"high", "medium", "low"}
        for key in f.direction:
            assert key in SPACE, f"finding points at unknown genome key {key}"


def test_search_loop_runs_records_and_improves_or_holds(ctx, tmp_path):
    ledger = Ledger(tmp_path / "ledger.sqlite")
    lab = Lab(ctx.cfg, ctx, ledger, use_llm=False)
    reports = lab.run(iterations=2)

    assert reports
    assert ledger.count(distinct=True) > 1
    assert ledger.count(rung=0, distinct=False) > 0
    assert ledger.count(rung=1, distinct=False) > 0
    # Elites are ordered best-first and never regress across iterations.
    assert lab.elites == sorted(lab.elites, key=lambda e: -e[1])
    assert reports[-1].best_reward >= reports[0].best_reward - 1e-9


def test_no_genome_is_evaluated_twice_at_the_same_rung(ctx, tmp_path):
    ledger = Ledger(tmp_path / "ledger.sqlite")
    lab = Lab(ctx.cfg, ctx, ledger, use_llm=False)
    lab.run(iterations=2)
    rows = ledger.rows(rung=0, limit=10_000, order="id ASC")
    hashes = [r["genome_hash"] for r in rows]
    assert len(hashes) == len(set(hashes)), "duplicate work inflates the trial count"


def test_finalize_reports_honestly_without_opening_the_vault(ctx, tmp_path):
    ledger = Ledger(tmp_path / "ledger.sqlite")
    lab = Lab(ctx.cfg, ctx, ledger, use_llm=False)
    lab.run(iterations=1)
    final = lab.finalize(open_vault=False)
    assert "dev_gate" in final
    assert final["n_trials"] >= 1
    assert final["deployable"] is False
    assert ledger.summary()["vault_opened"] == 0, "vault must stay sealed"


def test_ledger_returns_matrix_aligns_trials(ctx, tmp_path):
    ledger = Ledger(tmp_path / "ledger.sqlite")
    lab = Lab(ctx.cfg, ctx, ledger, use_llm=False)
    lab.run(iterations=2)
    R, names = ledger.returns_matrix(rung=1)
    if R.size:
        assert R.shape[0] > 100 and R.shape[1] == len(names)
        assert np.isfinite(R).all()


def test_requesting_an_absent_overlay_is_invalid_not_silently_ignored(ctx, loose_genome):
    """The most dangerous failure mode: a gate that is on but does nothing.

    If the news overlay is unavailable and the genome asks for it, the run must
    be rejected. Evaluating it anyway would credit the overlay for a result it
    took no part in.
    """
    from strategylab.validation import evaluate

    g = loose_genome.patched({"gates.use_news": True})
    ev = evaluate(g, ctx, rung=1)
    assert not ev.valid
    assert "news" in ev.reason.lower()

    g2 = loose_genome.patched({"gates.use_fundamentals": True})
    ev2 = evaluate(g2, ctx, rung=1)
    assert not ev2.valid
    assert "fundamental" in ev2.reason.lower()


def test_feature_cache_is_bounded_under_genome_churn(ctx):
    """Genome-tunable lookbacks mint a new matrix per distinct value.

    Unbounded, a few hundred trials hold gigabytes of one-use arrays. The cache
    must evict, and the shared base features must survive eviction.
    """
    bank = ctx.bank
    bank.max_cached = 20
    base = bank.get("sma", length=200)
    for length in range(10, 200):
        bank.get("sma", length=length)
    assert len(bank._cache) <= bank.max_cached
    # A pinned base feature is still the same object, not recomputed.
    assert bank.get("sma", length=200) is base
    assert bank.memory_mb() > 0


def test_signal_cache_is_bounded(ctx, loose_genome):
    from strategylab.genome import random_genome
    import random as _r
    rng = _r.Random(0)
    for _ in range(30):
        ctx.signals_for(random_genome(rng))
    assert len(ctx._signal_cache) <= ctx._signal_cache_limit


def test_resuming_a_run_rehydrates_elite_metrics(ctx, tmp_path):
    """A resumed run must not hand the policy elites with empty scorecards."""
    from strategylab.ledger import Ledger
    from strategylab.loop import Lab

    path = tmp_path / "ledger.sqlite"
    Lab(ctx.cfg, ctx, Ledger(path), use_llm=False).run(iterations=1)

    resumed = Lab(ctx.cfg, ctx, Ledger(path), use_llm=False)
    assert resumed.elites, "resume found no elites"
    g, reward, ev = resumed.elites[0]
    assert ev is not None and ev.metrics, "elite came back without metrics"
    assert "sharpe" in ev.metrics
    # Trial history must carry over so the deflated-Sharpe bar keeps rising.
    assert len(resumed.seen) > 1


def test_seeding_carries_the_inherited_trial_count(ctx, tmp_path):
    """Restarting a search from its own winner must not reset the selection-bias
    clock. The winner is already the survivor of the trials that produced it, and
    the deflated Sharpe has to keep counting them."""
    from strategylab.genome import default_genome
    from strategylab.ledger import Ledger
    from strategylab.loop import Lab

    seed = default_genome().patched({"pf.max_positions": 14})
    ledger = Ledger(tmp_path / "child.sqlite")
    lab = Lab(ctx.cfg, ctx, ledger, use_llm=False, seed_genome=seed,
              inherited_trials=125, seed_origin="run 'parent'")
    lab.run(iterations=1)

    assert ledger.inherited_trials() == 125
    final = lab.finalize(open_vault=False)
    assert final["inherited_trials"] == 125
    assert final["n_trials"] == final["own_trials"] + 125
    assert final["n_trials"] > final["own_trials"], "ancestry was dropped"


def test_unseeded_run_inherits_nothing(ctx, tmp_path):
    from strategylab.ledger import Ledger
    from strategylab.loop import Lab

    ledger = Ledger(tmp_path / "fresh.sqlite")
    Lab(ctx.cfg, ctx, ledger, use_llm=False).run(iterations=1)
    assert ledger.inherited_trials() == 0


def test_diagnostics_do_not_claim_direction_without_significance():
    """A five-bucket Spearman of -0.40 has p = 0.50. An earlier version emitted
    'the ranking is INVERTED' as a HIGH finding at that value; the policy spent
    three proposals on it, and correcting the 'defect' cut Sharpe from 0.512 to
    0.263. Directional claims must now clear a p-value."""
    from strategylab.investigate import MONO_ALPHA, _monotonicity_p

    weak = [{"expectancy_r": v} for v in (0.76, 0.19, 0.08, -0.04, 0.36)]
    rho, p = _monotonicity_p(weak)
    assert abs(rho) < 0.9 and p > MONO_ALPHA, \
        f"a noisy bucket table read as significant: rho={rho}, p={p}"

    strong = [{"expectancy_r": v} for v in (-0.5, -0.2, 0.1, 0.4, 0.9)]
    rho2, p2 = _monotonicity_p(strong)
    assert rho2 > 0.9 and p2 < MONO_ALPHA, f"a clean monotone table was rejected: {rho2}, {p2}"


def test_inverted_ranking_finding_requires_a_real_effect():
    import numpy as np
    import pandas as pd

    from strategylab.backtest import BacktestResult, Trade
    from strategylab.genome import default_genome
    from strategylab.investigate import investigate
    from strategylab.validation import Evaluation

    def _result(scores):
        rng = np.random.default_rng(0)
        trades = []
        for i, sc in enumerate(scores):
            trades.append(Trade(
                symbol="X", sector="Tech", side=1, entry_idx=i, exit_idx=i + 5,
                entry_date=np.datetime64("2020-01-01"), exit_date=np.datetime64("2020-01-08"),
                entry_price=100.0, exit_price=101.0, shares=10.0, initial_stop=95.0,
                final_stop=95.0, risk_per_share=5.0, pnl=float(rng.normal(0, 50)),
                r_multiple=float(rng.normal(0, 1)), return_pct=1.0, hold_days=5,
                mae_r=-0.3, mfe_r=0.9, exit_reason="target", entry_score=sc,
                entry_rs_rank=90.0, entry_adr=3.0, entry_weight=0.1, costs=1.0,
                borrow_cost=0.0, truncated=False))
        n = 300
        return BacktestResult(
            dates=pd.bdate_range("2020-01-01", periods=n).values.astype("datetime64[D]"),
            equity=np.linspace(100_000, 110_000, n), cash=np.full(n, 1e5),
            exposure=np.full(n, 0.5), n_positions=np.full(n, 3),
            returns=np.full(n, 0.0003), trades=trades, initial_equity=100_000.0)

    rng = np.random.default_rng(1)
    res = _result(list(rng.uniform(0.81, 1.0, 200)))     # compressed, random scores
    ev = Evaluation("h", 1, True)
    ev.result = res
    from strategylab.metrics import summarize
    ev.metrics = summarize(res)
    d = investigate(ev, default_genome())
    assert not any("INVERTED" in f.finding for f in d.findings), \
        "claimed an inverted ranking from noise"


def test_holdout_is_a_distinct_earlier_window_and_its_use_is_counted(ctx, tmp_path):
    """The holdout is a scarce resource. A window consulted repeatedly is a
    training set with extra steps, and the only defence is counting uses."""
    from strategylab.genome import default_genome
    from strategylab.ledger import Ledger
    from strategylab.validation import evaluate_holdout

    cfg = ctx.cfg
    cfg.splits.holdout_start = "2015-01-01"
    cfg.splits.holdout_end = "2015-12-31"
    ctx._folds = None

    h0, h1 = ctx.holdout_range()
    d0, d1 = ctx.dev_range()
    assert h1 <= d0, "holdout overlaps the searched dev window"

    ledger = Ledger(tmp_path / "l.sqlite")
    assert ledger.holdout_uses() == 0
    g = default_genome().patched({"universe.min_dollar_vol_20d": 5e5,
                                  "gates.rs_rank_min": 20, "regime.enabled": False})
    evaluate_holdout(g, ctx, ledger=ledger, note="first look")
    evaluate_holdout(g, ctx, ledger=ledger, note="second look")
    assert ledger.holdout_uses() == 2, "holdout use was not recorded"
    assert ledger.summary()["holdout_uses"] == 2


def test_holdout_evaluation_is_rung_3_and_separate_from_the_vault(ctx):
    from strategylab.genome import default_genome
    from strategylab.validation import evaluate_holdout, evaluate_vault

    ctx.cfg.splits.holdout_start = "2015-01-01"
    ctx.cfg.splits.holdout_end = "2015-12-31"
    g = default_genome().patched({"universe.min_dollar_vol_20d": 5e5,
                                  "gates.rs_rank_min": 20, "regime.enabled": False})
    h = evaluate_holdout(g, ctx)
    v = evaluate_vault(g, ctx)
    assert h.rung == 3 and v.rung == 2, "holdout and vault must be distinguishable"
    if h.dates is not None and v.dates is not None and len(h.dates) and len(v.dates):
        assert h.dates[-1] < v.dates[0], "holdout and vault overlap"
