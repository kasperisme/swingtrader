"""The thesis lab's own guarantees, pinned.

`test_discover.py` pins the discovery loop in both directions — it must find a
planted signal and must confirm nothing on noise. The equivalent obligations
here are structural rather than statistical: the chain must be terminal on a
broken link, a data gap must not read as a refutation, and a claim with no
stated kill condition must not be constructible at all.
"""

from __future__ import annotations

import pytest

from strategylab.thesis.thesis import (BLOCKED, FAILS, HOLDS, INCONCLUSIVE,
                                       PENDING, Link, LinkResult, Thesis,
                                       link_bar)


def _link(lid: str, **kw) -> Link:
    base = dict(claim="c", null="n", outcome="o", control="ctl", kill="k",
                data=("d",))
    base.update(kw)
    return Link(id=lid, **base)


def _thesis(*links: Link) -> Thesis:
    return Thesis(id="T", title="t", mechanism="m", links=tuple(links))


# ----------------------------------------------------------------------
# A claim you cannot refute is not a test.
# ----------------------------------------------------------------------
@pytest.mark.parametrize("missing", ["claim", "null", "control", "kill"])
def test_link_without_a_stated_kill_condition_refuses_to_construct(missing):
    with pytest.raises(ValueError, match=missing):
        _link("L1", **{missing: "   "})


def test_unknown_cost_tier_is_rejected():
    with pytest.raises(ValueError, match="cost"):
        _link("L1", cost="free-ish")


def test_a_thesis_needs_at_least_one_link():
    with pytest.raises(ValueError, match="tests nothing"):
        Thesis(id="T", title="t", mechanism="m", links=())


def test_duplicate_link_ids_are_rejected():
    with pytest.raises(ValueError, match="duplicate"):
        _thesis(_link("L1"), _link("L1"))


# ----------------------------------------------------------------------
# Chain semantics: the whole point of a thesis over a hypothesis.
# ----------------------------------------------------------------------
def test_one_broken_link_kills_the_chain_even_when_the_rest_hold():
    th = _thesis(_link("L1"), _link("L2"), _link("L3"))
    results = {"L1": LinkResult("L1", verdict=HOLDS),
               "L2": LinkResult("L2", verdict=FAILS),
               "L3": LinkResult("L3", verdict=HOLDS)}
    verdict, reason = th.verdict(results)
    assert verdict == FAILS
    assert "L2" in reason


def test_a_chain_holds_only_when_every_link_holds():
    th = _thesis(_link("L1"), _link("L2"))
    assert th.verdict({"L1": LinkResult("L1", verdict=HOLDS),
                       "L2": LinkResult("L2", verdict=HOLDS)})[0] == HOLDS
    # One link never run is PENDING, not HOLDS — no partial credit.
    assert th.verdict({"L1": LinkResult("L1", verdict=HOLDS)})[0] == PENDING


def test_missing_data_does_not_read_as_a_refutation():
    """BLOCKED and INCONCLUSIVE must never collapse into FAILS.

    This project's news history is 16.5 months, so a link over it is
    underpowered by construction. Reporting that as 'the thesis is refuted'
    would retire a mechanism on the strength of a data gap.
    """
    th = _thesis(_link("L1"))
    assert th.verdict({"L1": LinkResult("L1", verdict=BLOCKED)})[0] == BLOCKED
    assert th.verdict({"L1": LinkResult("L1", verdict=INCONCLUSIVE)})[0] == INCONCLUSIVE
    assert LinkResult("L1", verdict=BLOCKED).terminal is False
    assert LinkResult("L1", verdict=FAILS).terminal is True


# ----------------------------------------------------------------------
# Test order: spend the least money on the most likely refutation.
# ----------------------------------------------------------------------
def test_cheapest_and_pivotal_links_run_first():
    th = _thesis(_link("L1", cost="free"),
                 _link("L2", cost="paid", pivotal=True),
                 _link("L3", cost="free", pivotal=True),
                 _link("L4", cost="cheap"))
    assert [l.id for l in th.test_order()] == ["L3", "L1", "L4", "L2"]


def test_declaration_order_is_preserved_within_a_tier():
    th = _thesis(_link("L1"), _link("L2"), _link("L3"))
    assert [l.id for l in th.test_order()] == ["L1", "L2", "L3"]


# ----------------------------------------------------------------------
# The bar. Getting this wrong in either direction is a real failure.
# ----------------------------------------------------------------------
def test_a_preregistered_directional_link_is_one_test():
    """It was specified in advance, so it is not the maximum of a search and
    must not inherit the lab's trial count — that would make an honest
    replication unfalsifiable."""
    ln = _link("L1", direction=1)
    assert ln.preregistered
    assert link_bar(ln, local_trials=1) == pytest.approx(2.0)
    assert link_bar(ln, local_trials=500) == pytest.approx(2.0)


def test_an_exploratory_link_pays_for_every_arm_in_its_thesis():
    ln = _link("L1", direction=0)
    assert not ln.preregistered
    b1, b10, b500 = (link_bar(ln, n) for n in (1, 10, 500))
    assert b1 < b10 < b500
    # sqrt(2 ln N) + 0.5 — the same arithmetic the discovery loop uses.
    assert b500 == pytest.approx(4.03, abs=0.02)


def test_the_bar_a_search_of_this_width_produces_from_nothing():
    """Twenty arms of pure noise produce a maximum |t| near 2.4; the bar must
    sit above it or the lab confirms its own noise."""
    import numpy as np
    rng = np.random.default_rng(0)
    max_t = np.abs(rng.standard_normal((400, 20))).max(axis=1)
    assert link_bar(_link("L1", direction=0), 20) > np.median(max_t)


def test_a_refuted_link_is_terminal_even_when_upstream_links_never_ran():
    """The bug the first real L2 run exposed.

    L2 is pivotal and cheap, so it runs first and L1 is still PENDING when it
    comes back FAILS. Walking the chain in causal order reported
    'PENDING — L1 not yet run', which reads as an instruction to go and run L1
    on a thesis that is already dead. Cost-ordered testing only saves money if
    the verdict respects it.
    """
    th = _thesis(_link("L1"), _link("L2", pivotal=True), _link("L3"))
    verdict, reason = th.verdict({"L2": LinkResult("L2", verdict=FAILS)})
    assert verdict == FAILS
    assert "L2" in reason


def test_pending_still_reported_when_nothing_has_failed():
    th = _thesis(_link("L1"), _link("L2"))
    assert th.verdict({"L2": LinkResult("L2", verdict=HOLDS)})[0] == PENDING
