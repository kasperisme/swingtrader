"""Deployment artifacts must be honest and self-consistent."""

import json

from strategylab.config import LabConfig, OUTPUT_ROOT
from strategylab.deploy import export, strategy_card
from strategylab.genome import default_genome
from strategylab.ledger import Ledger, Trial
from strategylab.report import run_report


def _final(deployable: bool) -> dict:
    return {
        "genome_hash": "abc123",
        "genome": dict(default_genome()),
        "reward": 0.72,
        "dev_metrics": {"sharpe": 1.15, "max_drawdown": 0.21, "n_trades": 420,
                        "cagr": 0.19, "expectancy_r": 0.14, "beta": 0.4,
                        "alpha_t": 2.1, "turnover_annual": 7.5},
        "vault_metrics": {"sharpe": 0.82, "max_drawdown": 0.18, "n_trades": 96},
        "fold_metrics": [{"fold": "fold1", "start": "2014-01-01", "end": "2015-12-31",
                          "sharpe": 1.0, "return": 0.2, "max_drawdown": 0.1, "n_trades": 90}],
        "n_trials": 312,
        "pbo": 0.22,
        "pbo_sample_size": 60,
        "dev_gate": {"pass": True, "deflated_sharpe": 0.97, "checks": {}, "failed": []},
        "final_gate": {"pass": deployable, "deflated_sharpe": 0.97, "failed": []
                       if deployable else ["vault_retention"],
                       "checks": {"sharpe": {"actual": 1.15, "threshold": 1.0,
                                             "op": ">=", "pass": True},
                                  "vault_retention": {"actual": 0.71, "threshold": 0.5,
                                                      "op": ">=", "pass": deployable}}},
        "deployable": deployable,
        "diagnostics": "[MEDIUM/exits] some finding",
    }


def test_export_writes_every_artifact(tmp_path, monkeypatch):
    monkeypatch.setattr("strategylab.config.OUTPUT_ROOT", tmp_path)
    cfg = LabConfig(run_id="pytest_deploy")
    monkeypatch.setattr(type(cfg), "deploy_dir",
                        property(lambda self: _mk(tmp_path / "deploy")))
    out = export(cfg, default_genome(), _final(True))
    for name in ("strategy.json", "strategy_card.md", "signals.py", "nis_evolved.py"):
        assert (out / name).exists(), name

    spec = json.loads((out / "strategy.json").read_text())
    assert spec["deployable"] is True
    # The protocol travels with the genome — a strategy without the conditions
    # it was validated under is not reproducible.
    assert spec["protocol"]["splits"]["vault_start"]
    assert spec["protocol"]["costs"]["slippage_bps"] > 0
    assert set(spec["genome"]) == set(default_genome())

    # The generated scripts must at least be valid Python.
    import ast
    for name in ("signals.py", "nis_evolved.py"):
        ast.parse((out / name).read_text())


def test_strategy_card_refuses_to_look_good_when_it_failed():
    card = strategy_card(LabConfig(), default_genome(), _final(False))
    assert "NOT DEPLOYABLE" in card
    assert "Do not trade this" in card
    # The search size must be on the card — it is part of the result.
    assert "312" in card
    assert "Known limitations" in card
    assert "survivorship" in card.lower()


def test_strategy_card_shows_dev_and_vault_side_by_side():
    card = strategy_card(LabConfig(), default_genome(), _final(True))
    assert "DEPLOYABLE" in card
    assert "dev (searched)" in card and "vault (sealed)" in card
    assert "1.15" in card and "0.82" in card


def test_report_renders_from_a_ledger(tmp_path):
    cfg = LabConfig(run_id="pytest_report")
    ledger = Ledger(tmp_path / "l.sqlite")
    g = default_genome()
    ledger.record(Trial(genome=g, rung=1, valid=True, reward=0.5, sharpe=1.1,
                        metrics={"sharpe": 1.1, "max_drawdown": 0.2, "n_trades": 300,
                                 "expectancy_r": 0.12},
                        source="seed", operator="baseline"))
    text = run_report(cfg, ledger, _final(True))
    assert g.hash in text
    assert "Deployable" in text
    assert "PBO" in text


def _mk(p):
    p.mkdir(parents=True, exist_ok=True)
    return p


def test_generated_registry_script_resolves_the_right_project_root(tmp_path):
    """The generated screening script computes the strategylab path by walking
    up from its own install location. An off-by-one here fails only in
    production, months later, as an ImportError."""
    from pathlib import Path
    from strategylab.deploy import _registry_script

    src = _registry_script(default_genome())
    assert "parents[4]" in src

    # Simulate the documented install location and check the walk lands on the
    # sibling `strategylab` project.
    fake = Path("/repo/code/analytics/services/market_screenings/scripts/nis_evolved.py")
    assert fake.parents[4] / "strategylab" == Path("/repo/code/strategylab")


def test_generated_signals_script_resolves_the_project_root():
    from pathlib import Path
    from strategylab.deploy import _SIGNALS_SCRIPT

    assert "parents[3]" in _SIGNALS_SCRIPT
    # The script walks up from HERE = the file's PARENT directory (deploy/),
    # not from the file itself: deploy -> <run_id> -> runs -> output -> project.
    here = Path("/repo/code/strategylab/output/runs/r1/deploy/signals.py").parent
    assert here.parents[3] == Path("/repo/code/strategylab")
