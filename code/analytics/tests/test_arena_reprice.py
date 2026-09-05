"""The priced-in surfaces, re-anchored to the session being traded.

Every ``research_priced_in`` row is ``generation_is_pit = false``, so a replay
reads a reconstruction generated later and takes its ``price`` at face value.
Michael Beary bought CEG on 2026-07-02 believing it cost $285.05; it cost
$238.10. These tests pin the correction to that real trade — the numbers in
``test_repricing_the_ceg_trade_that_exposed_this`` are the arena's own record.
"""

import pytest

from services.arena.tools import PRICED_IN_TOOLS, _RepriceToSession


def _record(ticker="CEG", price=285.05, median=362.0, gap=-0.212569):
    """The shape ``get_priced_in`` returns: a price and a vote block."""
    return {
        "ticker": ticker,
        "price": price,
        "vote": {"target_low": 296, "target_median": median, "target_high": 380,
                 "median_gap": gap, "n_targets": 13},
        "drivers": [],
    }


def _driver_row(ticker="CEG", price=285.05):
    """The flatter shape the driver/case/search tools return."""
    return {"ticker": ticker, "price": price, "priced_in_pct": 10, "driver": "PPA upside"}


def _wrap(payload, prices):
    return _RepriceToSession(lambda **kw: payload, lambda t: prices.get(t))


# ── the correction ──────────────────────────────────────────────────────────

def test_repricing_the_ceg_trade_that_exposed_this():
    out = _wrap([_record()], {"CEG": 238.10})()[0]

    assert out["price"] == 238.10
    assert out["reconstruction_price"] == 285.05
    # -34.2% against the $362 median, not the -21.3% the stale price implied.
    assert out["vote"]["median_gap"] == pytest.approx(-0.342265, abs=1e-5)
    assert out["vote"]["median_gap_reconstruction"] == pytest.approx(-0.212569)


def test_the_original_price_is_kept_not_overwritten_away():
    out = _wrap([_record()], {"CEG": 238.10})()[0]
    assert out["reconstruction_price"] == 285.05
    assert "reconstruction was built against" in out["price_note"]


def test_flat_driver_rows_are_repriced_too():
    out = _wrap([_driver_row()], {"CEG": 238.10})()[0]
    assert out["price"] == 238.10
    assert out["reconstruction_price"] == 285.05


def test_a_dict_payload_is_handled_as_well_as_a_list():
    out = _wrap(_driver_row(), {"CEG": 238.10})()
    assert out["price"] == 238.10


def test_every_row_in_a_multi_ticker_result_is_repriced():
    payload = [_record("CEG"), _record("GEV", price=926.73, median=1217.5)]
    out = _wrap(payload, {"CEG": 238.10, "GEV": 1070.00})()
    assert [r["price"] for r in out] == [238.10, 1070.00]


# ── the failure modes ───────────────────────────────────────────────────────

def test_a_missing_price_says_so_rather_than_silently_passing_a_stale_one():
    out = _wrap([_record()], {})()[0]
    assert out["price"] == 285.05                    # unchanged
    assert "reconstruction_price" not in out
    assert "may be stale" in out["price_note"]


def test_a_zero_price_is_treated_as_no_price():
    out = _wrap([_record()], {"CEG": 0.0})()[0]
    assert out["price"] == 285.05
    assert "may be stale" in out["price_note"]


def test_a_lookup_that_raises_leaves_the_row_alone():
    def boom(_):
        raise RuntimeError("no price book")

    out = _RepriceToSession(lambda **kw: [_record()], boom)()[0]
    assert out["price"] == 285.05


def test_a_row_without_a_price_field_is_left_alone():
    out = _wrap([{"ticker": "CEG", "drivers": []}], {"CEG": 238.10})()[0]
    assert "price" not in out
    assert "reconstruction_price" not in out


def test_gap_is_not_recomputed_without_a_target_median():
    payload = [_record(median=None)]
    out = _wrap(payload, {"CEG": 238.10})()[0]
    assert out["price"] == 238.10                    # price still corrected
    assert "median_gap_reconstruction" not in out["vote"]


def test_kwargs_reach_the_wrapped_tool_unchanged():
    seen = {}

    def fn(**kw):
        seen.update(kw)
        return [_record()]

    _RepriceToSession(fn, lambda t: 238.10)(tickers="CEG", max_priced_in_pct=25)
    assert seen == {"tickers": "CEG", "max_priced_in_pct": 25}


def test_all_four_priced_in_surfaces_are_covered():
    assert set(PRICED_IN_TOOLS) == {
        "get_priced_in",
        "get_priced_in_drivers",
        "get_priced_in_case",
        "search_priced_in_drivers",
    }
