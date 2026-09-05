"""The roster's prompt/limit invariants.

The arena's claim is that agents differ ONLY in the data they can see. That
holds only if the mechanics reach every prompt identically and truthfully — an
agent told it may do something the broker rejects burns rounds arguing with the
broker, and one never told about a capability it has simply never uses it. Both
happened: the broker has supported shorting since the beginning and no prompt
mentioned it, so six of seven LLM agents ran long-only by ignorance.
"""

from services.arena.roster import ROSTER
from services.arena.types import AgentSpec, _SHORTING_ALLOWED, _SHORTING_FORBIDDEN


def _spec(**kw) -> AgentSpec:
    base = dict(slug="t", name="T", tagline="t", approach="a", system_prompt="PERSONA")
    return AgentSpec(**{**base, **kw})


# ── the derivation ──────────────────────────────────────────────────────────

def test_a_short_enabled_agent_is_told_it_may_short():
    spec = _spec(allow_shorts=True)
    assert _SHORTING_ALLOWED in spec.system_prompt
    assert _SHORTING_FORBIDDEN not in spec.system_prompt


def test_a_long_only_agent_is_told_it_may_not():
    spec = _spec(allow_shorts=False)
    assert _SHORTING_FORBIDDEN in spec.system_prompt
    assert _SHORTING_ALLOWED not in spec.system_prompt


def test_the_persona_survives_the_append():
    assert _spec(allow_shorts=True).system_prompt.startswith("PERSONA")


def test_a_deterministic_control_gets_no_shorting_text():
    spec = _spec(engine="deterministic", system_prompt="")
    assert spec.system_prompt == ""


def test_an_llm_agent_with_no_prompt_is_left_alone():
    assert _spec(system_prompt="").system_prompt == ""


# ── the roster itself ───────────────────────────────────────────────────────

def test_every_llm_agent_may_short_and_knows_it():
    for spec in ROSTER:
        if spec.engine != "llm":
            continue
        assert spec.allow_shorts, f"{spec.slug} cannot short"
        assert "You may go SHORT" in spec.system_prompt, f"{spec.slug} was not told"


def test_the_deterministic_controls_stay_long_only():
    # They have no prompt to read and their behaviour IS the benchmark; giving
    # them shorts would change what the leaderboard is measured against.
    controls = [s for s in ROSTER if s.engine != "llm"]
    assert {s.slug for s in controls} == {"jack-boggle", "burton-malarkey"}
    assert not any(s.allow_shorts for s in controls)


def test_no_prompt_contradicts_its_own_flag():
    for spec in ROSTER:
        if not spec.system_prompt:
            continue
        says_may = "You may go SHORT" in spec.system_prompt
        says_not = "You are LONG ONLY" in spec.system_prompt
        assert says_may != says_not, f"{spec.slug} says both or neither"
        assert says_may == spec.allow_shorts, f"{spec.slug} prompt contradicts flag"


def test_every_llm_agent_has_a_prompt_and_tools():
    for spec in ROSTER:
        if spec.engine != "llm":
            continue
        assert spec.system_prompt.strip(), f"{spec.slug} has no prompt"
        assert spec.tools, f"{spec.slug} has no tools"
