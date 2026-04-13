"""
Daily Narrative Generator
=========================

Synthesises a personalised pre-market briefing for one or all opted-in users.

Data sources
------------
  user_trades              → compute net open positions per ticker
  scan_row_notes (active)  → active screening candidates
  news_article_tickers     → which tickers appear in recent articles
  news_impact_heads        → TICKER_SENTIMENT and TICKER_RELATIONSHIPS clusters
  news_articles            → title, url, published_at
  user_portfolio_alerts    → stop losses / take profits to watch
  scan_rows                → latest price data for alert proximity

Output
------
  Writes one row per (user_id, narrative_date) to daily_narratives.
  Each section item may include sources [{article_id, title, url, published_at}];
  market_pulse_sources lists articles backing the macro summary.
  Returns the structured dict that was saved.

Usage
-----
  python -m news_impact.narrative_generator --user-id <uuid>
  python -m news_impact.narrative_generator  # all opted-in users
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

from src.db import get_pg_connection, get_supabase_client, get_schema, _tbl
from news_impact.ollama_client import chat as ollama_chat, OllamaError

logger = logging.getLogger(__name__)

_EASTERN = ZoneInfo("America/New_York")
_DEFAULT_LOOKBACK_HOURS = 24
_OLLAMA_NARRATIVE_MODEL = os.environ.get("OLLAMA_NARRATIVE_MODEL") or os.environ.get("OLLAMA_IMPACT_MODEL", "devstral")
_OLLAMA_NARRATIVE_TOKENS = int(os.environ.get("OLLAMA_NARRATIVE_TOKENS", "3072"))
_OLLAMA_NARRATIVE_TIMEOUT = float(os.environ.get("OLLAMA_NARRATIVE_TIMEOUT", "180"))


# ── Data containers ───────────────────────────────────────────────────────────

@dataclass
class TickerNewsItem:
    article_id: int
    title: str
    url: str
    published_at: Optional[datetime]
    sentiment_score: float       # from TICKER_SENTIMENT head, scoped to this ticker
    sentiment_reason: str
    relationships: list[dict]    # [{from, to, type, notes}] from TICKER_RELATIONSHIPS head


@dataclass
class OpenPosition:
    ticker: str
    net_qty: float               # positive = long, negative = short
    avg_cost: Optional[float]    # weighted average entry price


@dataclass
class AlertItem:
    ticker: str
    alert_type: str              # stop_loss | take_profit | price_alert
    alert_price: float
    direction: str               # above | below
    notes: Optional[str]
    latest_price: Optional[float] = None
    pct_away: Optional[float] = None  # + means price is above alert, - means below


@dataclass
class UserContext:
    user_id: str
    narrative_date: date
    open_positions: list[OpenPosition] = field(default_factory=list)
    active_screen_tickers: list[str] = field(default_factory=list)
    portfolio_news: dict[str, list[TickerNewsItem]] = field(default_factory=dict)
    screening_news: dict[str, list[TickerNewsItem]] = field(default_factory=dict)
    alert_items: list[AlertItem] = field(default_factory=list)
    lookback_hours: int = _DEFAULT_LOOKBACK_HOURS


# ── DB queries ────────────────────────────────────────────────────────────────

def _fetch_open_positions(conn, user_id: str) -> list[OpenPosition]:
    """
    Compute net open position per ticker from user_trades.
    Net long  = SUM(buy×long qty) - SUM(sell×long qty)  > 0
    Net short = SUM(sell×short qty) - SUM(buy×short qty) > 0 (returned as negative)
    """
    schema = get_schema()
    sql = f"""
        SELECT
            ticker,
            SUM(
                CASE
                    WHEN side = 'buy'  AND position_side = 'long'  THEN  quantity
                    WHEN side = 'sell' AND position_side = 'long'  THEN -quantity
                    WHEN side = 'sell' AND position_side = 'short' THEN  quantity
                    WHEN side = 'buy'  AND position_side = 'short' THEN -quantity
                    ELSE 0
                END
            ) AS net_qty,
            SUM(
                CASE WHEN side = 'buy' THEN quantity * price_per_unit ELSE 0 END
            ) / NULLIF(SUM(CASE WHEN side = 'buy' THEN quantity ELSE 0 END), 0)
                AS avg_cost
        FROM {schema}.user_trades
        WHERE user_id = %s
        GROUP BY ticker
        HAVING SUM(
            CASE
                WHEN side = 'buy'  AND position_side = 'long'  THEN  quantity
                WHEN side = 'sell' AND position_side = 'long'  THEN -quantity
                WHEN side = 'sell' AND position_side = 'short' THEN  quantity
                WHEN side = 'buy'  AND position_side = 'short' THEN -quantity
                ELSE 0
            END
        ) != 0
        ORDER BY ticker
    """
    cur = conn.cursor()
    cur.execute(sql, (user_id,))
    rows = cur.fetchall() or []
    return [
        OpenPosition(ticker=r[0], net_qty=float(r[1]), avg_cost=float(r[2]) if r[2] else None)
        for r in rows
    ]


def _fetch_active_screen_tickers(conn, user_id: str) -> list[str]:
    """Return tickers the user has marked 'active' in their screening notes."""
    schema = get_schema()
    sql = f"""
        SELECT DISTINCT ticker
        FROM {schema}.user_scan_row_notes
        WHERE user_id = %s AND status = 'active'
        ORDER BY ticker
    """
    cur = conn.cursor()
    cur.execute(sql, (user_id,))
    return [r[0] for r in (cur.fetchall() or [])]


def _fetch_ticker_news(
    conn,
    tickers: list[str],
    lookback_hours: int,
) -> dict[str, list[TickerNewsItem]]:
    """
    For each ticker, find recent articles and the TICKER_SENTIMENT score.
    Also pulls TICKER_RELATIONSHIPS data for relationship insights.
    Returns {ticker: [TickerNewsItem, ...]}
    """
    if not tickers:
        return {}

    schema = get_schema()
    since = datetime.now(_EASTERN) - timedelta(hours=lookback_hours)

    # Fetch articles mentioning these tickers
    sql_articles = f"""
        SELECT
            nat.ticker,
            na.id            AS article_id,
            na.title,
            na.url,
            na.published_at
        FROM {schema}.news_article_tickers nat
        JOIN {schema}.news_articles na ON na.id = nat.article_id
        WHERE nat.ticker = ANY(%s)
          AND COALESCE(na.published_at, na.created_at) >= %s
        ORDER BY nat.ticker, COALESCE(na.published_at, na.created_at) DESC
    """
    cur = conn.cursor()
    cur.execute(sql_articles, (tickers, since))
    article_rows = cur.fetchall() or []

    # Collect unique article IDs to fetch heads in one query
    article_ids = list({r[1] for r in article_rows})
    if not article_ids:
        return {}

    # Fetch TICKER_SENTIMENT heads
    sql_sentiment = f"""
        SELECT article_id, scores_json, reasoning_json
        FROM {schema}.news_impact_heads
        WHERE article_id = ANY(%s)
          AND cluster = 'TICKER_SENTIMENT'
    """
    cur.execute(sql_sentiment, (article_ids,))
    sentiment_by_article: dict[int, tuple[dict, dict]] = {}
    for row in (cur.fetchall() or []):
        sentiment_by_article[row[0]] = (row[1] or {}, row[2] or {})

    # Fetch TICKER_RELATIONSHIPS heads
    sql_rel = f"""
        SELECT article_id, scores_json, reasoning_json
        FROM {schema}.news_impact_heads
        WHERE article_id = ANY(%s)
          AND cluster = 'TICKER_RELATIONSHIPS'
    """
    cur.execute(sql_rel, (article_ids,))
    relationships_by_article: dict[int, list[dict]] = {}
    for row in (cur.fetchall() or []):
        rel_scores = row[1] or {}
        rel_reasoning = row[2] or {}
        parsed = []
        for key, strength in rel_scores.items():
            parts = key.split("__")
            if len(parts) == 3:
                parsed.append({
                    "from": parts[0],
                    "to": parts[1],
                    "type": parts[2],
                    "strength": strength,
                    "notes": rel_reasoning.get(key, ""),
                })
        relationships_by_article[row[0]] = parsed

    # Build output grouped by ticker
    result: dict[str, list[TickerNewsItem]] = {t: [] for t in tickers}
    seen: set[tuple[str, int]] = set()

    for ticker, article_id, title, url, published_at in article_rows:
        key = (ticker, article_id)
        if key in seen:
            continue
        seen.add(key)

        scores, reasons = sentiment_by_article.get(article_id, ({}, {}))
        ticker_upper = ticker.upper()
        sentiment_score = float(scores.get(ticker_upper, 0.0))
        sentiment_reason = reasons.get(ticker_upper, "")

        # Filter relationships to ones involving this ticker
        all_rels = relationships_by_article.get(article_id, [])
        relevant_rels = [
            r for r in all_rels
            if r["from"] == ticker_upper or r["to"] == ticker_upper
        ]

        if ticker in result:
            result[ticker].append(TickerNewsItem(
                article_id=article_id,
                title=title or "",
                url=url or "",
                published_at=published_at,
                sentiment_score=sentiment_score,
                sentiment_reason=sentiment_reason,
                relationships=relevant_rels,
            ))

    return result


def _fetch_alert_items(conn, user_id: str) -> list[AlertItem]:
    """Load active alerts and try to enrich with latest price from scan_rows."""
    schema = get_schema()

    sql_alerts = f"""
        SELECT ticker, alert_type, price, direction, notes
        FROM {schema}.user_portfolio_alerts
        WHERE user_id = %s AND is_active = TRUE
        ORDER BY ticker, alert_type
    """
    cur = conn.cursor()
    cur.execute(sql_alerts, (user_id,))
    alert_rows = cur.fetchall() or []
    if not alert_rows:
        return []

    alert_tickers = list({r[0] for r in alert_rows})

    # Try to get latest price from the most recent scan_rows row_data
    sql_price = f"""
        SELECT DISTINCT ON (sr.symbol)
            sr.symbol,
            (sr.row_data->>'close')::numeric AS close_price
        FROM {schema}.user_scan_rows sr
        WHERE sr.user_id = %s
          AND sr.symbol = ANY(%s)
          AND sr.row_data ? 'close'
        ORDER BY sr.symbol, sr.scan_date DESC, sr.id DESC
    """
    cur.execute(sql_price, (user_id, alert_tickers))
    price_map: dict[str, float] = {}
    for r in (cur.fetchall() or []):
        if r[1] is not None:
            price_map[r[0]] = float(r[1])

    items: list[AlertItem] = []
    for ticker, alert_type, alert_price, direction, notes in alert_rows:
        latest = price_map.get(ticker)
        pct_away: Optional[float] = None
        if latest and float(alert_price) > 0:
            pct_away = round((latest - float(alert_price)) / float(alert_price) * 100, 2)
        items.append(AlertItem(
            ticker=ticker,
            alert_type=alert_type,
            alert_price=float(alert_price),
            direction=direction,
            notes=notes,
            latest_price=latest,
            pct_away=pct_away,
        ))
    return items


def _fetch_opted_in_users(conn) -> list[tuple[str, int]]:
    """
    Return (user_id, lookback_hours) for all users where
    narrative_preferences.is_enabled = TRUE.
    Falls back to all users who have trades or active notes if no preferences exist.
    """
    schema = get_schema()
    sql = f"""
        SELECT user_id, lookback_hours
        FROM {schema}.user_narrative_preferences
        WHERE is_enabled = TRUE
    """
    cur = conn.cursor()
    try:
        cur.execute(sql)
        rows = cur.fetchall() or []
    except Exception:
        conn.rollback()
        rows = []

    if rows:
        return [(str(r[0]), int(r[1])) for r in rows]

    # Fallback: users with any trades
    sql2 = f"""
        SELECT DISTINCT user_id FROM {schema}.user_trades
    """
    cur.execute(sql2)
    return [(str(r[0]), _DEFAULT_LOOKBACK_HOURS) for r in (cur.fetchall() or [])]


# ── Ollama narrative synthesis ────────────────────────────────────────────────

_NARRATIVE_SYSTEM = """\
You are a concise pre-market briefing assistant for a swing trader.
Your job: synthesise recent news and its impact on specific portfolio positions \
and screening candidates. Be direct and actionable. Avoid waffle. No markdown.
Return ONLY valid JSON as specified — no preamble, no explanation outside the JSON."""

_NARRATIVE_USER_TEMPLATE = """\
Date: {date} (US Eastern premarket)

