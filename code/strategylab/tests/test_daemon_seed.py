"""Cold-start seeding for the autonomous daemon.

The daemon carried its incumbent forward correctly *within* one process and
forgot everything on restart, falling back to the untuned default genome with
`inherited = 0`. Two consequences, the second worse than the first:

  1. every restart re-litigated ground already covered, and
  2. the deflated Sharpe deflated against a best-of-N of ~30 when the real N
     was in the hundreds — optimistic in the one direction that matters.

So these tests are mostly about `inherited`, not about the genome.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from strategylab.autonomous.daemon import Daemon
from strategylab.config import LabConfig
from strategylab.genome import Genome, default_genome
from strategylab.ledger import Ledger, Trial


def _ledger(root: Path, run: str, entries: list[tuple[str, float, float]]) -> None:
    """Write a ledger with (tag, reward, sharpe) rows at rung 1.

    The genome hash is derived from the genome, so each row perturbs a
    dimension to make the configurations genuinely distinct — `count(distinct)`
    is the number under test.
    """
    path = root / run / "ledger.sqlite"
    path.parent.mkdir(parents=True, exist_ok=True)
    led = Ledger(path)
    for i, (_tag, reward, sharpe) in enumerate(entries):
        g = default_genome()
        g["entry.max_extension_pct"] = round(3.0 + reward * 10 + i * 0.11, 3)
        led.record(Trial(genome=g, rung=1, valid=True, reward=reward,
                         sharpe=sharpe, metrics={"sharpe": sharpe}, iteration=1,
                         operator="test", source="test"))


@pytest.fixture
def daemon(tmp_path, monkeypatch):
    cfg = LabConfig(run_id="test")
    d = Daemon.__new__(Daemon)          # no ctx / client needed for seeding
    d.cfg = cfg
    d.history = []
    d.runs_root = tmp_path / "runs"
    d.runs_root.mkdir(parents=True, exist_ok=True)
    return d


def test_no_prior_runs_starts_from_default(daemon):
    genome, inherited, origin = daemon._seed_for_next_campaign()
    assert genome is None
    assert inherited == 0
    assert origin == ""


def test_cold_start_recovers_the_incumbent(daemon):
    _ledger(daemon.runs_root, "evolve1", [("aaa", 0.10, 0.30), ("bbb", 0.20, 0.41)])
    _ledger(daemon.runs_root, "evolve2", [("ccc", 0.28, 0.46)])

    genome, inherited, origin = daemon._seed_for_next_campaign()
    assert isinstance(genome, Genome)
    assert inherited == 3, "every configuration searched counts, not just the winner's run"
    assert "evolve2" in origin


def test_inherited_counts_every_ledger_not_just_the_winning_one(daemon):
    """The seed is the argmax over all runs, so all runs are the best-of-N."""
    _ledger(daemon.runs_root, "a", [(f"a{i}", 0.01 * i, 0.1) for i in range(20)])
    _ledger(daemon.runs_root, "b", [("winner", 0.9, 0.8)])

    _, inherited, _ = daemon._seed_for_next_campaign()
    assert inherited == 21, "charging only the winning run understates the search"


def test_in_process_history_takes_precedence_over_disk(daemon, tmp_path, monkeypatch):
    """A live campaign is more current than an archived ledger."""
    _ledger(daemon.runs_root, "old", [("archived", 0.9, 0.9)])

    class Res:
        run_id = "auto-live"
    daemon.history = [Res()]
    live = tmp_path / "live"
    live.mkdir()
    _ledger(tmp_path, "live", [("fresh", 0.5, 0.5)])
    monkeypatch.setattr(LabConfig, "ledger_path",
                        property(lambda self: tmp_path / "live" / "ledger.sqlite"))

    _, _, origin = daemon._seed_for_next_campaign()
    assert "auto-live" in origin, "in-process history must win over disk"


def test_unreadable_ledger_is_skipped_not_fatal(daemon):
    _ledger(daemon.runs_root, "good", [("ok", 0.3, 0.4)])
    bad = daemon.runs_root / "corrupt"
    bad.mkdir(parents=True, exist_ok=True)
    (bad / "ledger.sqlite").write_bytes(b"not a database")

    genome, inherited, origin = daemon._seed_for_next_campaign()
    assert genome is not None, "one corrupt ledger must not stop the daemon"
    assert "good" in origin


def test_genome_predating_new_dimensions_is_repaired(daemon):
    """Old winners were saved with fewer knobs; they must still load."""
    path = daemon.runs_root / "ancient" / "ledger.sqlite"
    path.parent.mkdir(parents=True, exist_ok=True)
    _ledger(daemon.runs_root, "ancient", [("old", 0.4, 0.5)])
    # Rewrite the stored genome to one missing 20 dimensions, as an evolve2-era
    # winner is (73 dims stored against 102 in the current space).
    partial = dict(default_genome())
    for key in list(partial)[:20]:
        partial.pop(key)
    led = Ledger(path)
    led.conn.execute("UPDATE trials SET genome_json=?", (json.dumps(partial),))
    led.conn.commit()

    genome, inherited, _ = daemon._seed_for_next_campaign()
    assert genome is not None
    assert len(genome) == len(default_genome()), "missing dimensions get defaults"
    assert inherited == 1


# --------------------------------------------------------------------------
# Trial counting feeds the deflated Sharpe and the deploy gate. Under-counting
# inflates DSR and makes the gate easier to clear, so it has to be one number
# used everywhere, not a per-call-site choice.

def test_n_trials_includes_inherited(tmp_path):
    from strategylab.loop import Lab
    from strategylab.validation import build_context  # noqa: F401  (import shape check)

    path = tmp_path / "runs" / "r" / "ledger.sqlite"
    _ledger(tmp_path / "runs", "r", [("a", 0.1, 0.2), ("b", 0.2, 0.3)])
    led = Ledger(path)
    led.log_event("run_started", {"inherited_trials": 522})

    lab = Lab.__new__(Lab)
    lab.ledger = led
    assert led.count(distinct=True) == 2
    assert led.inherited_trials() == 522
    assert lab.n_trials() == 524, "the whole search, not just this run's slice"


def test_n_trials_without_ancestry_is_just_own_count(tmp_path):
    from strategylab.loop import Lab
    _ledger(tmp_path / "runs", "solo", [("a", 0.1, 0.2)])
    lab = Lab.__new__(Lab)
    lab.ledger = Ledger(tmp_path / "runs" / "solo" / "ledger.sqlite")
    assert lab.n_trials() == 1


def test_daemon_campaign_records_its_ancestry(tmp_path):
    """The daemon drives its own loop; if it skips log_run_start, the ledger
    reads back zero ancestry and every DSR it publishes is too high."""
    import inspect
    from strategylab.autonomous.daemon import Daemon

    src = inspect.getsource(Daemon._run_campaign)
    assert "log_run_start()" in src, (
        "the daemon must record run_started itself — it never calls Lab.run()")


def test_log_run_start_persists_inherited_trials(tmp_path):
    from strategylab.loop import Lab

    _ledger(tmp_path / "runs", "r", [("a", 0.1, 0.2)])
    led = Ledger(tmp_path / "runs" / "r" / "ledger.sqlite")

    lab = Lab.__new__(Lab)
    lab.ledger = led
    lab.inherited_trials = 522
    lab.seed_origin = "8 prior runs"
    lab.seed_genome = None
    lab.policy = None

    class _Splits:
        dev_start = dev_end = vault_start = vault_end = "2020-01-01"

    class _Cfg:
        splits = _Splits()
        protocol_version = "1.2.0"
        benchmark = "SPY"

    class _Panel:
        symbols = ["A", "B"]

    class _Ctx:
        panel = _Panel()
        dates = [1, 2, 3]

    lab.cfg, lab.ctx = _Cfg(), _Ctx()
    lab.log_run_start()

    assert led.inherited_trials() == 522
    assert lab.n_trials() == 523, "own trials plus recovered ancestry"
