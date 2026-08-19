"""Tests for the Supabase research publisher.

These run against a stub connection, not a real database. What is worth testing
here is not that psycopg2 works — it is the editorial policy encoded in the
module: that an unreplicated finding cannot be marked visible, that every claim
carries a caveat, and that the honest-caveat text actually changes with status.
Those are the properties that keep a p=0.53 result off a public page.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from strategylab.autonomous.findings import Finding, FindingStore, Status
from strategylab.autonomous.publish import ResearchPublisher, _slugify


class FakeCursor:
    def __init__(self, sink): self.sink = sink
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def execute(self, sql, params=None): self.sink.append((sql, params))
    def fetchone(self): return (4,)


class FakeConn:
    def __init__(self): self.calls, self.commits = [], 0
    def cursor(self): return FakeCursor(self.calls)
    def commit(self): self.commits += 1
    def close(self): pass


@pytest.fixture
def pub():
    p = ResearchPublisher(schema="swingtrader")
    p._conn = FakeConn()
    return p


def test_slugify_is_url_safe():
    assert _slugify("Momentum decay: 1999-2026?!") == "momentum-decay-1999-2026"
    assert _slugify("") == "untitled"
    assert len(_slugify("x" * 200)) <= 80


def test_ready_requires_all_four_tables(pub):
    assert pub.ready() == (True, "")


def test_only_credible_findings_become_visible(tmp_path, pub):
    """The core editorial rule: seen-once is recorded, never published."""
    store = FindingStore(tmp_path / "f.sqlite")
    store.observe(Finding(claim="prefilter adds 0.156 Sharpe", source="run1"))
    pub.publish_findings(store, only_confirmed=False)

    published = [params[-1] for sql, params in pub._conn.calls
                 if "research_findings" in sql]
    assert published == [False], "an unreplicated finding must not be visible"


def test_confirmed_finding_is_published(tmp_path, pub):
    store = FindingStore(tmp_path / "f.sqlite")
    store.observe(Finding(claim="vol scaling lifts Sharpe", source="run1"))
    store.record_attempt("vol scaling lifts Sharpe", replicated=True)
    store.record_attempt("vol scaling lifts Sharpe", replicated=True)
    assert store.get("vol scaling lifts Sharpe").credible

    pub.publish_findings(store, only_confirmed=True)
    rows = [params for sql, params in pub._conn.calls if "research_findings" in sql]
    assert len(rows) == 1 and rows[0][-1] is True


def test_a_single_refutation_unpublishes(tmp_path, pub):
    store = FindingStore(tmp_path / "f.sqlite")
    store.observe(Finding(claim="impact law holds out of sample"))
    store.record_attempt("impact law holds out of sample", replicated=True)
    store.record_attempt("impact law holds out of sample", replicated=True)
    store.record_attempt("impact law holds out of sample", replicated=False)

    pub.publish_findings(store, only_confirmed=False)
    rows = [params for sql, params in pub._conn.calls if "research_findings" in sql]
    assert all(r[-1] is False for r in rows)


def test_every_finding_carries_a_caveat(tmp_path, pub):
    """A claim must never travel without its counterweight."""
    store = FindingStore(tmp_path / "f.sqlite")
    for claim in ("a", "b"):
        store.observe(Finding(claim=claim))
    store.record_attempt("b", replicated=False)

    pub.publish_findings(store, only_confirmed=False)
    caveats = [params[6] for sql, params in pub._conn.calls
               if "research_findings" in sql]
    assert caveats and all(c and len(c) > 40 for c in caveats)
    assert any("Refuted" in c for c in caveats), "a refutation must say so"


def test_caveat_distinguishes_replicated_from_seen_once():
    f_new = Finding(claim="x", replications=0)
    f_rep = Finding(claim="x", replications=2, status=Status.CONFIRMED)
    assert "not yet independently" in ResearchPublisher._caveat_for(f_new)
    assert "Replicated on data" in ResearchPublisher._caveat_for(f_rep)
    # even a confirmed result is not sold as a track record
    assert "not a live track record" in ResearchPublisher._caveat_for(f_rep)


def test_note_extracts_title_and_defaults_to_draft(tmp_path, pub):
    md = tmp_path / "note.md"
    md.write_text("# Momentum Decay Is Not Real\n\nThe test returned rho=0.00.\n")
    slug = pub.publish_note(md)
    assert slug == "momentum-decay-is-not-real"
    sql, params = pub._conn.calls[-1]
    assert params[1] == "Momentum Decay Is Not Real"
    assert params[2].startswith("The test returned")
    assert params[-1] is False, "notes must default to draft, not live"


def test_note_defaults_to_negative_result_kind(tmp_path, pub):
    md = tmp_path / "n.md"
    md.write_text("# T\n\nbody\n")
    pub.publish_note(md)
    assert pub._conn.calls[-1][1][4] == "negative"


def test_strategy_row_requires_selection_bias_columns(pub):
    from strategylab.genome import default_genome
    g = default_genome()
    pub.publish_strategy(g, "run1", dev_metrics={"sharpe": 0.51}, fold_metrics=[],
                         trials_considered=743, deflated_sharpe=0.08, pbo=0.31,
                         gate_passed=False, gate_failures=["dsr"])
    sql, params = pub._conn.calls[-1]
    assert 743 in params and 0.08 in params
    # the genome must round-trip so a reader can re-run it
    stored = json.loads(params[2])
    assert stored == {k: v for k, v in dict(g).items()}, "the full genome, not a subset"


# --------------------------------------------------------------------------
# Published articles must not reference this machine, this repo, or this test
# suite. A reader cannot run our CLI and gains nothing from a test id; worse,
# a printed command that cannot work reads as a reproduction recipe while
# being unusable to everyone who reads it.

INTERNAL_SAMPLES = [
    "Run it with `.venv/bin/python -m strategylab.flow.cli stage1 --min-names 60`",
    "cd code/strategylab",
    "pinned as a regression test (`tests/test_flow.py::test_ema_manufactures`)",
    "Artifacts: `output/flow/stage1/{stage1.json, panel.csv.gz}`",
    "Reproduce: `python /tmp/ablate.py` (or the variants in `tests/test_x.py`).",
    "The repo has `services/pairs/` to build on.",
]


@pytest.mark.parametrize("sample", INTERNAL_SAMPLES)
def test_internal_references_are_stripped(sample):
    cleaned = ResearchPublisher._deinternalise(sample)
    assert ResearchPublisher.audit_internal_references(cleaned) == []


def test_audit_detects_what_the_transform_would_miss():
    """The audit is the backstop, so it must actually fire."""
    assert ResearchPublisher.audit_internal_references(
        "run .venv/bin/python now") != []
    assert ResearchPublisher.audit_internal_references("a clean sentence") == []


def test_real_notes_publish_clean(tmp_path):
    for sample in INTERNAL_SAMPLES:
        assert ResearchPublisher.audit_internal_references(
            ResearchPublisher._deinternalise(f"# T\n\n{sample}\n")) == []


def test_note_with_internal_refs_cannot_go_live(tmp_path, pub, caplog):
    """The gate, not the transform, is what makes this safe."""
    md = tmp_path / "leaky.md"
    md.write_text("# Leaky\n\nSee dot-venv-slash-bin.\n")
    # Force a leftover past the transform to prove the gate is independent.
    orig = ResearchPublisher._deinternalise
    try:
        ResearchPublisher._deinternalise = staticmethod(lambda t: t + "\n.venv/bin/python\n")
        pub.publish_note(md, published=True)
    finally:
        ResearchPublisher._deinternalise = orig
    assert pub._conn.calls[-1][1][-1] is False, "must be forced back to draft"


def test_clean_note_still_publishes_live(tmp_path, pub):
    md = tmp_path / "clean.md"
    md.write_text("# Clean\n\nThe estimator returns rho near zero.\n")
    pub.publish_note(md, published=True)
    assert pub._conn.calls[-1][1][-1] is True


def test_leading_h1_is_dropped_from_the_body():
    """The title is rendered by the page; leaving it in prints it twice."""
    out = ResearchPublisher._deinternalise("# Stage 1 result\n\nVerdict: nothing.\n")
    assert not out.lstrip().startswith("#")
    assert "Verdict" in out


def test_inner_headings_survive():
    out = ResearchPublisher._deinternalise("# Title\n\nintro\n\n## Method\n\nbody\n")
    assert "## Method" in out