=== PORTFOLIO POSITIONS ===
{portfolio_block}

=== ACTIVE SCREENING CANDIDATES ===
{screening_block}

=== RECENT NEWS HITS (last {lookback_hours}h) ===
Each line starts with article_id=... — cite these integer ids in "sources" and market_pulse_sources only.
{news_block}

=== ACTIVE ALERTS ===
{alerts_block}

Generate a daily narrative JSON with this exact structure:
{{
  "portfolio_watch": [
    {{
      "ticker": "AAPL",
      "sentiment": 0.65,
      "narrative": "One or two sentences on what happened and why it matters for this position.",
      "action": "monitor",
      "sources": [{{"article_id": 12345}}]
    }}
  ],
  "screening_update": [
    {{
      "ticker": "MSFT",
      "narrative": "One sentence on news impact for this setup candidate.",
      "sources": [{{"article_id": 67890}}]
    }}
  ],
  "alert_watch": [
    {{
      "ticker": "TSLA",
      "alert_type": "stop_loss",
      "alert_price": 220.0,
      "pct_away": -3.2,
      "narrative": "Approaching stop. Negative sentiment from earnings miss narrative.",
      "sources": [{{"article_id": 111}}]
    }}
  ],
  "market_pulse": "Two or three sentences summarising the key macro themes from today's news that affect these positions.",
  "market_pulse_sources": [12345, 67890]
}}

