"""Gate logic for the second-order chain board.

The agent this board exists for lost money three mechanical ways — it traded a
neighbour that had already moved, it got the sign backwards, and it traded
edges too small to matter. Each of those is a pure function here, so each gets
pinned.
"""

import pytest

from services.market_screenings.scripts import second_order_chain as S


# ── the sign rule ───────────────────────────────────────────────────────────
# `from -[supplier]-> to` means from SUPPLIES to (TSM->NVDA, MU->NVDA).

@pytest.mark.parametrize("role,expected", [
    ("supplier", 1), ("customer", 1), ("partner", 1),
    ("subsidiary", 1), ("acquirer", 1),
    ("competitor", -1),          # a rival's trouble is your opportunity
])
def test_only_a_competitor_moves_against_the_headline(role, expected):
    assert S._sign_for(role) == expected


# ── role normalisation ──────────────────────────────────────────────────────
# The same edge means different things depending which end the story landed on.

def test_peer_supplying_the_headline_is_a_supplier():
    # MU -[supplier]-> NVDA, story on NVDA: MU is NVDA's supplier.
    assert S._role("MU", "NVDA", "supplier", head="NVDA") == "supplier"


def test_headline_supplying_the_peer_makes_the_peer_a_customer():
    # NVDA -[supplier]-> MSFT, story on NVDA: MSFT is NVDA's customer.
    assert S._role("NVDA", "MSFT", "supplier", head="NVDA") == "customer"


def test_a_customer_edge_inverts_the_same_way():
    assert S._role("MU", "LRCX", "customer", head="LRCX") == "customer"
    assert S._role("MU", "LRCX", "customer", head="MU") == "supplier"


def test_the_symmetric_types_keep_their_label_either_way():
    for rel in ("competitor", "partner", "subsidiary", "acquirer"):
        assert S._role("A", "B", rel, head="A") == rel
        assert S._role("A", "B", rel, head="B") == rel


def test_the_trade_that_started_this():
    # LRCX -[supplier]-> MU. Story on MU, negative. LRCX is MU's SUPPLIER, so it
    # moves WITH MU -> the expected direction is short, not the long that was
    # actually taken for -$2,670.
    role = S._role("LRCX", "MU", "supplier", head="MU")
    assert role == "supplier"
    assert S._sign_for(role) * -1 == -1          # negative shock -> short


# ── contradictions ──────────────────────────────────────────────────────────

def _row(symbol, side, head, w=1.0, hr=0.10):
    return {"symbol": symbol, "side": side, "head": head, "role": "competitor",
            "head_return": hr, "edge_weight": w}


def test_a_symbol_two_stories_push_opposite_ways_is_dropped():
    # GOOG came back LONG as NVDA's customer and SHORT as META's competitor.
    out = S._resolve_conflicts([_row("GOOG", "long", "NVDA"), _row("GOOG", "short", "META")])
    assert out == []


def test_agreeing_stories_collapse_to_one_row_and_are_counted():
    out = S._resolve_conflicts([_row("INTC", "short", "NVDA", w=4.4),
                                _row("INTC", "short", "MU", w=2.1)])
    assert len(out) == 1
    assert out[0]["corroborating_heads"] == 2
    assert out[0]["head"] == "NVDA"                      # the stronger link leads
    assert [a["head"] for a in out[0]["also_linked_to"]] == ["MU"]


def test_a_single_link_carries_no_corroboration_fields():
    out = S._resolve_conflicts([_row("AMAT", "long", "MU")])
    assert len(out) == 1
    assert "corroborating_heads" not in out[0]
    assert "also_linked_to" not in out[0]


def test_distinct_symbols_are_untouched():
    out = S._resolve_conflicts([_row("AMAT", "long", "MU"), _row("TSM", "long", "NVDA")])
    assert {r["symbol"] for r in out} == {"AMAT", "TSM"}
