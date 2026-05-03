from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import date

import httpx

from .config import TELEGRAM_BOT_TOKEN

log = logging.getLogger(__name__)

_APPROVAL_TIMEOUT = 600  # 10 minutes
_POLL_INTERVAL = 3


def _count_words(script: dict) -> int:
    total = 0
    for act in script.get("acts", []):
        for line in act.get("lines", []):
            total += len(line.get("text", "").split())
    return total


def _estimated_minutes(script: dict) -> int:
    return max(1, _count_words(script) // 130)


def _format_approval_message(script: dict) -> str:
    today = str(date.today())
    title = script.get("episode_title", "Untitled")
    mins = _estimated_minutes(script)

    cold_open_line = ""
    regime_status = ""
    top_story = ""
    tickers = []

    for act in script.get("acts", []):
        if act["act"] == 1 and act.get("lines"):
            cold_open_line = act["lines"][0].get("text", "")[:120]
        if act["act"] == 2 and act.get("lines"):
            regime_status = act["lines"][0].get("text", "")[:80]

    lines = [
        f"📻 <b>PODCAST DRAFT READY</b> — {today}",
        "",
        f"🎯 {title}",
        f"⏱ ~{mins} min ({_count_words(script)} words)",
        "",
        f"COLD OPEN: {cold_open_line}...",
        f"REGIME: {regime_status}...",
        "",
        "[~$0.12–0.18 to render audio — LLM cost: $0.00 (local)]",
    ]
    return "\n".join(lines)


async def _send_message_with_keyboard(
    bot_token: str, chat_id: str, text: str, keyboard: dict
) -> int | None:
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "reply_markup": keyboard,
            },
            timeout=15,
        )
    if r.status_code == 200:
        return r.json()["result"]["message_id"]
    log.error("Failed to send Telegram message: %s", r.text)
    return None


async def _get_updates(bot_token: str, offset: int) -> list[dict]:
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"https://api.telegram.org/bot{bot_token}/getUpdates",
            params={"offset": offset, "timeout": _POLL_INTERVAL, "allowed_updates": ["callback_query", "message"]},
            timeout=_POLL_INTERVAL + 5,
        )
    if r.status_code == 200:
        return r.json().get("result", [])
    return []


async def _answer_callback(bot_token: str, callback_id: str) -> None:
    async with httpx.AsyncClient() as client:
        await client.post(
            f"https://api.telegram.org/bot{bot_token}/answerCallbackQuery",
            json={"callback_query_id": callback_id},
            timeout=10,
        )


async def _poll_for_decision(bot_token: str, chat_id: str, deadline: float) -> tuple[str, int]:
    """Poll getUpdates until we get a podcast callback. Returns (decision, update_id)."""
    offset = 0
    while time.time() < deadline:
        updates = await _get_updates(bot_token, offset)
        for update in updates:
            offset = update["update_id"] + 1
            cb = update.get("callback_query")
            if cb and str(cb.get("message", {}).get("chat", {}).get("id", "")) == str(chat_id):
                data = cb.get("data", "")
                if data in ("podcast_approve", "podcast_edit", "podcast_reject"):
                    await _answer_callback(bot_token, cb["id"])
                    decision_map = {
                        "podcast_approve": "approve",
                        "podcast_edit": "edit",
                        "podcast_reject": "reject",
                    }
                    return decision_map[data], offset
        await asyncio.sleep(_POLL_INTERVAL)
    return "reject", offset


async def _wait_for_edited_json(bot_token: str, chat_id: str, deadline: float) -> dict | None:
    """Wait for user to send an edited JSON message. Returns parsed dict or None."""
    offset = 0
    while time.time() < deadline:
        updates = await _get_updates(bot_token, offset)
        for update in updates:
            offset = update["update_id"] + 1
            msg = update.get("message")
            if msg and str(msg.get("chat", {}).get("id", "")) == str(chat_id):
                text = msg.get("text", "")
                idx = text.find("{")
                if idx != -1:
                    try:
                        return json.loads(text[idx:])
                    except json.JSONDecodeError:
                        pass
        await asyncio.sleep(_POLL_INTERVAL)
    return None


async def send_approval_request(script: dict, bot_token: str | None = None, chat_id: str | None = None) -> str:
    bot_token = bot_token or TELEGRAM_BOT_TOKEN
    chat_id = chat_id or ""

    if not bot_token or not chat_id:
        log.warning("Telegram not configured — auto-approving podcast")
        return "approve"

    text = _format_approval_message(script)
    keyboard = {
        "inline_keyboard": [[
            {"text": "✅ Approve", "callback_data": "podcast_approve"},
            {"text": "✏️ Edit", "callback_data": "podcast_edit"},
            {"text": "❌ Reject", "callback_data": "podcast_reject"},
        ]]
    }

    msg_id = await _send_message_with_keyboard(bot_token, chat_id, text, keyboard)
    if msg_id is None:
        log.warning("Could not send approval request — auto-approving")
        return "approve"

    deadline = time.time() + _APPROVAL_TIMEOUT
    decision, _ = await _poll_for_decision(bot_token, chat_id, deadline)
    log.info("Podcast approval decision: %s", decision)
    return decision


async def request_edited_script(
    original_script: dict,
    bot_token: str | None = None,
    chat_id: str | None = None,
) -> dict:
    """Send script JSON to Telegram and wait for edited reply. Falls back to original."""
    bot_token = bot_token or TELEGRAM_BOT_TOKEN
    chat_id = chat_id or ""

    if not bot_token or not chat_id:
        return original_script

    import json

    script_json = json.dumps(original_script, indent=2)
    chunks = [script_json[i:i+4000] for i in range(0, len(script_json), 4000)]
    async with httpx.AsyncClient() as client:
        for chunk in chunks:
            await client.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json={"chat_id": chat_id, "text": f"<pre>{chunk}</pre>", "parse_mode": "HTML"},
                timeout=15,
            )
        await client.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={"chat_id": chat_id, "text": "Reply with the edited JSON within 5 minutes."},
            timeout=15,
        )

    deadline = time.time() + 300  # 5 minutes
    edited = await _wait_for_edited_json(bot_token, chat_id, deadline)
    if edited is None:
        log.warning("Edit timeout — falling back to original script")
        return original_script
    return edited
