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
import html
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


def _send_telegram_message(chat_id: str, text: str) -> tuple[bool, int | None, str | None]:
    """
    Send a single Telegram message (HTML parse mode).
    Returns (success, telegram_message_id, error_text).
    Requires TELEGRAM_BOT_TOKEN env var.
    """
    import httpx
    if not os.environ.get("TELEGRAM_BOT_TOKEN"):
        msg = "TELEGRAM_BOT_TOKEN not set — skipping delivery"
        logger.warning("[telegram] %s", msg)
        return False, None, msg
    try:
        r = httpx.post(
            _tg_url("sendMessage"),
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=15,
        )
        if r.status_code == 200:
            telegram_message_id = r.json().get("result", {}).get("message_id")
            return True, telegram_message_id, None
        err = f"API returned {r.status_code}: {r.text[:200]}"
        logger.warning("[telegram] %s", err)
        return False, None, err
    except Exception as exc:
        logger.error("[telegram] send failed: %s", exc)
        return False, None, str(exc)


def _send_telegram_chunks(chat_id: str, text: str) -> tuple[bool, int | None, str | None]:
    """
    Split text into ≤4096-char chunks and send sequentially.
    Returns (overall_success, last_telegram_message_id, last_error_text).
    """
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
    last_message_id: int | None = None
    last_error: str | None = None
    for chunk in chunks:
        ok, message_id, error = _send_telegram_message(chat_id, chunk)
        if not ok:
            success = False
            last_error = error
        else:
            last_message_id = message_id
    return success, last_message_id, last_error


def _tg_link(url: str, text: str) -> str:
    return f'<a href="{html.escape(url, quote=True)}">{html.escape(text)}</a>'


def _format_sources_html(sources: object) -> list[str]:
    """Render article citations as Telegram HTML bullet lines."""
    if not isinstance(sources, list) or not sources:
        return []
    out: list[str] = []
    for s in sources:
        if not isinstance(s, dict):
            continue
        url = s.get("url") or ""
        aid = s.get("article_id", "")
        title = (s.get("title") or "").strip() or f"Article {aid}"
        if url:
            out.append(f"  • {_tg_link(str(url), str(title))}")
        else:
            out.append(f"  • {html.escape(str(title))}")
    return out


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
            for src_line in _format_sources_html(item.get("sources")):
                lines.append(src_line)
        lines.append("")

    # ── Portfolio Watch ───────────────────────────────────────────────────────
    portfolio = narrative.get("portfolio_watch", [])
    lines.append("📊 <b>PORTFOLIO WATCH</b>")
    if portfolio:
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
            for src_line in _format_sources_html(item.get("sources")):
                lines.append(src_line)
    else:
        lines.append("No material portfolio changes in the current lookback window.")
    lines.append("")

    # ── Screening Update ──────────────────────────────────────────────────────
    screening = narrative.get("screening_update", [])
    if screening:
        lines.append("🔭 <b>SCREENING UPDATE</b>")
        for item in screening:
            lines.append(f"<b>{item.get('ticker','')}</b>")
            if item.get("narrative"):
                lines.append(f"  {item['narrative']}")
            for src_line in _format_sources_html(item.get("sources")):
                lines.append(src_line)
        lines.append("")

    # ── Market Pulse ──────────────────────────────────────────────────────────
    pulse = narrative.get("market_pulse", "")
    if pulse:
        lines.append("🌐 <b>MARKET PULSE</b>")
        lines.append(pulse)
        mp_src = _format_sources_html(narrative.get("market_pulse_sources"))
        if mp_src:
            lines.append("<i>Sources:</i>")
            lines.extend(mp_src)
        lines.append("")

    lines.append("<i>Generated by Swingtrader · Not financial advice</i>")
    return "\n".join(lines)


# ── Delivery orchestration ────────────────────────────────────────────────────

def _log_telegram_message(
    client,
    schema: str,
    user_id: str,
    chat_id: str,
    text: str,
    success: bool,
    telegram_message_id: int | None,
    error_text: str | None,
) -> None:
    """Insert a row into telegram_message_log (best-effort, never raises)."""
    try:
        client.schema(schema).table("telegram_message_log").insert({
            "user_id": user_id,
            "chat_id": chat_id,
            "message_type": "daily_narrative",
            "message_text": text[:4096],  # store first chunk for audit
            "telegram_message_id": telegram_message_id,
            "success": success,
            "error_text": error_text,
        }).execute()
    except Exception as exc:
        logger.warning("[telegram] failed to write message log: %s", exc)


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

    # Default to 'both' — send via Telegram AND store in-app.
    # Only skip Telegram if the user explicitly chose 'in_app'.
    method = prefs.get("delivery_method", "both")
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
    sent, telegram_message_id, error_text = _send_telegram_chunks(chat_id, text)

    _log_telegram_message(
        client, schema, user_id, chat_id, text,
        success=sent,
        telegram_message_id=telegram_message_id,
        error_text=error_text,
    )

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
                        .select(
                            "portfolio_section,screening_section,alert_warnings,market_pulse,market_pulse_sources"
                        )
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
                        "market_pulse_sources": row.get("market_pulse_sources") or [],
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

    try:
        from src.health import JobHeartbeat
        with JobHeartbeat("daily_narrative", expected_interval_h=24.0):
            asyncio.run(_main(args.user_id, args.lookback_hours, args.deliver))
    except ImportError:
        asyncio.run(_main(args.user_id, args.lookback_hours, args.deliver))
