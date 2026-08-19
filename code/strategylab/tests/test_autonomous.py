"""The autonomous layer.

The stopping rules carry most of the weight here. An unsupervised search with
no stopping rule does not converge on truth — it converges on whatever the
sample rewards, and this project measured the cost directly: PBO rose from
0.255 at 41 configurations to 0.590 at 110, meaning selection had stopped
carrying information while the machine happily kept selecting.
"""

import json
import time

import pytest

from strategylab.autonomous.budget import (CampaignState, DailyBudget, SearchBudget,
                                           StopReason, should_stop)
from strategylab.autonomous.llm import extract_json, validate

SCHEMA = {
    "type": "object",
    "properties": {"reasoning_summary": {"type": "string"},
                   "proposals": {"type": "array"}},
    "required": ["reasoning_summary", "proposals"],
}


# ------------------------------------------------------------------ JSON ---
def test_extract_json_handles_the_shapes_models_actually_emit():
    obj = {"reasoning_summary": "x", "proposals": []}
    assert extract_json(json.dumps(obj)) == obj
    assert extract_json("```json\n" + json.dumps(obj) + "\n```") == obj
    assert extract_json("Here you go:\n" + json.dumps(obj)) == obj
    assert extract_json(json.dumps(obj) + "\n\nHope that helps!") == obj


def test_extract_json_refuses_to_invent_structure():
    assert extract_json("") is None
    assert extract_json("no json at all") is None
    assert extract_json("[1, 2, 3]") is None          # array is not the contract
    assert extract_json('{"broken": ') is None


def test_extract_json_survives_braces_inside_strings():
    obj = {"reasoning_summary": "use {this} carefully", "proposals": []}
    assert extract_json(json.dumps(obj)) == obj


def test_validate_catches_the_failures_that_actually_happen():
    ok, _ = validate({"reasoning_summary": "a", "proposals": []}, SCHEMA)
    assert ok
    ok, why = validate({"proposals": []}, SCHEMA)
    assert not ok and "reasoning_summary" in why
    ok, why = validate({"reasoning_summary": "a", "proposals": {}}, SCHEMA)
    assert not ok and "array" in why
    ok, why = validate([1, 2], SCHEMA)
    assert not ok


# -------------------------------------------------------------- stopping ---
def _state(iters, best, best_at, hours=0.0):
    s = CampaignState(started=time.time() - hours * 3600)
    s.iterations, s.best_reward, s.best_at_iteration = iters, best, best_at
    return s


def test_never_stops_before_the_seed_has_been_probed():
    stop, _r, _w = should_stop(_state(2, 0.1, 0), SearchBudget(), n_trials=999,
                               pbo=0.99, proposals_available=0)
    assert not stop, "stopped before the minimum number of iterations"


def test_stops_on_plateau():
    b = SearchBudget(patience=6)
    stop, reason, why = should_stop(_state(20, 0.12, 10), b, n_trials=50)
    assert stop and reason is StopReason.PLATEAU
    assert "without improvement" in why


def test_stops_when_pbo_says_selection_stopped_informing():
    """The measured failure mode: PBO 0.255 -> 0.590 between 41 and 110 trials."""
    b = SearchBudget(max_pbo=0.45, pbo_check_after=40)
    ok, _r, _w = should_stop(_state(10, 0.5, 9), b, n_trials=41, pbo=0.26)
    assert not ok, "stopped while selection was still informative"
    stop, reason, why = should_stop(_state(10, 0.5, 9), b, n_trials=110, pbo=0.59)
    assert stop and reason is StopReason.PBO_DEGRADED
    assert "fitting noise" in why


def test_pbo_is_ignored_before_it_has_a_population():
    b = SearchBudget(pbo_check_after=40, max_pbo=0.45)
    stop, _r, _w = should_stop(_state(5, 0.5, 4), b, n_trials=12, pbo=0.95)
    assert not stop, "acted on a PBO estimated from too few configurations"


def test_stops_when_the_gate_is_cleared_rather_than_continuing():
    """Continuing after success actively lowers the deflated Sharpe of the
    result already in hand — every extra trial raises the best-of-N bar."""
    stop, reason, why = should_stop(_state(9, 1.4, 9), SearchBudget(), n_trials=30,
                                    gate_cleared=True)
    assert stop and reason is StopReason.GATE_CLEARED
    assert "deflated Sharpe" in why


def test_stops_when_proposals_are_exhausted():
    stop, reason, _w = should_stop(_state(9, 0.5, 9), SearchBudget(), n_trials=30,
                                   proposals_available=0)
    assert stop and reason is StopReason.PROPOSALS_EXHAUSTED


def test_hard_trial_budget_binds_even_while_improving():
    b = SearchBudget(hard_trial_budget=100)
    stop, reason, _w = should_stop(_state(30, 2.0, 30), b, n_trials=100)
    assert stop and reason is StopReason.TRIAL_BUDGET


def test_wall_clock_binds():
    b = SearchBudget(max_wall_clock_hours=2.0)
    stop, reason, _w = should_stop(_state(20, 0.5, 20), b, n_trials=10, pbo=0.1)
    assert not stop
    stop, reason, _w = should_stop(_state(20, 0.5, 20, hours=3.0), b, n_trials=10)
    assert stop and reason is StopReason.WALL_CLOCK


def test_tiny_improvements_do_not_reset_the_patience_clock_forever():
    """A search inching up by 0.001 an iteration is sampling noise, not making
    progress. If that resets patience, the campaign never ends."""
    b = SearchBudget(patience=5, min_improvement=0.02)
    s = CampaignState()
    stop = False
    for i in range(1, 30):
        s.observe(i, 0.5 + i * 0.0005, min_improvement=b.min_improvement)
        stop, _r, _w = should_stop(s, b, n_trials=20)
        if stop:
            break
    assert stop, "a noise-level drift kept the campaign alive indefinitely"
    assert i < 20, f"took {i} iterations to notice it was not improving"


def test_a_real_improvement_does_extend_the_campaign():
    b = SearchBudget(patience=5)
    s = CampaignState()
    for i in range(1, 10):
        s.observe(i, 0.5 + i * 0.1, min_improvement=b.min_improvement)
    stop, _r, _w = should_stop(s, b, n_trials=20)
    assert not stop, "stopped a campaign that was still improving"


# ------------------------------------------------------------ daily caps ---
def test_daily_budget_blocks_and_rolls():
    d = DailyBudget(max_campaigns_per_day=2)
    assert d.can_start_campaign()[0]
    d.campaigns = 2
    ok, why = d.can_start_campaign()
    assert not ok and "campaign limit" in why
    d.day_started = time.time() - 86500
    assert d.roll_if_needed()
    assert d.can_start_campaign()[0], "budget did not roll over after a day"
