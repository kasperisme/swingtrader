"""
run_daily_narrative.py — Mac Mini cron entry point
====================================================

Generates the daily narrative for all opted-in users (or a specific user)
and optionally delivers it via Telegram Bot API.

Cron example (runs at 08:30 US Eastern every weekday):
  30 12 * * 1-5 cd /path/to/swingtrader/code/analytics && \
      /path/to/venv/bin/python -m scripts.run_daily_narrative >> logs/narrative.log 2>&1

Environment variables
---------------------
  SUPABASE_URL, SUPABASE_KEY, SUPABASE_DB_DIRECT_URL  — required (see src/db.py)
  OLLAMA_BASE_URL            — Ollama endpoint (default http://localhost:11434)
  OLLAMA_NARRATIVE_MODEL     — model for narrative synthesis (default: OLLAMA_IMPACT_MODEL)
  OLLAMA_NARRATIVE_TOKENS    — max tokens for narrative output (default 3072)
  OLLAMA_NARRATIVE_TIMEOUT   — seconds before timeout (default 180)
  TELEGRAM_BOT_TOKEN         — required for Telegram delivery (from @BotFather)

Telegram setup
--------------
  1. Create a bot via @BotFather → copy the token into TELEGRAM_BOT_TOKEN
  2. Each user must /start the bot once — the bot receives their chat_id
  3. Store each user's chat_id in swingtrader.user_telegram_connections (via /start bot flow)
  4. Set delivery_method = 'telegram' or 'both' in user_narrative_preferences
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import pathlib
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

# --- Path setup so the module runs from repo root or analytics/ ---------------
_ANALYTICS = pathlib.Path(__file__).resolve().parent.parent
if str(_ANALYTICS) not in sys.path:
    sys.path.insert(0, str(_ANALYTICS))

load_dotenv(_ANALYTICS / ".env")

from news_impact.narrative_generator import generate_for_user, generate_all, _DEFAULT_LOOKBACK_HOURS  # noqa: E402
from src.db import get_supabase_client, get_schema  # noqa: E402

_EASTERN = ZoneInfo("America/New_York")
logger = logging.getLogger(__name__)

_TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"
_TELEGRAM_MAX_CHARS = 4096  # Telegram hard limit per message


# ── Telegram delivery ─────────────────────────────────────────────────────────

def _tg_url(method: str) -> str:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    return _TELEGRAM_API.format(token=token, method=method)


def _send_telegram_message(chat_id: str, text: str) -> bool:
    """
    Send a single Telegram message (HTML parse mode).
    Returns True on success.
    Requires TELEGRAM_BOT_TOKEN env var.
    """
    import httpx
    if not os.environ.get("TELEGRAM_BOT_TOKEN"):
        logger.warning("[telegram] TELEGRAM_BOT_TOKEN not set — skipping delivery")
        return False
    try:
        r = httpx.post(
            _tg_url("sendMessage"),
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=15,
        )
        if r.status_code == 200:
            return True
        logger.warning("[telegram] API returned %d: %s", r.status_code, r.text[:200])
        return False
    except Exception as exc:
        logger.error("[telegram] send failed: %s", exc)
        return False


def _send_telegram_chunks(chat_id: str, text: str) -> bool:
    """Split text into ≤4096-char chunks and send sequentially."""
    import httpx
    chunks: list[str] = []
    while len(text) > _TELEGRAM_MAX_CHARS:
        # Try to break at a newline before the limit
        split_at = text.rfind("\n", 0, _TELEGRAM_MAX_CHARS)
        if split_at < 0:
            split_at = _TELEGRAM_MAX_CHARS
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")
    if text:
        chunks.append(text)

    success = True
    for chunk in chunks:
        if not _send_telegram_message(chat_id, chunk):
            success = False
    return success


def _narrative_to_telegram(narrative: dict, narrative_date: str) -> str:
    """
    Render the narrative dict as a Telegram HTML message.
    Telegram supports: <b>, <i>, <code>, <pre>, <a href="">.
    """
    lines: list[str] = []

    lines.append(f"<b>The Daily Narrative</b>")
    lines.append(f"{narrative_date} — Pre-market US Eastern\n")

    # ── Alert Watch ───────────────────────────────────────────────────────────
    alerts = narrative.get("alert_watch", [])
    if alerts:
        lines.append("🔔 <b>ALERT WATCH</b>")
        for item in alerts:
            pct = item.get("pct_away")
            pct_str = f"{pct:+.1f}%" if pct is not None else "?"
            atype = item.get("alert_type", "").replace("_", " ").title()
            lines.append(
                f"<b>{item.get('ticker','')}</b> — {atype} @ ${item.get('alert_price', 0):.2f} "
                f"| {pct_str} away"
            )
            if item.get("narrative"):
                lines.append(f"  <i>{item['narrative']}</i>")
        lines.append("")

    # ── Portfolio Watch ───────────────────────────────────────────────────────
    portfolio = narrative.get("portfolio_watch", [])
    if portfolio:
        lines.append("📊 <b>PORTFOLIO WATCH</b>")
        action_icons = {"monitor": "🟢", "review": "🟡", "urgent": "🔴"}
        for item in portfolio:
            action = item.get("action", "monitor")
            icon = action_icons.get(action, "⚪")
            sentiment = item.get("sentiment", 0)
            sent_str = f"{sentiment:+.2f}"
            lines.append(
                f"{icon} <b>{item.get('ticker','')}</b> {sent_str} — {action.upper()}"
            )
            if item.get("narrative"):
                lines.append(f"  {item['narrative']}")
        lines.append("")

    # ── Screening Update ──────────────────────────────────────────────────────
    screening = narrative.get("screening_update", [])
    if screening:
        lines.append("🔭 <b>SCREENING UPDATE</b>")
        for item in screening:
            lines.append(f"<b>{item.get('ticker','')}</b>")
            if item.get("narrative"):
                lines.append(f"  {item['narrative']}")
        lines.append("")

    # ── Market Pulse ──────────────────────────────────────────────────────────
    pulse = narrative.get("market_pulse", "")
    if pulse:
        lines.append("🌐 <b>MARKET PULSE</b>")
        lines.append(pulse)
        lines.append("")

    lines.append("<i>Generated by Swingtrader · Not financial advice</i>")
    return "\n".join(lines)


# ── Delivery orchestration ────────────────────────────────────────────────────

def _deliver_if_needed(user_id: str, narrative: dict, narrative_date: str) -> None:
    """Check user preferences and deliver via Telegram if configured."""
    schema = get_schema()
    client = get_supabase_client()

    prefs_res = (
        client.schema(schema)
        .table("user_narrative_preferences")
        .select("delivery_method,is_enabled")
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    prefs = (prefs_res.data or [{}])[0]

    if not prefs.get("is_enabled", True):
        return

    method = prefs.get("delivery_method", "in_app")
    if method not in ("telegram", "both"):
        logger.debug("[delivery] user=%s method=%s — skipping Telegram", user_id, method)
        return

    # chat_id lives in user_telegram_connections, not user_narrative_preferences
    tg_res = (
        client.schema(schema)
        .table("user_telegram_connections")
        .select("chat_id")
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    chat_id = ((tg_res.data or [{}])[0]).get("chat_id")
    if not chat_id:
        logger.warning(
            "[telegram] user=%s has no chat_id in user_telegram_connections — skipping. "
            "User must /start the bot first.",
            user_id,
        )
        return

    text = _narrative_to_telegram(narrative, narrative_date)
    sent = _send_telegram_chunks(chat_id, text)

    if sent:
        logger.info("[telegram] delivered to chat_id=%s for user=%s", chat_id, user_id)
        client.schema(schema).table("daily_narratives").update(
            {"delivered_at": datetime.now().isoformat()}
        ).eq("user_id", user_id).eq("narrative_date", narrative_date).execute()
    else:
        logger.error("[telegram] delivery failed for user=%s chat_id=%s", user_id, chat_id)


# ── CLI ───────────────────────────────────────────────────────────────────────

async def _main(user_id: str | None, lookback_hours: int, deliver: bool) -> None:
    today = datetime.now(_EASTERN).date().isoformat()

    if user_id:
        narrative = await generate_for_user(user_id, lookback_hours=lookback_hours)
        logger.info("[run_daily_narrative] done for user=%s", user_id)
        print(json.dumps(narrative, indent=2, default=str))
        if deliver:
            _deliver_if_needed(user_id, narrative, today)
    else:
        processed = await generate_all()
        logger.info("[run_daily_narrative] done for %d users", len(processed))
        if deliver:
            client = get_supabase_client()
            for uid in processed:
                try:
                    res = (
                        client.schema(get_schema())
                        .table("daily_narratives")
                        .select("portfolio_section,screening_section,alert_warnings,market_pulse")
                        .eq("user_id", uid)
                        .eq("narrative_date", today)
                        .limit(1)
                        .execute()
                    )
                    row = (res.data or [{}])[0]
                    narrative = {
                        "portfolio_watch": row.get("portfolio_section") or [],
                        "screening_update": row.get("screening_section") or [],
                        "alert_watch": row.get("alert_warnings") or [],
                        "market_pulse": row.get("market_pulse") or "",
                    }
                    _deliver_if_needed(uid, narrative, today)
                except Exception as exc:
                    logger.error("[delivery] failed for user=%s: %s", uid, exc)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    parser = argparse.ArgumentParser(description="Generate and optionally deliver the daily narrative")
    parser.add_argument("--user-id", help="Generate for a specific user UUID only")
    parser.add_argument("--lookback-hours", type=int, default=_DEFAULT_LOOKBACK_HOURS)
    parser.add_argument(
        "--deliver",
        action="store_true",
        help="Send Telegram message if user has telegram delivery configured",
    )
    args = parser.parse_args()

    asyncio.run(_main(args.user_id, args.lookback_hours, args.deliver))
