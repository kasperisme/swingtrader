"""The scheduled pass: what goes live, what gets held, and how big the window is.

The publish gate is the part of this build that had no predecessor, and it is
the part a naive cron would have got wrong in a way nobody would notice: the
pipeline never set `published`, and the quote pages read `published = true`
only. Scheduled without a gate the job writes an unpublished row every week,
reports success, and the pages keep serving whatever was promoted by hand.

So the gate is tested harder than the plumbing around it. Two properties matter
and they fail in opposite directions:

  * a row that cannot render must never be promoted (a published ticker that
    displays nothing is indistinguishable from a bug), and
  * an unchanged re-run must NOT be promoted, because the judged tier is model
    output and re-running it on unchanged inputs produces new wording for the
    same content — which reads as fresh analysis to anyone watching the page.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from strategylab.social.batch import (MEDIAN_MOVE_PCT, PRICE_MOVE_PCT,
                                      STALE_DAYS, materiality, publish_gate,
                                      validity)
from strategylab.social.universe import (MIN_TARGETS, cooldown_for,
                                         priority_of, _needs_check)


def payload(**over) -> dict:
    """A valid payload; keyword args override one field at a time."""
    vote = {"n_targets": 12, "low": 95.0, "high": 163.0, "median": 128.0,
            "price": 122.0}
    dec = {"position": "The price sits below the median of 12 published models.",
           "crux": "Whether HEYDUDE's decline is cyclical or structural.",
           "pays_for": ["the Crocs brand growing mid-single digits"],
           "declines": ["any HEYDUDE stabilisation"],
           "drivers": [{"driver": "HEYDUDE stabilisation", "priced_in_pct": 25,
                        "value_if_true_pct": 31, "basis": "Baird at $163",
                        "testable": False}]}
    vote.update(over.pop("vote", {}))
    dec.update(over.pop("decomposition", {}))
    out = {"vote": vote, "decomposition": dec, "cases": []}
    out.update(over)
    return out


def live(**over) -> dict:
    row = {"id": 1, "as_of": date.today() - timedelta(days=3), "price": 122.0,
           "n_targets": 12, "target_median": 128.0}
    row.update(over)
    return row


# ---------------------------------------------------------------- validity --
def test_valid_payload_passes():
    ok, why = validity(payload())
    assert ok, why


@pytest.mark.parametrize("over, fragment", [
    ({"decomposition": None}, "no decomposition"),
    ({"vote": {"n_targets": MIN_TARGETS - 1}}, "below the"),
    ({"vote": {"median": None}}, "incomplete"),
    ({"vote": {"high": 95.0}}, "degenerate"),
    ({"vote": {"price": None}}, "no price"),
])
def test_invalid_payloads_are_named(over, fragment):
    if over.get("decomposition") is None and "decomposition" in over:
        p = payload()
        p["decomposition"] = None
    else:
        p = payload(**over)
    ok, why = validity(p)
    assert not ok
    assert fragment in why


def test_empty_drivers_is_invalid():
    """A row with no drivers renders an empty panel, which is worse than none."""
    ok, why = validity(payload(decomposition={"drivers": []}))
    assert not ok and "no drivers" in why


@pytest.mark.parametrize("field_", ["position", "crux"])
def test_missing_summary_part_is_invalid(field_):
    ok, why = validity(payload(decomposition={field_: "   "}))
    assert not ok and field_ in why


def test_invalid_never_publishes_however_material():
    """Validity is checked FIRST, so a big move cannot promote a broken row."""
    p = payload(vote={"n_targets": 2, "median": 300.0})
    go, why = publish_gate(p, live())
    assert not go
    assert why.startswith("invalid:")


# ------------------------------------------------------------- materiality --
def test_first_row_always_publishes():
    go, why = materiality(payload(), None)
    assert go and "first" in why


def test_unchanged_rerun_is_held():
    """The property the gate exists for: same inputs, same day, no republish."""
    go, why = materiality(payload(), live())
    assert not go
    assert "unchanged" in why


def test_new_analyst_model_publishes():
    go, why = materiality(payload(vote={"n_targets": 13}), live())
    assert go and "12 -> 13" in why


def test_median_move_at_threshold_publishes():
    med = 128.0 * (1 + MEDIAN_MOVE_PCT)
    go, _ = materiality(payload(vote={"median": med}), live())
    assert go


def test_median_move_below_threshold_is_held():
    med = 128.0 * (1 + MEDIAN_MOVE_PCT / 2)
    go, _ = materiality(payload(vote={"median": med}), live())
    assert not go


def test_price_move_at_threshold_publishes():
    px = 122.0 * (1 + PRICE_MOVE_PCT)
    go, why = materiality(payload(vote={"price": px}), live())
    assert go and "price" in why


def test_price_move_is_symmetric():
    """A crash is as material as a rally; the gate must not be directional."""
    up = 122.0 * (1 + PRICE_MOVE_PCT)
    down = 122.0 * (1 - PRICE_MOVE_PCT)
    assert materiality(payload(vote={"price": up}), live())[0]
    assert materiality(payload(vote={"price": down}), live())[0]


def test_stale_row_republishes_on_age_alone():
    old = live(as_of=date.today() - timedelta(days=STALE_DAYS))
    go, why = materiality(payload(), old)
    assert go and "old" in why


def test_row_one_day_short_of_stale_is_held():
    old = live(as_of=date.today() - timedelta(days=STALE_DAYS - 1))
    go, _ = materiality(payload(), old)
    assert not go


def test_missing_comparison_fields_do_not_force_a_republish():
    """A live row with nulls must not be read as "everything changed".

    The early rows in this table predate several columns. Treating a null as a
    difference would republish every one of them on the first scheduled pass —
    a mass of "new" analysis that is nothing of the sort.
    """
    go, why = materiality(payload(), live(price=None, target_median=None,
                                          n_targets=None))
    assert not go, why


# ------------------------------------------------------------ the universe --
def test_priority_is_coverage_first():
    """The failure this weighting exists to prevent: ordering on anything else.

    Mention counts span three orders of magnitude, so on raw values one heavily
    covered name would swamp every other consideration — hence the logs. A name
    the press writes about constantly must outrank one with a deep analyst bench
    that nobody covers, because the corpus is what the drivers are checked
    against.
    """
    heavily_covered = priority_of(mentions_180d=4000, n_targets=6)
    thinly_covered = priority_of(mentions_180d=25, n_targets=40)
    assert heavily_covered > thinly_covered


def test_priority_breaks_ties_on_analyst_coverage():
    assert priority_of(500, 30) > priority_of(500, 6)


def test_size_is_no_longer_an_input_to_the_queue():
    """Market cap left eligibility, so it must not come back in as an ordering.

    A queue drained a few dozen names a night puts a small company behind every
    large one; that is the floor it replaced, with extra steps. The only inputs
    are the two the analysis actually needs — who writes about it and who models
    it.
    """
    import inspect

    from strategylab.social.universe import MIN_MARKET_CAP, MIN_PRICE, priority_of as p

    assert "market_cap" not in inspect.signature(p).parameters
    assert not MIN_MARKET_CAP and not MIN_PRICE, (
        "the size floors are inert by default; a caller may still bound an "
        "exploratory pass by hand")


def test_priority_handles_missing_inputs():
    assert priority_of(None, None) >= 0.0
    # An unchecked name is ordered on its coverage alone, never on a guessed
    # target count.
    assert priority_of(500, None) == priority_of(500, 0)


def test_cooldown_backs_off_and_is_capped():
    seq = [cooldown_for(n) for n in range(1, 12)]
    assert seq == sorted(seq), "backoff must be monotonic"
    assert seq[0] == 1
    assert seq[-1] == seq[5] == 60, "and capped, not unbounded"


def test_unchecked_name_is_always_due():
    assert _needs_check(None, None, None, date.today())


def test_near_miss_rechecks_sooner_than_a_hopeless_name():
    """Two targets short is worth revisiting; zero coverage is not.

    Without this split the FMP budget is spent re-asking about names that have
    never had a single published target, which is most of what fails the gate.
    """
    from strategylab.social.universe import (NEAR_MISS_RECHECK_DAYS,
                                             RECHECK_DAYS)
    from datetime import datetime, timezone

    when = datetime.now(timezone.utc) - timedelta(days=NEAR_MISS_RECHECK_DAYS)
    today = date.today()
    assert _needs_check(when, False, MIN_TARGETS - 1, today)
    assert not _needs_check(when, False, 0, today)
    assert NEAR_MISS_RECHECK_DAYS < RECHECK_DAYS


def test_eligible_name_is_rechecked_on_the_slow_cycle():
    from strategylab.social.universe import RECHECK_DAYS
    from datetime import datetime, timezone

    fresh = datetime.now(timezone.utc) - timedelta(days=RECHECK_DAYS - 1)
    stale = datetime.now(timezone.utc) - timedelta(days=RECHECK_DAYS)
    assert not _needs_check(fresh, True, 12, date.today())
    assert _needs_check(stale, True, 12, date.today())


def test_coverage_floor_admits_the_development_set():
    """The floor must not exclude the names the pipeline was built on.

    It did, at first. CROX has 19 mentions over 180 days and every stage of
    this pipeline was debugged against it, but the initial floor of 20 put it
    outside the universe — so the scheduled job would never have re-run the one
    reconstruction there is a written worked example of. A floor calibrated
    above its own development set is measuring the wrong thing.
    """
    from strategylab.social.universe import (DEVELOPMENT_SET_MIN_MENTIONS,
                                             MIN_MENTIONS_180D)
    assert MIN_MENTIONS_180D < DEVELOPMENT_SET_MIN_MENTIONS, (
        "the coverage floor must sit below the sparsest known-good name, with "
        "headroom for a ticker whose coverage dips between passes")


# ------------------------------------------------------------- the backend --
def test_backend_resolution_is_explicit(monkeypatch):
    """The scheduled pass must get the backend it asked for, not a guess.

    Auto-detection exists for interactive use. A cron job that silently fell
    back to Anthropic because a daemon was down would produce the right rows at
    the wrong price, which is the failure that would not be noticed until the
    bill arrived.
    """
    from strategylab.social.llm import resolve

    monkeypatch.setenv("STRATEGYLAB_LLM_BACKEND", "ollama")
    monkeypatch.setenv("STRATEGYLAB_OLLAMA_MODELS", "glm-5.1:cloud")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-present")
    assert resolve() == ("ollama", ["glm-5.1:cloud"])

    monkeypatch.setenv("STRATEGYLAB_LLM_BACKEND", "anthropic")
    backend, chain = resolve()
    assert backend == "anthropic" and chain and chain[0].startswith("claude")


def test_ollama_backend_ignores_a_leaked_claude_default(monkeypatch):
    """`model=` defaults to LabConfig's Claude name all over the pipeline.

    Callers pass it through without meaning to pick a model, so honouring it
    would send the batch to Anthropic on a backend that was explicitly set to
    Ollama.
    """
    from strategylab.social.llm import resolve

    monkeypatch.setenv("STRATEGYLAB_LLM_BACKEND", "ollama")
    monkeypatch.setenv("STRATEGYLAB_OLLAMA_MODELS", "glm-5.1:cloud")
    assert resolve("claude-opus-5") == ("ollama", ["glm-5.1:cloud"])
    assert resolve("gpt-oss:120b-cloud") == ("ollama", ["gpt-oss:120b-cloud"])


def test_unknown_backend_is_refused(monkeypatch):
    from strategylab.social.llm import resolve

    monkeypatch.setenv("STRATEGYLAB_LLM_BACKEND", "openai")
    with pytest.raises(ValueError, match="unknown"):
        resolve()


def test_context_window_covers_the_reply_not_just_the_prompt():
    """`num_ctx` covers both halves.

    Sizing on the prompt alone buys a window that fits the question and then
    truncates it to make room for the answer — and Ollama truncates the FRONT,
    which for these prompts is the analyst position the case is about.
    """
    from strategylab.social.llm import CHARS_PER_TOKEN, _num_ctx

    chars, reply = 60_000, 12_000
    ctx = _num_ctx(chars, reply)
    assert ctx >= chars / CHARS_PER_TOKEN + reply


def test_context_window_is_capped():
    from strategylab.social.llm import CTX_CEILING, _num_ctx

    assert _num_ctx(10_000_000, 12_000) == CTX_CEILING
