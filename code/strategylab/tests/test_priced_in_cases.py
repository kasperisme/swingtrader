"""The deterministic halves of a per-driver case.

`case.py` produces three things and only one of them is a language model's. The
other two are the ones that can be wrong without looking wrong:

* `narrative_read` reports a SIGNED impact per claim, which it can only do
  because `NarrativeSpace.claim_vecs` is built from `own_claims` in the order it
  was handed them. If that alignment ever slips, every case still renders — with
  another claim's sentiment attached to it.
* `measure` dispatches a data series off the driver's `observable`. Most
  observables are not wired, and the failure this programme cares about is a
  quiet substitution: reporting something measured when nothing was.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pytest

from strategylab.social import case as case_mod


@dataclass
class _Claim:
    text: str
    impact: float
    published: date = date(2026, 1, 1)


class _Space:
    def __init__(self, vecs):
        self.claim_vecs = np.array(vecs, dtype=float)


@pytest.fixture
def unit_embed(monkeypatch):
    """`embed` returns the vector named by the text; `_unit` passes it through."""
    from strategylab.social import saturation

    table = {"a": [1.0, 0.0], "b": [0.0, 1.0], "mid": [0.7071, 0.7071]}
    monkeypatch.setattr(saturation, "embed", lambda t, **k: table[t])
    monkeypatch.setattr(saturation, "_unit", lambda v: np.array(v, dtype=float))


def test_impact_comes_from_the_aligned_claim(unit_embed):
    """The nearest claim's OWN impact is reported, not a neighbour's."""
    space = _Space([[1.0, 0.0], [0.0, 1.0]])
    claims = [_Claim("claim about a", +0.9), _Claim("claim about b", -0.9)]

    read = case_mod.narrative_read(space, "a", claims, top_k=1)
    assert read["top"][0]["text"] == "claim about a"
    assert read["net_impact"] == pytest.approx(0.9)

    read = case_mod.narrative_read(space, "b", claims, top_k=1)
    assert read["top"][0]["text"] == "claim about b"
    assert read["net_impact"] == pytest.approx(-0.9)


def test_extra_vectors_never_index_past_the_claims(unit_embed):
    """A mismatch truncates rather than throwing — or worse, wrapping around."""
    space = _Space([[1.0, 0.0], [0.0, 1.0], [1.0, 0.0]])
    read = case_mod.narrative_read(space, "a", [_Claim("only one", 0.5)], top_k=3)
    assert read["n_claims_scanned"] == 1
    assert len(read["top"]) == 1


def test_the_relatedness_bar_is_measured_not_chosen(unit_embed):
    """One claim on-topic among off-topic ones clears its own corpus's bar."""
    space = _Space([[1.0, 0.0], [0.0, 1.0], [0.0, 1.0], [0.0, 1.0]])
    claims = [_Claim("on topic", 0.4)] + [_Claim(f"off {i}", -0.4) for i in range(3)]
    read = case_mod.narrative_read(space, "a", claims, top_k=4)
    assert read["n_related"] == 1
    assert read["top"][0]["text"] == "on topic"


def test_a_uniformly_on_topic_corpus_reports_all_of_it(unit_embed):
    """Every claim matching equally is not a failure — they are all related."""
    space = _Space([[1.0, 0.0], [1.0, 0.0], [1.0, 0.0]])
    claims = [_Claim(f"same {i}", 0.1) for i in range(3)]
    read = case_mod.narrative_read(space, "a", claims)
    assert read["n_related"] == 3
    assert not read["note"]


def test_nothing_clearing_the_bar_is_said_rather_than_shown_as_silence(unit_embed):
    """A left-skewed corpus can put the bar above its own maximum.

    Three middling matches and one far outlier: mean + 1 sd lands above the best
    of them, so nothing is "related" and the honest output is the nearest claim
    plus a note, not an empty read the caller would mistake for no coverage.
    """
    space = _Space([[0.7071, 0.7071]] * 3 + [[0.0, 1.0]])
    claims = [_Claim(f"middling {i}", 0.2) for i in range(3)] + [
        _Claim("unrelated", -0.9)]
    read = case_mod.narrative_read(space, "a", claims, top_k=4)
    assert read["n_related"] == 0
    assert "does not speak to this driver" in read["note"]
    assert len(read["top"]) == 1
    assert read["top"][0]["text"].startswith("middling")


def test_no_claims_is_reported_not_crashed():
    read = case_mod.narrative_read(_Space([]), "a", [])
    assert read["n_claims_scanned"] == 0
    assert read["top"] == []


# ----------------------------------------------------------------------
def test_an_unwired_observable_reports_the_gap():
    m = case_mod.measure("CROX", {"observable": "pricing"})
    assert m["testable"] is False
    assert m["result"] is None
    assert "NOT wired" in m["note"]


def test_a_driver_with_no_observable_is_not_silently_testable():
    m = case_mod.measure("CROX", {})
    assert m["testable"] is False
    assert m["result"] is None
    assert m["note"]


def test_a_wired_observable_runs_its_tool(monkeypatch):
    from strategylab.social import tools

    monkeypatch.setitem(tools.TOOLS, "segment_revenue_history",
                        lambda t: {"product": [{"Franchise": {"revenue": 1}}]})
    m = case_mod.measure("PLNT", {"observable": "unit_volumes"})
    assert m["tool"] == "segment_revenue_history"
    assert m["result"] is not None


def test_a_dead_tool_is_a_fact_about_the_evidence_not_an_exception(monkeypatch):
    from strategylab.social import tools

    def _boom(_t):
        raise RuntimeError("FMP said no")

    monkeypatch.setitem(tools.TOOLS, "segment_revenue_history", _boom)
    m = case_mod.measure("PLNT", {"observable": "unit_volumes"})
    assert m["result"] is None
    assert "FMP said no" in m["error"]


def test_attention_series_is_given_the_brand_not_the_ticker(monkeypatch):
    from strategylab.social import tools

    seen = {}
    monkeypatch.setitem(tools.TOOLS, "attention_series",
                        lambda t, e: seen.update(ticker=t, entity=e) or {"obs": 1})
    case_mod.measure("CROX", {"observable": "consumer_attention"}, entity="HEYDUDE")
    assert seen == {"ticker": "CROX", "entity": "HEYDUDE"}
