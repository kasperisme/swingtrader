"""Narrative-differencing guarantees that do not need a database.

The metric's integration check is `python -m strategylab.social.cli control
<TICKER>`, which needs Supabase and a local embedding model and is therefore not
run here. What IS pinned here is the logic that four separate failures came
down to — every one of them a case where a wrong answer looked plausible:

  * word salad scored as a narrative GAP (no topicality gate at all)
  * a verbatim quote from the ticker's own coverage scored OFF_TOPIC
    (absolute cosine thresholds, guessed)
  * a paraphrase of a circulating claim scored GAP
    (max-over-N inflated by pool size, three times in three places)
  * NKE and SBUX failing where CROX and MNST passed
    (extracted claims often omit the company name; generated theses must not)
"""

from __future__ import annotations

import numpy as np
import pytest

from strategylab.social.saturation import NarrativeSpace, _unit


class _Space(NarrativeSpace):
    """Construct without touching the database."""

    def __init__(self, entities, claims=(), dim=8, seed=0):
        rng = np.random.default_rng(seed)
        self.ticker = "TEST"
        self.entities = [e.lower() for e in entities]
        self.claims = list(claims)
        self.scope = ["TEST"]
        self.chunks = np.vstack([_unit(rng.standard_normal(dim)) for _ in range(20)])
        self.background = np.vstack([_unit(rng.standard_normal(dim)) for _ in range(20)])
        self.claim_vecs = np.zeros((0, 1))
        self.bg_claims = []
        self.bg_claim_vecs = np.zeros((0, 1))
        self.chunk_meta = [("", "", "")] * 20
        self.topicality_bar = 0.0
        self.saturation_bar = 0.0


# ----------------------------------------------------------------------
def test_entity_gate_accepts_company_and_brand_names():
    s = _Space(["CROX", "Crocs", "HEYDUDE"])
    assert s.mentions_entity("Crocs' Jibbitz charms drive recurring revenue") == "crocs"
    assert s.mentions_entity("HEYDUDE is turning around") == "heydude"
    assert s.mentions_entity("CROX will re-rate on margin expansion") == "crox"


def test_entity_gate_rejects_off_topic_and_incoherent():
    """The failure the whole two-axis design exists to prevent: text with no
    neighbours in the corpus must not read as 'nobody has noticed this yet'."""
    s = _Space(["CROX", "Crocs", "HEYDUDE"])
    assert s.mentions_entity(
        "Semiconductor foundry capacity constrains AI accelerator supply") is None
    assert s.mentions_entity(
        "The purple velocity of quarterly umbrella synergy accelerates") is None
    assert s.mentions_entity("Margins will expand next year") is None


def test_short_entities_are_ignored():
    """A two-letter 'brand' would match inside almost any word."""
    s = _Space(["GO", "ON", "Crocs"])
    assert s.mentions_entity("going on to another topic entirely") is None


# ----------------------------------------------------------------------
def test_mean_top_is_biased_by_pool_size():
    """Why every comparison in this metric is size-matched.

    This is the bug that appeared three times — in the chunk pool, the claim
    count, and the background pool. It is a property of the order statistic,
    not of the data, so it will reappear in any new comparison that is not
    matched on N.
    """
    rng = np.random.default_rng(3)
    q = _unit(rng.standard_normal(16))
    small = np.vstack([_unit(rng.standard_normal(16)) for _ in range(50)])
    large = np.vstack([_unit(rng.standard_normal(16)) for _ in range(5000)])
    top_small = NarrativeSpace._mean_top(small, q, 8)
    top_large = NarrativeSpace._mean_top(large, q, 8)
    # Both pools are pure noise with the same distribution; only N differs.
    assert top_large > top_small


def test_mean_top_matched_pools_agree():
    rng = np.random.default_rng(4)
    q = _unit(rng.standard_normal(16))
    a = np.vstack([_unit(rng.standard_normal(16)) for _ in range(500)])
    b = np.vstack([_unit(rng.standard_normal(16)) for _ in range(500)])
    diff = abs(NarrativeSpace._mean_top(a, q, 8) - NarrativeSpace._mean_top(b, q, 8))
    assert diff < 0.15


# ----------------------------------------------------------------------
def test_score_refuses_to_run_uncalibrated():
    """An uncalibrated threshold is what reported word salad as a gap."""
    s = _Space(["Crocs"])
    s.saturation_bar = float("nan")
    with pytest.raises(RuntimeError, match="calibrate"):
        s.score("Crocs will do well")


def test_reword_strips_figures_but_keeps_the_assertion():
    from strategylab.social.cli import _as_thesis, _reword
    claim = "HEYDUDE is a turnaround priority with expected revenue declines of 5-7% in 2026"
    out = _reword(claim)
    assert "HEYDUDE" in out and "turnaround" in out
    assert "2026" not in out and "%" not in out


def test_as_thesis_only_prefixes_when_the_name_is_absent():
    from strategylab.social.cli import _as_thesis
    assert _as_thesis("Revenue in China fell 30%", "NKE").startswith("NKE: ")
    named = "NKE margins are expanding"
    assert _as_thesis(named, "NKE") == named
