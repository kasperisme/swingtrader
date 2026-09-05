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


# ── repricing a past run ────────────────────────────────────────────────────
# The fundamentals cannot be rewound (FMP serves current TTM), but the PRICE
# half of a multiple can, and it is the half that moves daily. Without this a
# backfilled July run would judge every name on its September price.

def test_a_halved_price_halves_the_equity_not_the_debt():
    # EV 1000 = 800 equity + 200 net debt (2.0x on 100 EBITDA).
    v = {"enterprise_value": 1000.0, "ev_to_ebitda": 10.0,
         "net_debt_to_ebitda": 2.0, "fcf_yield": 0.08, "earnings_yield": 0.05}
    out = B._reprice_value(v, 0.5)
    assert out["enterprise_value"] == pytest.approx(600.0)     # 400 + 200
    assert out["ev_to_ebitda"] == pytest.approx(6.0)


def test_yields_scale_inversely_with_price():
    v = {"enterprise_value": 1000.0, "ev_to_ebitda": 10.0,
         "net_debt_to_ebitda": 2.0, "fcf_yield": 0.08, "earnings_yield": 0.05}
    out = B._reprice_value(v, 0.5)
    assert out["fcf_yield"] == pytest.approx(0.16)
    assert out["earnings_yield"] == pytest.approx(0.10)


def test_leverage_is_price_independent():
    v = {"enterprise_value": 1000.0, "ev_to_ebitda": 10.0,
         "net_debt_to_ebitda": 2.0, "fcf_yield": 0.08}
    assert B._reprice_value(v, 3.0)["net_debt_to_ebitda"] == 2.0


def test_a_ratio_of_one_changes_nothing_material():
    v = {"enterprise_value": 1000.0, "ev_to_ebitda": 10.0,
         "net_debt_to_ebitda": 2.0, "fcf_yield": 0.08}
    out = B._reprice_value(v, 1.0)
    assert out["ev_to_ebitda"] == pytest.approx(10.0)
    assert out["fcf_yield"] == pytest.approx(0.08)


@pytest.mark.parametrize("ratio", [None, 0, -1.0])
def test_no_usable_ratio_leaves_the_read_untouched(ratio):
    # No bar that day must not silently pass today's multiple off as history —
    # the row comes back unrepriced and without the marker.
    v = {"enterprise_value": 1000.0, "ev_to_ebitda": 10.0,
         "net_debt_to_ebitda": 2.0, "fcf_yield": 0.08}
    out = B._reprice_value(v, ratio)
    assert out == v
    assert "price_ratio_applied" not in out


def test_repricing_is_recorded_on_the_row():
    v = {"enterprise_value": 1000.0, "ev_to_ebitda": 10.0,
         "net_debt_to_ebitda": 2.0, "fcf_yield": 0.08}
    assert B._reprice_value(v, 0.75)["price_ratio_applied"] == 0.75
