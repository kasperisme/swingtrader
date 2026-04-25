"""
telegram.py — shared Telegram Bot API utilities.

Reused by run_daily_narrative.py and screen_agent/engine.py.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime

import httpx

from .db import get_supabase_client, get_schema

log = logging.getLogger(__name__)

_TG_API = "https://api.telegram.org/bot{token}/{method}"
_TG_MAX_CHARS = 4096


def _tg_url(method: str) -> str:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    return _TG_API.format(token=token, method=method)


def send_telegram_message(
    chat_id: str, text: str,
) -> tuple[bool, int | None, str | None]:
    if not os.environ.get("TELEGRAM_BOT_TOKEN"):
        return False, None, "TELEGRAM_BOT_TOKEN not set"
    try:
        r = httpx.post(
            _tg_url("sendMessage"),
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=15,
        )
        if r.status_code == 200:
            msg_id = r.json().get("result", {}).get("message_id")
            return True, msg_id, None
        err = f"API {r.status_code}: {r.text[:200]}"
        log.warning("[telegram] %s", err)
        return False, None, err
    except Exception as exc:
        log.error("[telegram] send failed: %s", exc)
        return False, None, str(exc)


def send_telegram_chunks(
    chat_id: str, text: str,
) -> tuple[bool, int | None, str | None]:
    chunks: list[str] = []
    while len(text) > _TG_MAX_CHARS:
        split_at = text.rfind("\n", 0, _TG_MAX_CHARS)
        if split_at < 0:
            split_at = _TG_MAX_CHARS
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")
    if text:
        chunks.append(text)

    success = True
    last_id: int | None = None
    last_err: str | None = None
    for chunk in chunks:
        ok, msg_id, err = send_telegram_message(chat_id, chunk)
        if not ok:
            success = False
            last_err = err
        else:
            last_id = msg_id
    return success, last_id, last_err


def get_user_chat_id(user_id: str) -> str | None:
    client = get_supabase_client()
    schema = get_schema()
    res = (
        client.schema(schema)
        .table("user_telegram_connections")
        .select("chat_id")
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    return ((res.data or [{}])[0]).get("chat_id")


def log_telegram_message(
    *,
    user_id: str,
    chat_id: str,
    message_type: str,
    message_text: str,
    success: bool,
    telegram_message_id: int | None = None,
    error_text: str | None = None,
) -> None:
    try:
        client = get_supabase_client()
        schema = get_schema()
        client.schema(schema).table("telegram_message_log").insert({
            "user_id": user_id,
            "chat_id": chat_id,
            "message_type": message_type,
            "message_text": message_text[:4096],
            "telegram_message_id": telegram_message_id,
            "success": success,
            "error_text": error_text,
        }).execute()
    except Exception as exc:
        log.warning("[telegram] failed to write message log: %s", exc)
