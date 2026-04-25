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

from news_impact.narrative_generator import (
    generate_for_user,
    generate_all,
    build_prompt_for_user,
    _DEFAULT_LOOKBACK_HOURS,
    _DEFAULT_NETWORK_LOOKBACK_DAYS,
)  # noqa: E402
from src.health import PartialJobFailure  # noqa: E402
from src.db import get_supabase_client, get_schema  # noqa: E402

_EASTERN = ZoneInfo("America/New_York")
logger = logging.getLogger(__name__)


def _score_tier(score: float) -> str:
    """Translate a -1..+1 sentiment score into human language."""
    abs_s = abs(score)
    if abs_s >= 0.6:
        tier = "strong"
    elif abs_s >= 0.3:
        tier = "moderate"
    elif abs_s >= 0.1:
        tier = "mild"
    else:
        return "neutral"
    return f"{tier} {'bullish' if score > 0 else 'bearish'}"

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
            sent_str = _score_tier(sentiment)
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

def _print_dry_run(user_id: str, lookback_hours: int, network_lookback_days: int) -> None:
    """Print the full model prompt and article context without calling Ollama."""
    ctx, prompt = build_prompt_for_user(
        user_id,
        lookback_hours=lookback_hours,
        network_lookback_days=network_lookback_days,
    )
    sep = "=" * 72

    print(f"\n{sep}")
    print(
        f"DRY RUN — user={user_id}  lookback={lookback_hours}h  network_lookback={network_lookback_days}d  date={ctx.narrative_date}"
    )
    print(sep)

    print(f"\n── Positions ({len(ctx.open_positions)}) ──")
    for p in ctx.open_positions:
        print(f"  {p.ticker:6s}  qty={p.net_qty:+.2f}  avg={p.avg_cost}")

    print(f"\n── Active screens ({len(ctx.active_screen_tickers)}) ──")
    print("  " + (", ".join(ctx.active_screen_tickers) or "(none)"))

    print(f"\n── Alerts ({len(ctx.alert_items)}) ──")
    for a in ctx.alert_items:
        print(f"  {a.ticker}  {a.alert_type}  @ {a.alert_price}")

    portfolio_article_count = sum(len(v) for v in ctx.portfolio_news.values())
    screening_article_count = sum(len(v) for v in ctx.screening_news.values())
    related_article_count = sum(len(v) for v in ctx.related_news.values())

    print(f"\n── Portfolio news  ({portfolio_article_count} articles across {len(ctx.portfolio_news)} tickers) ──")
    for ticker, items in sorted(ctx.portfolio_news.items()):
        for it in items:
            ts = it.published_at.strftime("%Y-%m-%d %H:%M") if it.published_at else "?"
            score = f"{it.sentiment_score:+.2f}" if it.sentiment_score else "  n/a"
            print(f"  [{ticker}] id={it.article_id} {ts} sentiment={score}  {it.title[:90]}")

    print(f"\n── Screening news  ({screening_article_count} articles across {len(ctx.screening_news)} tickers) ──")
    for ticker, items in sorted(ctx.screening_news.items()):
        for it in items:
            ts = it.published_at.strftime("%Y-%m-%d %H:%M") if it.published_at else "?"
            score = f"{it.sentiment_score:+.2f}" if it.sentiment_score else "  n/a"
            print(f"  [{ticker}] id={it.article_id} {ts} sentiment={score}  {it.title[:90]}")

    print(f"\n── Related-network traversal diagnostics  ({len(ctx.related_seed_diagnostics)} seed runs) ──")
    if ctx.related_seed_diagnostics:
        for diag in ctx.related_seed_diagnostics:
            seed = str(diag.get("seed_ticker") or "?")
            visited_nodes = int(diag.get("visited_nodes") or 0)
            traversed_edges = int(diag.get("traversed_edges") or 0)
            qualified = int(diag.get("qualified_candidates") or 0)
            print(
                f"  seed={seed}  visited_nodes={visited_nodes}  traversed_edges={traversed_edges}  qualified_candidates={qualified}"
            )
            top_candidates = diag.get("top_candidates") or []
            for c in top_candidates[:5]:
                ticker = str(c.get("ticker") or "?")
                score = float(c.get("score") or 0.0)
                path = str(c.get("path") or "")
                print(f"    -> {ticker}  score={score:.3f}  path: {path}")
    else:
        print("  (no traversal diagnostics captured)")

    print(f"\n── Related-network news  ({related_article_count} articles across {len(ctx.related_news)} tickers) ──")
    for ticker, items in sorted(ctx.related_news.items(), key=lambda kv: ctx.related_ticker_scores.get(kv[0], 0), reverse=True):
        score = ctx.related_ticker_scores.get(ticker, 0)
        path = " → ".join(ctx.related_ticker_paths.get(ticker, []))
        print(f"  [{ticker}] graph_score={score:.3f}  path: {path}")
        for it in items:
            ts = it.published_at.strftime("%Y-%m-%d %H:%M") if it.published_at else "?"
            print(f"    id={it.article_id} {ts}  {it.title[:90]}")

    print(f"\n── Semantic evidence  ({len(ctx.semantic_evidence)} snippets) ──")
    for ev in ctx.semantic_evidence:
        print(f"  id={ev.get('article_id')}  {str(ev.get('title',''))[:80]}")
        if ev.get("snippet"):
            print(f"    {str(ev['snippet'])[:120]}")

    print(f"\n{sep}")
    print("FULL PROMPT SENT TO MODEL")
    print(sep)
    print(prompt)
    print(sep + "\n")


