from __future__ import annotations

import asyncio
import json
import logging
from datetime import date
from pathlib import Path
from typing import Callable, Awaitable

import httpx

from .config import (
    EPISODES_DIR,
    PODCAST_ENABLED,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
)
from .elevenlabs_render import render_episode
from .episode_packager import package_episode
from .rss_publisher import publish_episode
from .script_generator import generate_script, _welcome_act
from .telegram_gate import request_edited_script, send_approval_request

log = logging.getLogger(__name__)


async def _send_notification(text: str) -> None:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    async with httpx.AsyncClient() as client:
        await client.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"},
            timeout=15,
        )


async def _log_to_supabase(
    today: str,
    title: str,
    url: str,
    duration_seconds: int,
    script: dict,
    elevenlabs_chars: int,
    status: str,
) -> None:
    try:
        from shared.db import get_supabase_client

        def _tbl(c, t):
            return c.schema("swingtrader").table(t)

        word_count = sum(
            len(line.get("text", "").split())
            for act in script.get("acts", [])
            for line in act.get("lines", [])
        )
        estimated_cost = round(elevenlabs_chars * 0.00003, 4)

        client = get_supabase_client()
        _tbl(client, "podcast_episodes").insert({
            "date": today,
            "title": title,
            "episode_url": url,
            "duration_seconds": duration_seconds,
            "script_word_count": word_count,
            "elevenlabs_chars": elevenlabs_chars,
            "estimated_cost_usd": estimated_cost,
            "status": status,
        }).execute()
        log.info("Podcast episode logged to Supabase")
    except Exception as exc:
        log.error("Failed to log episode to Supabase: %s", exc)


def _count_chars(script: dict) -> int:
    return sum(
        len(line.get("text", ""))
        for act in script.get("acts", [])
        for line in act.get("lines", [])
    )


async def run_daily_podcast(
    data_fetcher_fn: Callable[[], Awaitable[dict] | dict],
    *,
    script_only: bool = False,
    skip_approval: bool = False,
    skip_publish: bool = False,
) -> None:
    """Run the full pipeline. Optional flags skip later stages for cheap tests.

    script_only    — stop after the LLM produces the JSON script (no TTS, no publish)
    skip_approval  — bypass the Telegram approval gate
    skip_publish   — render + package locally but skip RSS / R2 / Telegram-notify
    """
    if not PODCAST_ENABLED:
        log.info("Podcast disabled (PODCAST_ENABLED=false)")
        return

    today = str(date.today())
    mode_tags = [t for t, on in [
        ("script-only", script_only),
        ("skip-approval", skip_approval),
        ("skip-publish", skip_publish),
    ] if on]
    mode_str = f" [{', '.join(mode_tags)}]" if mode_tags else ""
    log.info("Starting daily podcast pipeline for %s%s", today, mode_str)

    try:
        data = data_fetcher_fn()
        if asyncio.iscoroutine(data):
            data = await data

        script = await generate_script(data)

        if script_only:
            log.info("Stopping after script generation (script_only=True)")
            return

        if skip_approval:
            log.info("Skipping Telegram approval gate (skip_approval=True)")
        else:
            decision = await send_approval_request(
                script, bot_token=TELEGRAM_BOT_TOKEN, chat_id=TELEGRAM_CHAT_ID
            )
            if decision == "reject":
                log.info("Podcast rejected via Telegram")
                await _log_to_supabase(today, script.get("episode_title", ""), "", 0, script, 0, "rejected")
                return
            if decision == "edit":
                script = await request_edited_script(
                    script, bot_token=TELEGRAM_BOT_TOKEN, chat_id=TELEGRAM_CHAT_ID
                )

        segments_dir = EPISODES_DIR / today / "segments"
        segments = await render_episode(script, segments_dir)

        metadata = package_episode(segments, script, today, EPISODES_DIR / today)

        title = metadata["title"]
        duration = metadata["duration_seconds"]
        chars = _count_chars(script)

        if skip_publish:
            log.info("Skipping publish (skip_publish=True) — episode at %s", EPISODES_DIR / today)
            await _log_to_supabase(today, title, "", duration, script, chars, "local_only")
            return

        url = await publish_episode(metadata, today)

        await _log_to_supabase(today, title, url, duration, script, chars, "published")

        await _send_notification(
            f"✅ Episode published: <b>{title}</b>\n{url}"
        )
        log.info("Daily podcast pipeline complete: %s", url)

    except Exception as exc:
        log.exception("Podcast pipeline failed: %s", exc)
        if not (script_only or skip_publish):
            await _send_notification(f"❌ Podcast pipeline failed ({today}): {exc}")
            await _log_to_supabase(today, "", "", 0, {}, 0, "error")
        raise


async def run_welcome_only() -> Path:
    """Render only the deterministic welcome scene through ElevenLabs + pydub.

    No LLM call, no data fetcher, no Telegram, no publish, no Supabase. Useful
    for verifying voice configuration, ElevenLabs credentials, and audio
    stitching end-to-end with minimal API spend (~2 short TTS calls).

    Returns the path to the packaged MP3.
    """
    today = str(date.today())
    log.info("Starting welcome-only test render for %s", today)

    welcome = _welcome_act()
    if welcome is None:
        raise RuntimeError(
            "ELEVENLABS_PRIMARY_VOICE_NAME and ELEVENLABS_SECONDARY_VOICE_NAME "
            "must both be set to render the welcome scene"
        )

    script = {
        "episode_title": f"Welcome test — {today}",
        "episode_description": "Local test render of the deterministic welcome scene. Not for publication.",
        "acts": [welcome],
    }

    output_root = EPISODES_DIR / f"{today}_welcome_test"
    segments_dir = output_root / "segments"
    segments = await render_episode(script, segments_dir)

    metadata = package_episode(segments, script, today, output_root)

    log.info(
        "Welcome-only render complete — %d chars TTS, %.1fs audio at %s",
        _count_chars(script), metadata["duration_seconds"], output_root,
    )
    return output_root / f"{today}_episode.mp3"
