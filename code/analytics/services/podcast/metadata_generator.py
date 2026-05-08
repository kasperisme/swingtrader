"""
Episode metadata generator — always derive a real title + description from the
finalized act content.

Why this exists: the script and producer LLMs are asked to emit
``episode_title`` / ``episode_description`` alongside the acts, but they
occasionally drop either field (or fall back to the literal "The Impact Tape"
placeholder). When that happens, the row written to ``swingtrader.podcast_episodes``
has a generic title and an empty description, which then leaks into the RSS feed
and the UI.

This module runs after the script is finalized and uses the actual transcribed
lines (acts 1-6 only — HOOK / WELCOME / SIGN_OFF are deterministic boilerplate
and irrelevant to the episode's narrative) to produce:

  - episode_title:       5-9 words, concrete, no "Daily Recap" generics
  - episode_description: 2-3 sentence show-notes summary

The call is best-effort. If Ollama fails or returns unparseable JSON, the
existing values are kept and we log a warning instead of failing the pipeline.
"""

from __future__ import annotations

import json
import logging
import re
import time

import httpx

from .config import OLLAMA_BASE_URL, OLLAMA_PODCAST_SCRIPT_MODEL

log = logging.getLogger(__name__)


_GENERIC_TITLES = {"", "newsimpact daily", "news impact daily", "the impact tape"}
_LLM_ACT_NAMES = {
    "COLD OPEN",
    "EXECUTIVE SUMMARY",
    "MARKET REGIME BRIEFING",
    "TOP STORY DEEP DIVE",
    "WATCHLIST PULSE",
    "CLOSE + THESIS",
}


def _extract_transcript(script: dict) -> str:
    """Flatten the LLM-written acts into a single transcript string.

    Skips HOOK / WELCOME / SIGN_OFF so the summary reflects the day's actual
    narrative rather than the boilerplate intro/outro.
    """
    parts: list[str] = []
    for act in script.get("acts", []) or []:
        name = (act.get("name") or "").strip().upper()
        if name not in _LLM_ACT_NAMES:
            continue
        parts.append(f"## {name}")
        for line in act.get("lines", []) or []:
            text = (line.get("text") or "").strip()
            if not text:
                continue
            text = re.sub(r"<break[^>]*/>", " ", text)
            text = re.sub(r"\s+", " ", text).strip()
            parts.append(text)
        parts.append("")
    return "\n".join(parts).strip()


def _parse_metadata_json(raw: str) -> dict | None:
    cleaned = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL)
    idx = cleaned.find("{")
    if idx == -1:
        return None
    cleaned = cleaned[idx:]
    cleaned = re.sub(r"```[a-z]*\s*$", "", cleaned.strip()).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return None


async def _call_metadata_model(transcript: str, date_str: str) -> dict | None:
    system = (
        "You write podcast episode metadata for The Impact Tape, a swing-trader "
        "market intelligence show. Read the transcript and emit ONLY JSON with "
        '"episode_title" (5-9 words, concrete, names the day\'s actual story or '
        'thread — not "Daily Recap" or "Market Update") and "episode_description" '
        "(2-3 sentences, show-notes style, mentions the headline name/ticker or "
        "regime read so a listener can decide whether to play it). "
        "Start with { and end with }. No preamble, no markdown."
    )
    user = (
        f"Episode date: {date_str}\n\n"
        f"TRANSCRIPT:\n\n{transcript}\n\n"
        "Return JSON: {\"episode_title\": \"...\", \"episode_description\": \"...\"}"
    )

    started = time.monotonic()
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(
            f"{OLLAMA_BASE_URL}/api/chat",
            json={
                "model": OLLAMA_PODCAST_SCRIPT_MODEL,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "stream": False,
                "options": {"temperature": 0.4, "num_predict": 400},
            },
        )
        if r.status_code >= 400:
            log.warning(
                "Metadata model HTTP %s: %s",
                r.status_code,
                r.text[:300],
            )
            return None
        body = r.json()

    raw = (body.get("message") or {}).get("content", "") or ""
    parsed = _parse_metadata_json(raw)
    elapsed = time.monotonic() - started
    if parsed is None:
        log.warning(
            "Metadata model returned unparseable JSON in %.1fs (head=%r)",
            elapsed,
            raw[:160],
        )
        return None
    log.info(
        "Metadata model: title+description regenerated in %.1fs (raw=%d chars)",
        elapsed,
        len(raw),
    )
    return parsed


def _is_generic_title(title: str | None) -> bool:
    return (title or "").strip().lower() in _GENERIC_TITLES


async def regenerate_episode_metadata(script: dict, date_str: str) -> dict:
    """Fill or replace the script's episode_title + episode_description.

    Always runs against the LLM-written acts so the published metadata
    reflects the day's actual story. The existing values are preserved when
    the model returns nothing parseable, so this is safe to call
    unconditionally.
    """
    transcript = _extract_transcript(script)
    if not transcript:
        log.warning(
            "Metadata regeneration skipped — no LLM-act content found in script"
        )
        return script

    try:
        parsed = await _call_metadata_model(transcript, date_str)
    except (httpx.TimeoutException, httpx.HTTPError) as exc:
        log.warning(
            "Metadata regeneration skipped — %s: %s",
            type(exc).__name__,
            exc,
        )
        return script

    if not parsed:
        return script

    new_title = str(parsed.get("episode_title") or "").strip()
    new_desc = str(parsed.get("episode_description") or "").strip()

    old_title = str(script.get("episode_title") or "").strip()
    old_desc = str(script.get("episode_description") or "").strip()

    # Only overwrite when we actually got something better — guards against a
    # model that echoed the placeholder back.
    if new_title and not _is_generic_title(new_title):
        if new_title != old_title:
            log.info(
                "Episode title updated: %r → %r", old_title, new_title
            )
        script["episode_title"] = new_title
    elif _is_generic_title(old_title):
        log.warning(
            "Metadata regeneration produced no usable title — leaving generic %r",
            old_title,
        )

    if new_desc:
        if new_desc != old_desc:
            log.info(
                "Episode description updated (%d → %d chars)",
                len(old_desc),
                len(new_desc),
            )
        script["episode_description"] = new_desc
    elif not old_desc:
        log.warning("Metadata regeneration produced no description and none existed")

    return script
