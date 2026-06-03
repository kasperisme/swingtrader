"""Tests for the NIS Momentum screen's gating logic."""

from services.market_screenings.scripts.nis_momentum import _passed_full_gates


_BASE = {"Passed": True, "PASSED_FUNDAMENTALS": True, "PriceOverSMA50": True}


def test_passes_when_all_gates_true():
    assert _passed_full_gates(_BASE) is True


def test_dropped_when_price_below_sma50():
    """A name that has pulled back below its 50-day MA is removed, even if it
    still clears the shared trend-template Passed + fundamentals gates."""
    assert _passed_full_gates({**_BASE, "PriceOverSMA50": False}) is False


def test_price_over_sma50_is_required():
    # missing the key is treated conservatively as not-passing
    tt = {"Passed": True, "PASSED_FUNDAMENTALS": True}
    assert _passed_full_gates(tt) is False


def test_still_requires_the_other_gates():
    assert _passed_full_gates({**_BASE, "Passed": False}) is False
    assert _passed_full_gates({**_BASE, "PASSED_FUNDAMENTALS": False}) is False
