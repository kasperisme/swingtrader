"""
News article retrieval — top articles, ticker news, ticker-article mapping.

Consolidates:
  - services/agent/data_queries.get_top_articles
  - services/agent/data_queries.get_ticker_news
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from datetime import date, datetime, time as dtime, timedelta, timezone
from typing import Any

from shared.db import get_supabase_client, _as_json

log = logging.getLogger(__name__)


def _client():
    return get_supabase_client(), "swingtrader"


# ── Tag search (mirror of the /articles?tag= path) ───────────────────────────
#
# The public articles page filters by tag through the search_news_by_tags RPC,
# expanding each token into its plausible stored forms first. We replicate the
# UI's lib/news/search-tags.ts expansion exactly so the agent's tag search
# returns the same rows the website does for the same tag.

_TICKER_RE = re.compile(r"^[A-Za-z]{1,6}$")


def _slugify_theme_tag(raw: str) -> str:
    """Lowercase snake_case theme slug (mirror of slugifyThemeTag)."""
    s = re.sub(r"[^a-z0-9]+", "_", str(raw or "").lower())
    return s.strip("_")[:48]


def expand_search_tag_candidates(raw: str) -> list[str]:
    """Expand one token into every plausible stored tag form.

    Mirror of lib/news/search-tags.ts:expandSearchTagCandidates — a short token
    could be stored as a lowercase theme slug or an uppercase ticker, so emit
    both (e.g. "SPCX" -> ["spcx", "SPCX"], "japan" -> ["japan", "JAPAN"]). The
    GIN overlap in search_news_by_tags then matches whichever the article holds.
    """
    t = str(raw or "").strip()
    if not t:
        return []
    out: list[str] = []
    slug = _slugify_theme_tag(t)
    if slug:
        out.append(slug)
    if _TICKER_RE.match(t):
        upper = t.upper()
        if upper not in out:
            out.append(upper)
    return out


def get_news_by_tag(
    tags: list[str],
    hours: int = 720,
    limit: int = 20,
    article_stream: str | None = None,
) -> list[dict[str, Any]]:
    """Latest articles carrying any of the given tags, newest first.

    The exact search the /articles?tag=X feed uses: each tag is expanded into
    its stored forms and matched against news_articles.search_tags via the
    GIN-indexed search_news_by_tags RPC. Returns:
    {article_id, title, url, source, slug, image_url, article_stream,
     published_at, snippet, similarity}.
    """
    client, schema = _client()
    seen: set[str] = set()
    expanded: list[str] = []
    for tag in tags or []:
        for cand in expand_search_tag_candidates(tag):
            if cand not in seen:
                seen.add(cand)
                expanded.append(cand)
    if not expanded:
        return []

    res = (
        client.schema(schema)
        .rpc(
            "search_news_by_tags",
            {
                "tag_filter": expanded,
                "match_count": max(1, min(int(limit), 100)),
                "lookback_hours": max(0, int(hours)),
                "stream_filter": article_stream,
            },
        )
        .execute()
    )
    return res.data or []


def get_top_articles(
    tickers: list[str] | None = None,
    hours: int = 14,
    limit: int = 10,
    as_of: "date | None" = None,
) -> list[dict[str, Any]]:
    """Top-scored articles sorted by impact magnitude.

    Returns: title, url, source, published_at, impact_json, top_dimensions, magnitude.

    ``as_of`` replays a past session: the window is anchored to that date and
    bounded above by it, on ``published_at`` rather than ``created_at``. The
    corpus has been backfilled, so publication time is what was knowable at the
    time; ingestion time is an artifact of our own pipeline.
    """
    client, schema = _client()

    if as_of is None:
        since_iso = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        time_col, upper_iso = "created_at", None
    else:
        end = datetime.combine(as_of, dtime.max, tzinfo=timezone.utc)
        since_iso = (end - timedelta(hours=hours)).isoformat()
        time_col, upper_iso = "published_at", end.isoformat()

    q = (
        client.schema(schema)
        .table("news_articles")
        .select("id, title, url, source, created_at, published_at")
        .gte(time_col, since_iso)
        .order(time_col, desc=True)
        .limit(limit * 3)
    )
    if upper_iso:
        q = q.lte(time_col, upper_iso)

    if tickers:
        tick_res = (
            client.schema(schema)
            .table("news_article_tickers")
            .select("article_id")
            .in_("ticker", [t.upper() for t in tickers])
            .execute()
        )
        article_ids = list({r["article_id"] for r in (tick_res.data or [])})
        if not article_ids:
            return []
        q = q.in_("id", article_ids)

    articles = q.execute().data or []
    if not articles:
        return []

    ids = [a["id"] for a in articles]
    vec_res = (
        client.schema(schema)
        .table("news_impact_vectors")
        .select("article_id, impact_json, top_dimensions")
        .in_("article_id", ids)
        .execute()
    )
    vecs = {v["article_id"]: v for v in (vec_res.data or [])}

    out = []
    for a in articles:
        v = vecs.get(a["id"])
        if not v:
            continue
        impact = _as_json(v["impact_json"], default={})
        magnitude = sum(abs(val) for val in impact.values() if isinstance(val, (int, float)))
        out.append({
            **a,
            "impact_json": impact,
            "top_dimensions": _as_json(v["top_dimensions"], default=[]),
            "magnitude": magnitude,
        })

    out.sort(key=lambda x: x["magnitude"], reverse=True)
    return out[:limit]


def fetch_tickers_for_articles(article_ids: list[int]) -> dict[int, list[str]]:
    """Map article IDs → list of associated ticker symbols."""
    if not article_ids:
        return {}
    client, schema = _client()
    res = (
        client.schema(schema)
        .table("news_article_tickers")
        .select("article_id, ticker")
        .in_("article_id", article_ids)
        .execute()
    )
    out: dict[int, list[str]] = {}
    for row in (res.data or []):
        out.setdefault(row["article_id"], []).append(row["ticker"])
    return out


def _ticker_articles_as_of(
    client, schema: str, tickers: list[str], *, hours: int,
    per_ticker_limit: int, as_of: "date",
) -> list[tuple[str, int, str, str, str | None]]:
    """Per-ticker articles published within ``hours`` of the end of ``as_of``.

    Runs as one indexed join in Postgres rather than over PostgREST. Fetching
    the ticker links first would pull every article ever associated with a
    mega-cap and then need thousands of ids in an IN clause; the date bound has
    to be applied in the same query as the join, not after it.
    """
    end_ts = datetime.combine(as_of, dtime.max, tzinfo=timezone.utc)
    start_ts = end_ts - timedelta(hours=max(hours, 24))

    sql = f"""
        SELECT ticker, article_id, title, url, published_at
        FROM (
            SELECT t.ticker,
                   a.id AS article_id,
                   a.title,
                   a.url,
                   a.published_at,
                   ROW_NUMBER() OVER (
                       PARTITION BY t.ticker ORDER BY a.published_at DESC
                   ) AS rn
            FROM {schema}.news_article_tickers t
            JOIN {schema}.news_articles a ON a.id = t.article_id
            WHERE t.ticker = ANY(%(tickers)s)
              AND a.published_at >= %(start)s
              AND a.published_at <= %(end)s
        ) ranked
        WHERE rn <= %(per_ticker)s
        ORDER BY published_at DESC
    """
    from shared.db import get_pg_connection

    conn = get_pg_connection()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(sql, {
                "tickers": tickers,
                "start": start_ts,
                "end": end_ts,
                "per_ticker": per_ticker_limit,
            })
            rows = cur.fetchall()
    finally:
        conn.close()

    return [
        (str(r[0]).upper().strip(), int(r[1]), r[2] or "", r[3] or "",
         r[4].isoformat() if hasattr(r[4], "isoformat") else r[4])
        for r in rows
    ]


def _bound_by_as_of(
    rows: list[dict[str, Any]], as_of: "date | None", key: str = "published_at"
) -> list[dict[str, Any]]:
    """Drop anything published after a replayed session.

    Post-filtering can only REMOVE rows, never invent them, so the worst case is
    a thin result rather than a leaked one — which is the correct direction to
    fail in.
    """
    if as_of is None:
        return rows
    cutoff = as_of.isoformat()
    return [r for r in rows if str(r.get(key) or "")[:10] <= cutoff]


def get_ticker_news(
    tickers: list[str],
    hours: int = 24,
    per_ticker_limit: int = 5,
    as_of: "date | None" = None,
) -> list[dict[str, Any]]:
    """Per-ticker articles with sentiment scores and relationship annotations.

    Uses get_relationship_node_news RPC (alias resolution + direct mentions)
    then enriches with TICKER_SENTIMENT and TICKER_RELATIONSHIPS heads.

    Returns: ticker, article_id, title, url, published_at,
             sentiment_score, sentiment_reason, relationships.
    """
    if not tickers:
        return []
    normalized = list(dict.fromkeys(t.upper().strip() for t in tickers if t and t.strip()))
    if not normalized:
        return []

    client, schema = _client()
    days_lookback = max(1, -(-hours // 24))
    # The RPC anchors its lookback at now() server-side, so a replay has to
    # reach BACK far enough to cover the session and then discard anything
    # published after it. Widening changes which rows the RPC ranks highest, so
    # this is a faithful bound on the content, not a faithful reconstruction of
    # the ordering — noted in the arena README.
    article_rows: list[tuple[str, int, str, str, str | None]] = []
    seen_ids: set[tuple[str, int]] = set()

    if as_of is not None:
        # Replay path: query the tables directly.
        #
        # `get_relationship_node_news` anchors its lookback at now() AND caps at
        # 30 rows per call server-side, always the newest. For a session two
        # months back there is no combination of page and lookback that reaches
        # it — the window is simply not addressable through the RPC. So the
        # replay reads `news_article_tickers` -> `news_articles` bounded by
        # published_at instead.
        #
        # The cost is alias resolution: the RPC maps aliases to a canonical
        # ticker, and this path matches the symbol as stored. Direct mentions
        # are covered; an article that names only a subsidiary is not.
        article_rows = _ticker_articles_as_of(
            client, schema, normalized, hours=hours,
            per_ticker_limit=per_ticker_limit, as_of=as_of,
        )
        seen_ids = {(r[0], r[1]) for r in article_rows}
    else:
        for ticker in normalized:
            res = client.schema(schema).rpc("get_relationship_node_news", {
                "p_ticker": ticker,
                "p_page": 1,
                "p_page_size": per_ticker_limit,
                "p_days_lookback": days_lookback,
            }).execute()
            for r in (res.data or []):
                canonical = (r.get("canonical_ticker") or ticker).upper().strip()
                article_id = int(r["article_id"])
                key = (canonical, article_id)
                if key in seen_ids:
                    continue
                seen_ids.add(key)
                article_rows.append((
                    canonical, article_id,
                    r.get("title") or "", r.get("url") or "",
                    r.get("published_at"),
                ))

    if not article_rows:
        return []

    article_ids = list({r[1] for r in article_rows})
    heads_res = (
        client.schema(schema)
        .table("news_impact_heads")
        .select("article_id,cluster,scores_json,reasoning_json")
        .in_("article_id", article_ids)
        .in_("cluster", ["TICKER_SENTIMENT", "TICKER_RELATIONSHIPS"])
        .execute()
    )

    sentiment_by_article: dict[int, tuple[dict, dict]] = {}
    relationships_by_article: dict[int, list[dict]] = {}
    for r in (heads_res.data or []):
        aid = int(r["article_id"])
        scores = _as_json(r["scores_json"], {})
        reasoning = _as_json(r["reasoning_json"], {})
        if r["cluster"] == "TICKER_SENTIMENT":
            sentiment_by_article[aid] = (scores, reasoning)
        elif r["cluster"] == "TICKER_RELATIONSHIPS":
            parsed = []
            for key, strength in scores.items():
                parts = str(key).split("__")
                if len(parts) == 3:
                    parsed.append({
                        "from": parts[0], "to": parts[1], "type": parts[2],
                        "strength": strength, "notes": reasoning.get(key, ""),
                    })
            relationships_by_article[aid] = parsed

    out: list[dict[str, Any]] = []
    for canonical, article_id, title, url, published_at in article_rows:
        scores, reasons = sentiment_by_article.get(article_id, ({}, {}))
        sentiment_score = float(scores.get(canonical) or 0.0)
        sentiment_reason = str(reasons.get(canonical) or "")
        all_rels = relationships_by_article.get(article_id, [])
        relevant_rels = [r for r in all_rels if r["from"] == canonical or r["to"] == canonical]
        out.append({
            "ticker": canonical,
            "article_id": article_id,
            "title": title,
            "url": url,
            "published_at": published_at,
            "sentiment_score": sentiment_score,
            "sentiment_reason": sentiment_reason,
            "relationships": relevant_rels,
        })

    per_ticker: dict[str, list] = {}
    for item in out:
        per_ticker.setdefault(item["ticker"], []).append(item)

    flat: list[dict[str, Any]] = []
    for t in normalized:
        items = per_ticker.get(t, [])
        items.sort(key=lambda x: x.get("published_at") or "", reverse=True)
        flat.extend(items[:per_ticker_limit])
    return flat
