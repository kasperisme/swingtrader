"""Multi-agent pipeline orchestrator.

Full pipeline: producer → sequential per-scene researcher → sequential
per-scene writer chains → editor junction smoothing → deterministic
HOOK / WELCOME / SIGN_OFF injection.

Sequencing rationale:
- Researchers run sequentially so scene N sees scenes 1..N-1's
  carry-forward strings — keeps the storyline chained.
- Writers run sequentially so writer N sees writer N-1's last lines
  (the "tail") — clean hand-offs even before the editor.
- Editor runs once across the full draft, rewriting only the last 1–2
  lines of each act and the first 1–2 of the next at the five LLM
  junctions (1→2 through 5→6). Surgical, not a rewrite pass.
- Deterministic injection (HOOK / WELCOME / SIGN_OFF) is reused from
  ``script_generator``'s helpers so the multi-agent path's bookend acts
  are byte-identical to the single-agent path.

Falls back to the single-agent pipeline (gather_dossier + generate_script)
on producer or scene-level failure when
``PODCAST_MULTI_AGENT_FALLBACK_ON_FAILURE=true``. The editor is best-effort
— failures there ship the unedited draft rather than fall back.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import date

from ..config import SCRIPTS_DIR
from ..data_fetcher import _fetch_news_24h_stats, _fetch_regime_and_breadth, session_meta
from .editor import edit_junctions
from .producer import plan_episode
from .scene_researcher import research_scene
from .scene_writer import write_scene

log = logging.getLogger(__name__)


PODCAST_MULTI_AGENT_FALLBACK_ON_FAILURE = (
    os.environ.get("PODCAST_MULTI_AGENT_FALLBACK_ON_FAILURE", "false").lower()
    == "true"
)

# Editor pass is on by default. Disable to ship the raw 6-scene draft
# (useful when comparing pre/post-edit quality or skipping an LLM call to
# save cost).
PODCAST_EDITOR_ENABLED = (
    os.environ.get("PODCAST_EDITOR_ENABLED", "true").lower() == "true"
)

# Number of trailing lines from each scene that the next writer sees as
# the "prior tail". Two is enough for a clean hand-off without leaking too
# much context.
_TAIL_LINES = int(os.environ.get("PODCAST_TAIL_LINES", "2"))


def _build_world_state(today: str, scout_results: dict) -> dict:
    """Harvest the producer's tool_results into a world-state baseline.

    The baseline is the same shape ``data_fetcher.fetch_live_data()``
    returns so per-scene researchers can read it directly. Missing
    aggregates (regime/breadth, news_24h_stats) are filled by direct
    fetches because the deterministic HOOK act needs articles_24h /
    sources_24h and act 3 always needs regime/breadth.
    """
    world: dict = {"date": today, **session_meta(today)}

    rb = scout_results.get("get_market_regime_and_breadth")
    if isinstance(rb, dict) and "regime" in rb and "breadth" in rb:
        world["regime"] = rb["regime"]
        world["breadth"] = rb["breadth"]
    else:
        log.warning(
            "Multi-agent: producer didn't fetch regime/breadth — fetching directly"
        )
        regime, breadth = _fetch_regime_and_breadth()
        world["regime"] = regime
        world["breadth"] = breadth

    news_stats = scout_results.get("get_news_24h_stats")
    if isinstance(news_stats, dict) and "articles_24h" in news_stats:
        world["articles_24h"] = int(news_stats.get("articles_24h") or 0)
        world["sources_24h"] = int(news_stats.get("sources_24h") or 0)
    else:
        log.warning(
            "Multi-agent: producer didn't fetch news_24h stats — fetching directly"
        )
        articles, sources = _fetch_news_24h_stats()
        world["articles_24h"] = articles
        world["sources_24h"] = sources

    vix = scout_results.get("get_vix")
    if isinstance(vix, dict) and "current" in vix:
        world["vix"] = vix
    else:
        world["vix"] = {"current": 0, "change_pct": 0, "direction": "flat"}

    if scout_results.get("get_top_news"):
        world["top_news"] = scout_results["get_top_news"]
    if scout_results.get("get_watchlist_setups"):
        world["watchlist"] = scout_results["get_watchlist_setups"]
    if scout_results.get("get_earnings"):
        world["earnings"] = scout_results["get_earnings"]
    if scout_results.get("get_insider_activity"):
        world["insider"] = scout_results["get_insider_activity"]

    return world


def _extract_tail(scene_script: dict, n: int) -> list[dict]:
    lines = scene_script.get("lines") or []
    return list(lines[-n:])


def _inject_deterministic_acts(script: dict, world: dict) -> dict:
    """Prepend HOOK + WELCOME and append SIGN_OFF.

    Reuses the single-agent path's helpers so the bookend acts are
    identical across pipelines. Idempotent: re-running on a script that
    already contains a HOOK or SIGN_OFF won't double-inject.
    """
    from ..script_generator import _hook_act, _signoff_act, _welcome_act

    welcome = _welcome_act()
    if welcome is not None:
        existing = script.get("acts") or []
        if not (existing and existing[0].get("act") == 0):
            script["acts"] = [welcome] + existing
            log.info("Multi-agent: welcome act prepended")
    else:
        log.info(
            "Multi-agent: welcome act skipped — set ELEVENLABS_PRIMARY_VOICE_NAME "
            "and ELEVENLABS_SECONDARY_VOICE_NAME to enable"
        )

    hook = _hook_act(
        article_count=int(world.get("articles_24h") or 0),
        source_count=int(world.get("sources_24h") or 0),
    )
    existing = script.get("acts") or []
    if not (existing and existing[0].get("name") == "HOOK"):
        script["acts"] = [hook] + existing
        log.info(
            "Multi-agent: hook act prepended (articles_24h=%d, sources_24h=%d)",
            world.get("articles_24h", 0),
            world.get("sources_24h", 0),
        )

    existing = script.get("acts") or []
    if not any(a.get("name") == "SIGN_OFF" for a in existing):
        script["acts"] = existing + [_signoff_act()]
        log.info("Multi-agent: sign-off act appended")

    return script


async def _run_phase2(today: str) -> dict:
    """Producer → sequential researcher/writer chain → deterministic injection."""
    pipeline_start = time.monotonic()
    log.info("Multi-agent (Phase 2): start for %s", today)

    brief, scout_results = await plan_episode(today)
    world = _build_world_state(today, scout_results)
    log.info(
        "Multi-agent: world state assembled — keys=%s",
        sorted(k for k in world.keys() if not k.startswith("_")),
    )

    written_scenes: list[dict] = []
    carry_forward_chain: list[dict] = []
    prior_tail: list[dict] = []

    for scene_brief in brief["scenes"]:
        scene_dossier = await research_scene(
            today=today,
            weekday=world.get("weekday", ""),
            scene=scene_brief,
            episode_brief=brief,
            world_state=world,
            carry_forward_chain=list(carry_forward_chain),
        )
        carry_forward_chain.append(
            {
                "act": scene_dossier["act"],
                "name": scene_dossier["name"],
                "carry_forward": scene_dossier.get("carry_forward", ""),
            }
        )

        scene_script = await write_scene(
            scene=scene_brief,
            episode_brief=brief,
            world_state=world,
            scene_dossier=scene_dossier,
            prior_tail_lines=prior_tail,
        )
        written_scenes.append(scene_script)
        prior_tail = _extract_tail(scene_script, _TAIL_LINES)

    if PODCAST_EDITOR_ENABLED:
        written_scenes = await edit_junctions(written_scenes, brief)
    else:
        log.info(
            "Multi-agent: editor disabled (PODCAST_EDITOR_ENABLED=false) — "
            "shipping raw 6-scene draft"
        )

    script = {
        "episode_title": brief.get("episode_title") or "The Impact Tape",
        "episode_description": brief.get("episode_description")
        or brief.get("scouting_notes", ""),
        "acts": written_scenes,
    }

    _inject_deterministic_acts(script, world)

    SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = SCRIPTS_DIR / f"{today}.json"
    serialized = json.dumps(script, indent=2)
    out_path.write_text(serialized)
    log.info(
        "Multi-agent (Phase 2): script ready in %.1fs — %d acts (%d bytes) → %s",
        time.monotonic() - pipeline_start,
        len(script.get("acts", [])),
        len(serialized),
        out_path,
    )
    return script


async def _fallback_to_single_agent(today: str, reason: str) -> dict:
    log.error(
        "Multi-agent: %s — falling back to single-agent path. "
        "Set PODCAST_MULTI_AGENT_FALLBACK_ON_FAILURE=false to fail hard.",
        reason,
    )
    from ..research_agent import gather_dossier
    from ..script_generator import generate_script

    dossier = await gather_dossier(today)
    return await generate_script(dossier)


async def run_multi_agent_pipeline(today: str | None = None) -> dict:
    """Run the full multi-agent pipeline; return the final script dict.

    Returns the same shape ``script_generator.generate_script`` returns
    (acts list with HOOK / WELCOME / SIGN_OFF already injected). The
    caller (``scheduler_hook.run_daily_podcast``) treats the result
    identically to the single-agent path.
    """
    today_iso = today or str(date.today())
    try:
        return await _run_phase2(today_iso)
    except Exception as exc:
        # Any agent-level failure (producer, researcher, writer, editor)
        # stops the show. Content-level errors mean the planned episode
        # can't be made — falling back to single-agent would ship a
        # different show than what was planned, hiding the real problem.
        from .scene_researcher import PodcastAgentError

        if isinstance(exc, PodcastAgentError):
            log.error(
                "Multi-agent: %s failed — aborting pipeline (no fallback for "
                "agent-level failures). %s",
                type(exc).__name__,
                exc,
            )
            raise
        if not PODCAST_MULTI_AGENT_FALLBACK_ON_FAILURE:
            raise
        return await _fallback_to_single_agent(
            today_iso, f"phase 2 failed ({type(exc).__name__}: {exc})"
        )
