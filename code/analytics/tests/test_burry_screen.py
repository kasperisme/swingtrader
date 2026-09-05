"""Gate logic for the Burry deep-value board.

Pure-function tests over the value gates. The attention half is a SQL query
against live coverage data and is exercised by running the board; what is
asserted here is the arithmetic that decides whether a name is cheap, which is
the part a bad edit would break silently.
"""

import pytest

from services.market_screenings.scripts import burry_deep_value as B


def _v(ev=8.0, fcf=0.08, lev=1.5, wc=None):
    return {
        "ev_to_ebitda": ev, "fcf_yield": fcf,
        "net_debt_to_ebitda": lev, "working_capital": wc,
    }


# ── the long gate ───────────────────────────────────────────────────────────

def test_cheap_cash_generative_and_unlevered_passes():
    assert B._passes_long(_v(), "Industrials")


def test_the_ceiling_is_sector_relative():
    # Burry is explicit that the acceptable multiple differs by industry:
    # 15x is fine for software and not for a driller.
    assert B._passes_long(_v(ev=15.0), "Technology")
    assert not B._passes_long(_v(ev=15.0), "Energy")


def test_a_negative_multiple_is_an_ebitda_loss_not_a_bargain():
    # The trap this gate exists for: -3x sorts below every ceiling.
    assert not B._passes_long(_v(ev=-3.0), "Industrials")


def test_zero_ev_ebitda_is_rejected_too():
    assert not B._passes_long(_v(ev=0.0), "Industrials")


def test_negative_free_cash_flow_disqualifies_however_cheap():
    assert not B._passes_long(_v(ev=2.0, fcf=-0.05), "Industrials")


def test_a_thin_fcf_yield_is_not_enough():
    assert not B._passes_long(_v(fcf=0.01), "Industrials")


def test_too_much_leverage_disqualifies():
    assert not B._passes_long(_v(lev=6.0), "Industrials")


def test_missing_leverage_does_not_disqualify():
    # An absent field is unknown, not bad — the other two gates still bind.
    assert B._passes_long(_v(lev=None), "Industrials")


def test_missing_multiple_or_fcf_always_fails():
    assert not B._passes_long(_v(ev=None), "Industrials")
    assert not B._passes_long(_v(fcf=None), "Industrials")


def test_an_unknown_sector_falls_back_to_the_default_ceiling():
    assert B._passes_long(_v(ev=11.0), "Nonexistent Sector")
    assert not B._passes_long(_v(ev=13.0), "Nonexistent Sector")


# ── the short gate ──────────────────────────────────────────────────────────

def test_rich_and_cash_poor_is_a_short():
    # Energy ceiling 8.0 -> needs >= 12.0, and FCF yield <= 2%.
    assert B._passes_short(_v(ev=20.0, fcf=0.01), "Energy")


def test_a_rich_multiple_on_strong_cash_flow_is_a_good_business_not_a_short():
    assert not B._passes_short(_v(ev=20.0, fcf=0.09), "Energy")


def test_merely_above_the_long_ceiling_is_not_rich_enough():
    # 10x clears the 8x energy ceiling but not the 1.5x multiple of it.
    assert not B._passes_short(_v(ev=10.0, fcf=0.01), "Energy")


def test_the_two_sides_never_both_fire_on_one_name():
    for ev in (1.0, 5.0, 8.0, 12.0, 20.0, 40.0):
        for fcf in (-0.02, 0.01, 0.05, 0.12):
            v = _v(ev=ev, fcf=fcf)
            assert not (B._passes_long(v, "Industrials") and B._passes_short(v, "Industrials"))


# ── the rare bird flag ──────────────────────────────────────────────────────

def test_rare_bird_needs_working_capital_well_above_the_market_price():
    # 100m working capital / 1m shares = $100/share against a $50 price.
    assert B._rare_bird(_v(wc=100_000_000), price=50.0, shares=1_000_000)


def test_an_ordinary_company_is_not_a_rare_bird():
    assert not B._rare_bird(_v(wc=10_000_000), price=50.0, shares=1_000_000)


@pytest.mark.parametrize("price,shares", [(None, 1_000), (50.0, None), (50.0, 0)])
def test_rare_bird_is_false_when_it_cannot_be_computed(price, shares):
    assert not B._rare_bird(_v(wc=100_000_000), price=price, shares=shares)
