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
from .script_generator import generate_script
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


async def run_daily_podcast(data_fetcher_fn: Callable[[], Awaitable[dict] | dict]) -> None:
    if not PODCAST_ENABLED:
        log.info("Podcast disabled (PODCAST_ENABLED=false)")
        return

    today = str(date.today())
    log.info("Starting daily podcast pipeline for %s", today)

    try:
        data = data_fetcher_fn()
        if asyncio.iscoroutine(data):
            data = await data

        script = await generate_script(data)

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

        url = await publish_episode(metadata, today)

        title = metadata["title"]
        duration = metadata["duration_seconds"]
        chars = _count_chars(script)

        await _log_to_supabase(today, title, url, duration, script, chars, "published")

        await _send_notification(
            f"✅ Episode published: <b>{title}</b>\n{url}"
        )
        log.info("Daily podcast pipeline complete: %s", url)

    except Exception as exc:
        log.exception("Podcast pipeline failed: %s", exc)
        await _send_notification(f"❌ Podcast pipeline failed ({today}): {exc}")
        await _log_to_supabase(today, "", "", 0, {}, 0, "error")
        raise
