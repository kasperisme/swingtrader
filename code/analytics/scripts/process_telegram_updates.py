"""
process_telegram_updates.py
===========================

Polls swingtrader.telegram_update_requests for pending rows created by the
Telegram commands. Requests are queued by the webhook and processed on Mac.

Usage:
  python -m scripts.process_telegram_updates
  python -m scripts.process_telegram_updates --once
"""

from __future__ import annotations

import argparse
import asyncio
import html
import logging
import pathlib
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

_ANALYTICS = pathlib.Path(__file__).resolve().parent.parent
if str(_ANALYTICS) not in sys.path:
    sys.path.insert(0, str(_ANALYTICS))

load_dotenv(_ANALYTICS / ".env")

from news_impact.narrative_generator import _DEFAULT_LOOKBACK_HOURS, generate_for_user  # noqa: E402
from news_impact.semantic_retrieval import search_news_embeddings  # noqa: E402
from src.db import get_schema, get_supabase_client  # noqa: E402
from scripts.run_daily_narrative import _narrative_to_telegram, _send_telegram_chunks  # noqa: E402

logger = logging.getLogger(__name__)
_EASTERN = ZoneInfo("America/New_York")


def _claim_pending_requests(limit: int) -> list[dict]:
    """
    Fetch oldest pending rows and mark them as processing.
    Returns claimed rows as dicts.
    """
    client = get_supabase_client()
    schema = get_schema()

    pending = (
        client.schema(schema)
        .table("telegram_update_requests")
        .select("id,user_id,chat_id,request_type,request_text,requested_at")
        .eq("status", "pending")
        .order("requested_at")
        .limit(limit)
        .execute()
    )
    rows = pending.data or []
    if not rows:
        return []

    claimed: list[dict] = []
    now = datetime.now().isoformat()
    for row in rows:
        req_id = row["id"]
        res = (
            client.schema(schema)
            .table("telegram_update_requests")
            .update({"status": "processing", "started_at": now, "error_text": None})
            .eq("id", req_id)
            .eq("status", "pending")
            .execute()
        )
        if res.data:
            claimed.append(row)
    return claimed


def _load_lookback_hours(user_id: str) -> int:
    client = get_supabase_client()
    schema = get_schema()
    res = (
        client.schema(schema)
        .table("user_narrative_preferences")
        .select("lookback_hours")
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    row = (res.data or [{}])[0]
    value = row.get("lookback_hours")
    return int(value) if value is not None else _DEFAULT_LOOKBACK_HOURS


def _finish_request(
    req_id: str,
    *,
    status: str,
    response_preview: str | None = None,
    telegram_message_id: int | None = None,
    error_text: str | None = None,
) -> None:
    client = get_supabase_client()
    schema = get_schema()
    client.schema(schema).table("telegram_update_requests").update({
        "status": status,
        "completed_at": datetime.now().isoformat(),
        "response_preview": response_preview,
        "telegram_message_id": telegram_message_id,
        "error_text": error_text,
    }).eq("id", req_id).execute()


async def _process_single(row: dict) -> bool:
    """Process one update request. Returns True on success, False on failure."""
    req_id = str(row["id"])
    user_id = str(row["user_id"])
    chat_id = str(row["chat_id"])
    request_type = str(row.get("request_type") or "update")
    request_text = str(row.get("request_text") or "").strip()
    date_text = datetime.now(_EASTERN).date().isoformat()

    logger.info(
        "[tg-update] processing request id=%s user=%s type=%s",
        req_id,
        user_id,
        request_type,
    )
    try:
        lookback_hours = _load_lookback_hours(user_id)
        if request_type == "search":
            message = _build_search_response(request_text, lookback_hours=lookback_hours)
        else:
            narrative = await generate_for_user(user_id, lookback_hours=lookback_hours)
            message = _narrative_to_telegram(narrative, date_text)
        ok, message_id, send_error = _send_telegram_chunks(chat_id, message)

        if ok:
            _finish_request(
                req_id,
                status="completed",
                response_preview=message[:1200],
                telegram_message_id=message_id,
            )
            logger.info("[tg-update] completed request id=%s user=%s", req_id, user_id)
            return True
        else:
            _finish_request(
                req_id,
                status="failed",
                response_preview=message[:1200],
                error_text=send_error or "Failed to send Telegram message",
            )
            logger.error("[tg-update] send failed id=%s user=%s err=%s", req_id, user_id, send_error)
            return False
    except Exception as exc:
        _finish_request(req_id, status="failed", error_text=str(exc))
        logger.exception("[tg-update] request failed id=%s user=%s", req_id, user_id)
        return False


def _build_search_response(query: str, *, lookback_hours: int) -> str:
    q = query.strip()
    if not q:
        return (
            "🔎 <b>Search request is empty.</b>\n\n"
            "Usage: <code>/search &lt;search terms&gt;</code>"
        )
    matches = search_news_embeddings(
        q,
        lookback_hours=max(24, lookback_hours),
        limit=5,
    )
    if not matches:
        return (
            f"🔎 <b>Search results</b> for: <i>{html.escape(q)}</i>\n\n"
            "No relevant recent articles found."
        )

    lines: list[str] = [
        f"🔎 <b>Search results</b> for: <i>{html.escape(q)}</i>",
        "",
    ]
    for i, item in enumerate(matches, start=1):
        title = html.escape(str(item.get("title") or "Untitled"))
        url = html.escape(str(item.get("url") or ""), quote=True)
        similarity = float(item.get("similarity") or 0.0)
        snippet = html.escape(str(item.get("snippet") or "").strip())
        if url:
            lines.append(f"{i}. <a href=\"{url}\">{title}</a> ({similarity:.2f})")
        else:
            lines.append(f"{i}. {title} ({similarity:.2f})")
        if snippet:
            lines.append(f"   {snippet[:180]}")
        lines.append("")
    return "\n".join(lines).strip()


async def _run_loop(batch_size: int, poll_interval_sec: int, once: bool) -> dict:
    """Process pending requests. Returns metadata with request counts."""
    processed = 0
    failed = 0
    while True:
        claimed = _claim_pending_requests(batch_size)
        if claimed:
            for row in claimed:
                ok = await _process_single(row)
                if ok:
                    processed += 1
                else:
                    failed += 1
        elif once:
            return {"requests_processed": processed, "requests_failed": failed}
        else:
            time.sleep(poll_interval_sec)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    parser = argparse.ArgumentParser(description="Process queued Telegram requests")
    parser.add_argument("--batch-size", type=int, default=5)
    parser.add_argument("--poll-interval-sec", type=int, default=20)
    parser.add_argument("--once", action="store_true", help="Process one fetch cycle then exit")
    args = parser.parse_args()

    try:
        from src.health import JobHeartbeat, update_job_metadata
        with JobHeartbeat("telegram_updates", expected_interval=1 / 60):
            _meta = asyncio.run(_run_loop(args.batch_size, args.poll_interval_sec, args.once))
        if _meta:
            update_job_metadata("telegram_updates", _meta)
    except ImportError:
        asyncio.run(_run_loop(args.batch_size, args.poll_interval_sec, args.once))
