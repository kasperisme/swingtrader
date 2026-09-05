"""The roster's prompt/limit invariants.

The arena's claim is that agents differ ONLY in the data they can see. That
holds only if the mechanics reach every prompt identically and truthfully — an
agent told it may do something the broker rejects burns rounds arguing with the
broker, and one never told about a capability it has simply never uses it. Both
happened: the broker has supported shorting since the beginning and no prompt
mentioned it, so six of seven LLM agents ran long-only by ignorance.
"""

from services.arena.roster import ROSTER
from services.arena.prompt import _SHORTING_ALLOWED, _SHORTING_FORBIDDEN
from services.arena.types import AgentSpec


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


# ── who the agent is modelled on ────────────────────────────────────────────
# The persona describes a method; the inspiration names the person. Naming them
# buys what a description cannot — the model already knows how these people
# behaved in situations no prompt anticipates. The framing is what stops that
# becoming a costume: act as they would with ONLY this data.

from services.arena.prompt import assemble


def test_the_inspiration_reaches_the_prompt():
    spec = _spec(inspiration="Michael Burry — contrarian.")
    assert "## Who you are modelled on" in spec.system_prompt
    assert "Michael Burry — contrarian." in spec.system_prompt


def test_no_inspiration_means_no_section():
    assert "## Who you are modelled on" not in _spec(inspiration="").system_prompt


def test_discipline_rules_are_rendered_as_a_list():
    spec = _spec(inspiration="X.", discipline=("Hold through drawdown.", "Concentrate."))
    assert "- Hold through drawdown." in spec.system_prompt
    assert "- Concentrate." in spec.system_prompt


def test_discipline_needs_an_inspiration_to_hang_from():
    # Rules with nobody attached would read as free-floating orders.
    assert "Hold through" not in _spec(inspiration="", discipline=("Hold through it.",)).system_prompt


def _flat(text: str) -> str:
    """Prompt prose is hard-wrapped, so assert on content, not on line breaks."""
    return " ".join(text.split())


def test_the_data_slice_constraint_is_stated():
    # Without this the naming turns the experiment into celebrity imitation.
    p = _flat(_spec(inspiration="Michael Burry — contrarian.").system_prompt)
    assert "ONLY the data in front of you" in p
    assert "borrowing their sources is cheating" in p


def test_every_llm_agent_names_someone_and_lists_their_discipline():
    for spec in ROSTER:
        if spec.engine != "llm":
            continue
        assert spec.inspiration.strip(), f"{spec.slug} has no inspiration"
        assert spec.discipline, f"{spec.slug} has no discipline rules"
        assert spec.inspiration.split("—")[0].strip() in spec.system_prompt, spec.slug
        for rule in spec.discipline:
            assert rule in spec.system_prompt, f"{spec.slug}: {rule[:40]}"


# ── assembly order ──────────────────────────────────────────────────────────

def test_sections_appear_in_the_fixed_order():
    p = assemble("PERSONA", inspiration="X.", discipline=("R.",), allow_shorts=True)
    order = [p.index(s) for s in (
        "PERSONA", "## Who you are modelled on", "## Selling short", "## How this works",
    )]
    assert order == sorted(order)


def test_the_summary_instruction_is_last():
    # Recency is the cheapest instruction-following the prompt gets, and the
    # write-up is the step most often skipped.
    p = assemble("PERSONA", inspiration="X.", allow_shorts=True)
    assert p.index("## Finishing") > p.index("## Selling short")
    assert p.rstrip().endswith("preamble, no markdown headings.")


# ── roster vs the database projection ───────────────────────────────────────
# The prompt is read from roster.py; every broker-enforced limit is read from
# arena_agents. A spec edited without `sync-roster` therefore produces an agent
# TOLD it may short and then refused by the broker — which is exactly what
# happened: Michael Beary tried once (sell 60 STX against a holding of 10), was
# rejected, and never tried again. Nothing errored.

from services.arena.scheduler import roster_drift


def _db_row(slug="michael-beary", **kw):
    from services.arena.roster import BY_SLUG
    spec = BY_SLUG[slug]
    row = {
        "slug": slug,
        "strategy_key": slug,
        "allow_shorts": spec.allow_shorts,
        "max_position_pct": spec.max_position_pct,
        "max_positions": spec.max_positions,
        "max_gross_exposure_pct": spec.max_gross_exposure_pct,
        "starting_cash": spec.starting_cash,
    }
    row.update(kw)
    return row


def test_a_matching_projection_reports_no_drift():
    assert roster_drift([_db_row()]) == []


def test_the_exact_failure_that_cost_a_replay_is_caught():
    drift = roster_drift([_db_row(allow_shorts=False)])
    assert drift == ["michael-beary.allow_shorts: roster=True db=False"]


def test_numeric_limits_drift_too():
    assert roster_drift([_db_row(max_position_pct=0.05)])
    assert roster_drift([_db_row(max_positions=99)])


def test_an_agent_with_no_spec_is_skipped_not_flagged():
    # A row left behind by a renamed or retired agent must not block a run.
    assert roster_drift([{"slug": "ghost", "strategy_key": "ghost", "allow_shorts": True}]) == []


def test_missing_columns_are_not_treated_as_disagreement():
    assert roster_drift([{"slug": "michael-beary", "strategy_key": "michael-beary"}]) == []