async def _main(
    user_id: str | None,
    lookback_hours: int,
    network_lookback_days: int,
    deliver: bool,
    dry_run: bool = False,
) -> dict:
    today = datetime.now(_EASTERN).date().isoformat()
    meta: dict = {"narrative_date": today, "lookback_hours": lookback_hours}

    if dry_run:
        if not user_id:
            logger.error("--dry-run requires --user-id")
            sys.exit(1)
        _print_dry_run(user_id, lookback_hours, network_lookback_days)
        return meta

    if user_id:
        narrative = await generate_for_user(
            user_id,
            lookback_hours=lookback_hours,
            network_lookback_days=network_lookback_days,
        )
        logger.info("[run_daily_narrative] done for user=%s", user_id)
        print(json.dumps(narrative, indent=2, default=str))
        meta["users_processed"] = 1
        meta["users_failed"] = 0
        if deliver:
            _deliver_if_needed(user_id, narrative, today)
    else:
        processed, failed = await generate_all(network_lookback_days=network_lookback_days)
        logger.info("[run_daily_narrative] done for %d users (%d failed)", len(processed), len(failed))
        meta["users_processed"] = len(processed)
        meta["users_failed"] = len(failed)
        telegrams_sent = 0
        telegrams_failed = 0
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
                    telegrams_sent += 1
                except Exception as exc:
                    logger.error("[delivery] failed for user=%s: %s", uid, exc)
                    telegrams_failed += 1
        meta["telegrams_sent"] = telegrams_sent
        meta["telegrams_failed"] = telegrams_failed
        if failed and processed:
            raise PartialJobFailure(
                f"{len(failed)}/{len(processed) + len(failed)} users failed: {failed}"
            )
        elif failed:
            raise RuntimeError(
                f"All {len(failed)} user(s) failed: {failed}"
            )
    return meta


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    parser = argparse.ArgumentParser(description="Generate and optionally deliver the daily narrative")
    parser.add_argument("--user-id", help="Generate for a specific user UUID only")
    parser.add_argument("--lookback-hours", type=int, default=_DEFAULT_LOOKBACK_HOURS)
    parser.add_argument("--network-lookback-days", type=int, default=_DEFAULT_NETWORK_LOOKBACK_DAYS)
    parser.add_argument(
        "--deliver",
        action="store_true",
        help="Send Telegram message if user has telegram delivery configured",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print articles and full model prompt without calling Ollama or writing to DB. Requires --user-id.",
    )
    args = parser.parse_args()

    if args.dry_run:
        # Dry-run bypasses health tracking entirely — no DB writes, no Ollama.
        asyncio.run(
            _main(
                args.user_id,
                args.lookback_hours,
                args.network_lookback_days,
                deliver=False,
                dry_run=True,
            )
        )
    else:
        try:
            from src.health import JobHeartbeat, update_job_metadata
            with JobHeartbeat("daily_narrative", expected_interval=24.0):
                _meta = asyncio.run(
                    _main(
                        args.user_id,
                        args.lookback_hours,
                        args.network_lookback_days,
                        args.deliver,
                    )
                )
            update_job_metadata("daily_narrative", _meta)
        except ImportError:
            asyncio.run(
                _main(
                    args.user_id,
                    args.lookback_hours,
                    args.network_lookback_days,
                    args.deliver,
                )
            )
