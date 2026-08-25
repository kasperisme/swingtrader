"""The forward-prediction ledger's guarantees.

Tiers 1 and 2 failed retrospectively — the measurement was designed after the
data existed, so every degree of freedom in it could be turned until something
appeared. Tier 3 removes that by fixing the claim first, which means the
properties worth pinning are about the RECORD, not the statistics.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from strategylab.social.predict import (FALSE, TRUE, UNRESOLVED, Prediction,
                                        PredictionLedger, score)


def _pred(**kw) -> Prediction:
    base = dict(ticker="TEST", driver="a driver", priced_in_pct=25.0,
                p_resolves=0.6, move_if_true=0.10, move_if_false=-0.02,
                resolver="earnings_beat",
                spec={"after": "2026-01-01", "expect_beat": True},
                resolve_on=(date.today() + timedelta(days=30)).isoformat(),
                made_on=date.today().isoformat(), price_at_prediction=100.0)
    base.update(kw)
    return Prediction(**base)


# ----------------------------------------------------------------------
# The lock. Nothing else matters if this fails.
# ----------------------------------------------------------------------
def test_sealed_prediction_verifies():
    assert _pred().seal().verify()


@pytest.mark.parametrize("field,value", [
    ("p_resolves", 0.95), ("move_if_true", 0.99), ("priced_in_pct", 90.0),
    ("driver", "a different driver"), ("resolve_on", "2099-01-01"),
])
def test_editing_a_sealed_prediction_breaks_its_lock(field, value):
    """The failure this tier exists to make impossible: quietly improving a
    forecast after the outcome is known."""
    p = _pred().seal()
    setattr(p, field, value)
    assert not p.verify()


def test_tampering_is_detected_in_the_ledger(tmp_path):
    led = PredictionLedger(tmp_path / "p.db")
    lock = led.register(_pred())
    assert led.tampered() == []
    led.db.execute("UPDATE predictions SET p_resolves=0.99 WHERE lock=?", (lock,))
    led.db.commit()
    assert led.tampered() == [lock]


# ----------------------------------------------------------------------
# Registrability. A prediction that cannot be resolved by machine is not a test.
# ----------------------------------------------------------------------
def test_unknown_resolver_is_refused(tmp_path):
    led = PredictionLedger(tmp_path / "p.db")
    with pytest.raises(ValueError, match="unknown resolver"):
        led.register(_pred(resolver="markdown_depth_on_the_dtc_site"))


def test_incomplete_spec_is_refused_at_registration(tmp_path):
    """Fail when it is written, not months later when it comes due."""
    led = PredictionLedger(tmp_path / "p.db")
    with pytest.raises(ValueError, match="spec keys"):
        led.register(_pred(resolver="segment_growth", spec={"segment": "X"}))


def test_resolution_date_must_be_in_the_future(tmp_path):
    led = PredictionLedger(tmp_path / "p.db")
    with pytest.raises(ValueError, match="future"):
        led.register(_pred(resolve_on=date.today().isoformat()))


# ----------------------------------------------------------------------
# Resolution is once and only once.
# ----------------------------------------------------------------------
def test_a_resolved_prediction_is_never_re_resolved(tmp_path):
    """Re-running a resolver until it agrees is the retrospective failure mode
    in a new costume."""
    led = PredictionLedger(tmp_path / "p.db")
    lock = led.register(_pred())
    led.record_outcome(lock, FALSE, {"note": "first"}, price_now=90.0)
    led.record_outcome(lock, TRUE, {"note": "second"}, price_now=130.0)
    row = led.resolved()[0]
    assert row["outcome"] == FALSE
    assert row["price_at_resolution"] == 90.0


def test_unresolved_is_not_scored_as_a_miss(tmp_path):
    led = PredictionLedger(tmp_path / "p.db")
    for i in range(10):
        led.register(_pred(driver=f"d{i}", p_resolves=0.5 + i / 100))
    for i, p in enumerate(led.due(date.today() + timedelta(days=60))):
        led.record_outcome(p.lock, UNRESOLVED if i < 4 else TRUE, {}, 110.0)
    s = score(led)
    assert s["n_resolved"] == 6
    assert led.summary()["unresolved"] == 4


# ----------------------------------------------------------------------
# Scoring is against a base rate, and refuses to conclude while underpowered.
# ----------------------------------------------------------------------
def test_score_reports_underpowered_until_the_stated_threshold(tmp_path):
    led = PredictionLedger(tmp_path / "p.db")
    for i in range(12):
        led.register(_pred(driver=f"d{i}"))
    for p in led.due(date.today() + timedelta(days=60)):
        led.record_outcome(p.lock, TRUE, {}, 110.0)
    s = score(led)
    assert s["powered"] is False
    assert "UNDERPOWERED" in s["verdict"]


def test_a_forecast_no_better_than_the_base_rate_does_not_beat_it(tmp_path):
    """75% 'beat' calls on a 75% base rate is not skill."""
    led = PredictionLedger(tmp_path / "p.db")
    for i in range(20):
        led.register(_pred(driver=f"d{i}", p_resolves=0.75))
    for i, p in enumerate(led.due(date.today() + timedelta(days=60))):
        led.record_outcome(p.lock, TRUE if i < 15 else FALSE, {}, 110.0)
    s = score(led)
    assert s["base_rate"] == pytest.approx(0.75)
    assert not s["beats_base_rate"]


def test_score_says_nothing_on_a_near_empty_ledger(tmp_path):
    led = PredictionLedger(tmp_path / "p.db")
    led.register(_pred())
    assert "note" in score(led)