Rules:
- Only include tickers that appear in the news hits above. Skip tickers with no news.
- sentiment: -1.0 (very negative) to +1.0 (very positive) for this specific ticker.
- action: one of "monitor" | "review" | "urgent" (urgent = needs attention today).
- alert_watch: only include alerts where pct_away is within 5% of the trigger level.
- market_pulse: required even if brief.
- sources: for each portfolio_watch, screening_update, and alert_watch item, include "sources" as a JSON array of objects {{"article_id": <int>}} for every article you relied on. Use only article_id values that appear in the news hits block. Omit "sources" or use [] if none apply.
- market_pulse_sources: array of article_id integers drawn from the news hits that informed market_pulse; use [] if not article-specific.
- Return {{"portfolio_watch":[],"screening_update":[],"alert_watch":[],"market_pulse":"No significant news in the lookback window.","market_pulse_sources":[]}} if nothing relevant found.
"""


def _build_portfolio_block(positions: list[OpenPosition]) -> str:
    if not positions:
        return "  (no open positions)"
    lines = []
    for p in positions:
        side = "LONG" if p.net_qty > 0 else "SHORT"
        cost = f"avg cost ${p.avg_cost:.2f}" if p.avg_cost else "cost unknown"
        lines.append(f"  {p.ticker} {side} {abs(p.net_qty):.0f} shares, {cost}")
    return "\n".join(lines)


def _build_screening_block(tickers: list[str]) -> str:
    if not tickers:
        return "  (no active screening candidates)"
    return "\n".join(f"  {t}" for t in tickers)


def _build_news_block(
    portfolio_news: dict[str, list[TickerNewsItem]],
    screening_news: dict[str, list[TickerNewsItem]],
) -> str:
    combined: dict[str, list[TickerNewsItem]] = {}
    for t, items in {**portfolio_news, **screening_news}.items():
        combined.setdefault(t, []).extend(items)

    if not any(v for v in combined.values()):
        return "  (no news hits in the lookback window)"

    lines: list[str] = []
    for ticker, items in sorted(combined.items()):
        if not items:
            continue
        lines.append(f"\n  [{ticker}]")
        for item in items[:3]:  # cap at 3 articles per ticker to control token budget
            ts = item.published_at.strftime("%H:%M") if item.published_at else "?"
            score_str = f"{item.sentiment_score:+.2f}" if item.sentiment_score else " 0.00"
            lines.append(
                f"    article_id={item.article_id} | {ts} sentiment={score_str} | {item.title[:100]}"
            )
            if item.sentiment_reason:
                lines.append(f"           reason: {item.sentiment_reason[:120]}")
            for rel in item.relationships[:2]:
                lines.append(
                    f"           related: {rel['from']}→{rel['to']} ({rel['type']}) {rel['notes'][:80]}"
                )
    return "\n".join(lines) if lines else "  (no news hits)"


def _build_alerts_block(alerts: list[AlertItem]) -> str:
    if not alerts:
        return "  (no active alerts)"
    lines: list[str] = []
    for a in alerts:
        price_str = f"current=${a.latest_price:.2f}" if a.latest_price else "price unknown"
        away_str = f"{a.pct_away:+.1f}%" if a.pct_away is not None else "?"
        lines.append(
            f"  {a.ticker} {a.alert_type.upper()} @ ${a.alert_price:.2f} | {price_str} | {away_str} away"
        )
    return "\n".join(lines)


def _article_catalog_from_context(ctx: UserContext) -> dict[int, dict[str, Any]]:
    """Map article_id -> stable title/url for post-processing model citations."""
    cat: dict[int, dict[str, Any]] = {}
    for items in list(ctx.portfolio_news.values()) + list(ctx.screening_news.values()):
        for it in items:
            cat[it.article_id] = {
                "article_id": it.article_id,
                "title": it.title,
                "url": it.url,
                "published_at": it.published_at.isoformat() if it.published_at else None,
            }
    return cat


def _coerce_article_id(entry: Any) -> Optional[int]:
    if isinstance(entry, int):
        return entry
    if isinstance(entry, dict):
        v = entry.get("article_id")
        if v is None:
            return None
        try:
            return int(v)
        except (TypeError, ValueError):
            return None
    try:
        return int(entry)
    except (TypeError, ValueError):
        return None


def _enrich_narrative_sources(narrative: dict[str, Any], catalog: dict[int, dict[str, Any]]) -> None:
    """Replace model article_id citations with title/url from DB; drop unknown ids. Mutates narrative."""
    for section in ("portfolio_watch", "screening_update", "alert_watch"):
        for item in narrative.get(section) or []:
            if not isinstance(item, dict):
                continue
            raw = item.get("sources")
            if not isinstance(raw, list):
                item.pop("sources", None)
                continue
            enriched: list[dict[str, Any]] = []
            for ent in raw:
                aid = _coerce_article_id(ent)
                if aid is not None and aid in catalog:
                    enriched.append(dict(catalog[aid]))
            if enriched:
                item["sources"] = enriched
            else:
                item.pop("sources", None)

    mp = narrative.get("market_pulse_sources")
    if not isinstance(mp, list):
        narrative["market_pulse_sources"] = []
        return
    enriched_mp: list[dict[str, Any]] = []
    for ent in mp:
        aid = _coerce_article_id(ent)
        if aid is not None and aid in catalog:
            enriched_mp.append(dict(catalog[aid]))
    narrative["market_pulse_sources"] = enriched_mp


def _parse_narrative_json(raw: str) -> dict:
    """Best-effort JSON extraction from Ollama response."""
    import re
    # Strip markdown fences
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.MULTILINE).strip()
    # Find outermost { }
    start = raw.find("{")
    if start < 0:
        return {}
    depth, i, in_str, esc = 0, start, False, False
    while i < len(raw):
        c = raw[i]
        if in_str:
            esc = (not esc and c == "\\")
            if not esc and c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(raw[start: i + 1])
                except json.JSONDecodeError:
                    return {}
        i += 1
    return {}


async def _generate_narrative_text(ctx: UserContext) -> tuple[dict, int]:
    """
    Call Ollama with context; returns (parsed_narrative_dict, latency_ms).
    Falls back to an empty narrative structure on any error.
    """
    portfolio_block = _build_portfolio_block(ctx.open_positions)
    screening_block = _build_screening_block(ctx.active_screen_tickers)
    news_block = _build_news_block(ctx.portfolio_news, ctx.screening_news)
    alerts_block = _build_alerts_block(ctx.alert_items)

    prompt = _NARRATIVE_USER_TEMPLATE.format(
        date=ctx.narrative_date.strftime("%A %B %-d, %Y"),
        portfolio_block=portfolio_block,
        screening_block=screening_block,
        news_block=news_block,
        alerts_block=alerts_block,
        lookback_hours=ctx.lookback_hours,
    )

    t0 = time.monotonic()
    try:
        raw, latency_ms = await ollama_chat(
            prompt=prompt,
            system=_NARRATIVE_SYSTEM,
            model=_OLLAMA_NARRATIVE_MODEL,
            timeout=_OLLAMA_NARRATIVE_TIMEOUT,
        )
    except OllamaError as exc:
        logger.error("[narrative] Ollama error for user %s: %s", ctx.user_id, exc)
        return _empty_narrative(), 0

    parsed = _parse_narrative_json(raw)
    if not parsed:
        logger.warning("[narrative] could not parse Ollama response for user %s: %r", ctx.user_id, raw[:200])
        return _empty_narrative(), latency_ms

    catalog = _article_catalog_from_context(ctx)
    _enrich_narrative_sources(parsed, catalog)

    return parsed, latency_ms


def _empty_narrative() -> dict:
    return {
        "portfolio_watch": [],
        "screening_update": [],
        "alert_watch": [],
        "market_pulse": "Could not generate narrative. Check Ollama connectivity.",
        "market_pulse_sources": [],
    }


# ── Persistence ───────────────────────────────────────────────────────────────

def _save_narrative(
    client,
    user_id: str,
    narrative_date: date,
    portfolio_section: list,
    screening_section: list,
    alert_warnings: list,
    market_pulse: str,
    market_pulse_sources: list,
    model: str,
    latency_ms: int,
) -> None:
    """Upsert the daily narrative for this user+date."""
    schema = get_schema()
    row = {
        "user_id": user_id,
        "narrative_date": narrative_date.isoformat(),
        "portfolio_section": portfolio_section,
        "screening_section": screening_section,
        "alert_warnings": alert_warnings,
        "market_pulse": market_pulse,
        "market_pulse_sources": market_pulse_sources,
        "model": model,
        "latency_ms": latency_ms,
        "generated_at": datetime.now().isoformat(),
    }
    client.schema(schema).table("daily_narratives").upsert(
        row, on_conflict="user_id,narrative_date"
    ).execute()


# ── Main entry point ──────────────────────────────────────────────────────────

async def generate_for_user(user_id: str, narrative_date: Optional[date] = None, lookback_hours: int = _DEFAULT_LOOKBACK_HOURS) -> dict:
    """
    Generate and persist the daily narrative for one user.
    Returns the saved narrative dict.
    """
    if narrative_date is None:
        narrative_date = datetime.now(_EASTERN).date()

    logger.info("[narrative] generating for user=%s date=%s lookback=%dh", user_id, narrative_date, lookback_hours)
    conn = get_pg_connection()
    try:
        ctx = UserContext(
            user_id=user_id,
            narrative_date=narrative_date,
            lookback_hours=lookback_hours,
        )

        ctx.open_positions = _fetch_open_positions(conn, user_id)
        ctx.active_screen_tickers = _fetch_active_screen_tickers(conn, user_id)
        ctx.alert_items = _fetch_alert_items(conn, user_id)

        portfolio_tickers = [p.ticker for p in ctx.open_positions]
        all_tickers = list(dict.fromkeys(portfolio_tickers + ctx.active_screen_tickers))

        if all_tickers:
            news_map = _fetch_ticker_news(conn, all_tickers, lookback_hours)
            portfolio_set = set(portfolio_tickers)
            ctx.portfolio_news = {t: v for t, v in news_map.items() if t in portfolio_set}
            ctx.screening_news = {t: v for t, v in news_map.items() if t not in portfolio_set}
        else:
            logger.info("[narrative] user=%s has no positions or active screens", user_id)
    finally:
        conn.close()

    narrative, latency_ms = await _generate_narrative_text(ctx)

    client = get_supabase_client()
    _save_narrative(
        client=client,
        user_id=user_id,
        narrative_date=narrative_date,
        portfolio_section=narrative.get("portfolio_watch", []),
        screening_section=narrative.get("screening_update", []),
        alert_warnings=narrative.get("alert_watch", []),
        market_pulse=narrative.get("market_pulse", ""),
        market_pulse_sources=narrative.get("market_pulse_sources") or [],
        model=_OLLAMA_NARRATIVE_MODEL,
        latency_ms=latency_ms,
    )
    logger.info("[narrative] saved for user=%s date=%s latency=%dms", user_id, narrative_date, latency_ms)
    return narrative


async def generate_all() -> list[str]:
    """
    Generate narratives for all opted-in users (sequentially — Ollama is single-GPU).
    Returns list of user_ids processed.
    """
    conn = get_pg_connection()
    try:
        users = _fetch_opted_in_users(conn)
    finally:
        conn.close()

    if not users:
        logger.info("[narrative] no opted-in users found")
        return []

    processed: list[str] = []
    for user_id, lookback_hours in users:
        try:
            await generate_for_user(user_id, lookback_hours=lookback_hours)
            processed.append(user_id)
        except Exception as exc:
            logger.error("[narrative] failed for user=%s: %s", user_id, exc)
    return processed


if __name__ == "__main__":
    import argparse
    import pathlib
    from dotenv import load_dotenv

    load_dotenv(pathlib.Path(__file__).parent.parent / ".env")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Generate daily narrative")
    parser.add_argument("--user-id", help="Generate for a specific user UUID only")
    parser.add_argument("--lookback-hours", type=int, default=_DEFAULT_LOOKBACK_HOURS)
    args = parser.parse_args()

    if args.user_id:
        result = asyncio.run(generate_for_user(args.user_id, lookback_hours=args.lookback_hours))
        print(json.dumps(result, indent=2))
    else:
        processed = asyncio.run(generate_all())
        print(f"Generated narratives for {len(processed)} users: {processed}")
