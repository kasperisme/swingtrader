"""The squeeze screen's thresholds, and the structured short thesis.

``crowding.evaluate`` is pure, so every threshold is tested without FMP or the
database. The screen FAILS CLOSED: data it cannot fetch is a refusal.
"""

from __future__ import annotations

from datetime import date

from services.arena import crowding
from services.arena.tools import AccountTools, _place_order_schema
from services.arena.types import PortfolioSnapshot

OK_FLOAT = {"float_shares": 500_000_000, "free_float_pct": 95.0}
OK_ATTN = {"mentions_recent": 4, "acceleration": 1.1, "sentiment": 0.05}
OK_STATS = {"close": 50.0, "runup_20d_pct": 3.0, "avg_dollar_volume": 200_000_000}


def reasons(**over):
    args = {"float_data": OK_FLOAT, "attention": OK_ATTN, "stats": OK_STATS, **over}
    return crowding.evaluate(**args)


def test_a_large_liquid_quiet_name_passes():
    assert reasons() == []


def test_a_small_float_value_disqualifies():
    # 10M shares x $50 = $0.5B, under the $1B floor.
    out = reasons(float_data={"float_shares": 10_000_000, "free_float_pct": 95.0})
    assert any("small enough to squeeze" in r for r in out)


def test_a_tight_free_float_disqualifies():
    out = reasons(float_data={"float_shares": 500_000_000, "free_float_pct": 30.0})
    assert any("tight float" in r for r in out)


def test_thin_liquidity_disqualifies():
    out = reasons(stats={**OK_STATS, "avg_dollar_volume": 5_000_000})
    assert any("too thin to cover" in r for r in out)


def test_a_run_up_in_progress_disqualifies():
    out = reasons(stats={**OK_STATS, "runup_20d_pct": 40.0})
    assert any("squeeze in progress" in r for r in out)


def test_accelerating_bullish_coverage_disqualifies():
    out = reasons(attention={"mentions_recent": 30, "acceleration": 4.0, "sentiment": 0.4})
    assert any("retail crowding" in r for r in out)


def test_accelerating_NEGATIVE_coverage_is_not_a_long_side_crowd():
    # An investigation getting louder is not retail enthusiasm.
    assert reasons(attention={"mentions_recent": 30, "acceleration": 4.0, "sentiment": -0.4}) == []


def test_missing_data_fails_closed():
    assert any("float could not be verified" in r for r in reasons(float_data=None))
    assert any("attention could not be measured" in r for r in reasons(attention=None))
    assert any("no recent price/volume" in r for r in reasons(stats=None))


# ── the structured short thesis ─────────────────────────────────────────────


class _Broker:
    prices = None

    def __init__(self):
        self.submitted = []

    def submit(self, agent, intent, **kw):
        self.submitted.append((intent, kw))
        return {"status": "pending"}


def _account(required=True):
    return AccountTools(
        {"id": "a", "allow_shorts": True},
        broker=_Broker(),
        portfolio=PortfolioSnapshot(agent_id="a", slug="a", cash=100_000.0),
        decision_id=None,
        intended_for=date(2026, 9, 14),
        reference_prices={"AAA": 50.0},
        as_of=date(2026, 9, 11),
        short_thesis_required=required,
    )


FULL = dict(
    defect="CFO negative four quarters while net income positive",
    evidence="cashflow-statement Q1-Q2 2026",
    catalyst="Q3 print",
    falsified_by="Q3 10-Q shows positive CFO",
    falsify_by_date="2026-11-05",
)


def test_a_short_without_the_four_parts_is_refused_before_the_broker():
    acct = _account()
    out = acct.place_order(ticker="AAA", side="sell", quantity=10, thesis="looks weak")
    assert out["ok"] is False and "missing" in out["error"]
    assert acct.broker.submitted == []


def test_a_falsifier_in_the_past_is_refused():
    acct = _account()
    out = acct.place_order(ticker="AAA", side="sell", quantity=10,
                           **{**FULL, "falsify_by_date": "2026-09-01"})
    assert out["ok"] is False and "not in the future" in out["error"]


def test_a_complete_short_thesis_is_written_onto_the_order():
    acct = _account()
    acct.place_order(ticker="AAA", side="sell", quantity=10, **FULL)
    intent, _ = acct.broker.submitted[0]
    assert intent.thesis.startswith("DEFECT: CFO negative")
    assert "FALSIFIED BY: Q3 10-Q shows positive CFO (by 2026-11-05)" in intent.thesis


def test_a_long_needs_no_short_thesis():
    acct = _account()
    acct.place_order(ticker="AAA", side="buy", quantity=10, thesis="a long")
    assert len(acct.broker.submitted) == 1


def test_only_the_requiring_agent_sees_the_extra_fields():
    assert "defect" in _place_order_schema(True)["function"]["parameters"]["properties"]
    assert "defect" not in _place_order_schema(False)["function"]["parameters"]["properties"]
