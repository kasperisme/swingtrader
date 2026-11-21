"""Offline tests for the narrative stress-test arithmetic."""

from datetime import date

import pytest

from services.drawdown.narrative import (breakeven_cut, consensus_cagr, dcf_value, faded_cagr,
                                         required_now, solve_growth)


def test_solve_inverts_dcf():
    ev = dcf_value(100.0, 0.2, 0.08, 0.09, 0.025)
    assert solve_growth(ev, 100.0, 0.2, 0.09, 0.025) == pytest.approx(0.08, abs=1e-6)
    assert solve_growth(ev, 100.0, -0.1, 0.09, 0.025) is None


def test_fade_is_flat_at_terminal_and_between_otherwise():
    assert faded_cagr(0.025, 0.025) == pytest.approx(0.025)
    g = faded_cagr(0.20, 0.025)
    assert 0.025 < g < 0.20


def test_breakeven_cut_zero_when_supported_equals_required():
    req = faded_cagr(0.15, 0.025)
    assert breakeven_cut(0.15, 0.025, req) == pytest.approx(0.0, abs=1e-6)
    assert breakeven_cut(0.15, 0.025, req - 0.02) > 0
    assert breakeven_cut(0.15, 0.025, req + 0.02) < 0


def test_lower_price_needs_less_growth():
    p = {"implied_revenue_cagr": 0.12, "fcf_margin": 0.25, "discount_rate": 0.09, "terminal_growth": 0.025, "price": 100.0}
    same, _ = required_now(p, 100.0, 1e9, 2e8)
    lower, _ = required_now(p, 70.0, 0.7e9, 2e8)
    assert same == pytest.approx(0.12, abs=1e-6)
    assert lower < 0.12


def test_consensus_uses_last_reported_to_farthest_of_three():
    rows = [{"fiscal_date": f"{y}-12-31", "revenue_avg": 100 * 1.1 ** (y - 2025)} for y in range(2025, 2031)]
    g, n = consensus_cagr(rows, date(2026, 11, 21))
    assert n == 3 and g == pytest.approx(0.10, abs=1e-6)
