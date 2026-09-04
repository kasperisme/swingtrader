"""
News search for the agent tools.

``search_news`` is a CASCADE, not a vector search — tag overlap first, ranked
full-text second. It mirrors the order the public /articles page uses
(app/api/news/semantic-search/route.ts), for two measured reasons:

  1. **Speed.** The embedding RPC is not viable as an agent tool. Measured on
     the live database, same corpus, same day:

         search_news_embeddings   39,993 ms   (and 60s timeouts under load)
         cascade (tags/FTS)          583 ms   average over 5 realistic queries

     The RPC is `LANGUAGE sql` + SECURITY DEFINER, so PostgreSQL cannot inline
     it and eventually plans it generically; without the parameter values it
     misjudges the `published_at` selectivity and picks a 17GB ivfflat scan over
     the btree. `search_news_fulltext` is `LANGUAGE plpgsql` and does not have
     that failure mode. See supabase/migrations/20260904180000_*.sql.

  2. **Point-in-time honesty.** The RPCs anchor their window at `NOW()`
     server-side, which silently hands a backtest tomorrow's news. With
     ``as_of`` set this module runs upper-bounded SQL instead, so a replayed
     session sees only what had actually been published. Verified: 0 of 60
     returned articles were published after the as-of date.

What this gives up is pure semantic recall — matching an article that shares no
words with the query. Full-text ORs the query's lexemes, so "catalyst" will not
find "surged on unexpected approval". That is a real loss and the reason
``semantic_search_news`` is still exported: it is the right tool for a human
typing into a search box, and the wrong one for an agent making 3 calls a
session against a 40-second latency.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, time as dtime, timedelta, timezone
from typing import Any, Optional

from shared.db import get_supabase_client

log = logging.getLogger(__name__)

#: Columns every path returns, so callers (and provenance) see one shape.
_COLUMNS = (
    "article_id", "title", "url", "source", "slug", "image_url",
    "article_stream", "published_at", "snippet", "similarity",
)


def _client():
    return get_supabase_client(), "swingtrader"


def _row(d: dict[str, Any]) -> dict[str, Any]:
    """Normalise one row to the shared shape."""
    return {
        "article_id": int(d["article_id"]) if d.get("article_id") is not None else None,
        "title": d.get("title") or "",
        "url": d.get("url") or "",
        "source": d.get("source") or "",
        "slug": d.get("slug") or "",
        "image_url": d.get("image_url") or "",
        "article_stream": d.get("article_stream") or "",
        "published_at": d.get("published_at"),
        "snippet": (d.get("snippet") or "")[:260],
        "similarity": float(d["similarity"]) if d.get("similarity") is not None else 0.0,
    }


# ── The public entry point ───────────────────────────────────────────────────


def search_news(
    query: str,
    *,
    lookback_hours: int = 24,
    tickers: Optional[list[str]] = None,
    article_stream: Optional[str] = None,
    limit: int = 12,
    as_of: "date | None" = None,
) -> list[dict[str, Any]]:
    """Search the news corpus: tag overlap when tickers are named, else full-text.

    ``as_of`` bounds the window's upper edge to the end of that day, for replay.
    Returns rows of {article_id, title, url, source, slug, image_url,
    article_stream, published_at, snippet, similarity}.
    """
    q = (query or "").strip()
    tickers = [t.strip().upper() for t in (tickers or []) if t and t.strip()]
    if not q and not tickers:
        return []
    limit = max(1, min(int(limit), 100))
    hours = max(1, int(lookback_hours))

    # Tickers are an exact, index-fast filter and the strongest signal the caller
    # can give — a named ticker beats guessing at its name inside prose. Only
    # when it returns nothing does the free-text path run, so a quiet ticker
    # still yields something rather than an empty result.
    rows: list[dict[str, Any]] = []
    if tickers:
        rows = _by_tags(tickers, hours, limit, article_stream, as_of)
    if not rows and q:
        rows = _by_fulltext(q, hours, limit, article_stream, as_of)
    return rows


def semantic_search_news(
    query: str,
    *,
    lookback_hours: int = 24,
    tickers: Optional[list[str]] = None,
    article_stream: Optional[str] = None,
    limit: int = 12,
    as_of: "date | None" = None,
) -> list[dict[str, Any]]:
    """Vector search via the embedding RPC — meaning-level recall, higher latency.

    Honours ``as_of`` (migration 20260904190000 onward), so unlike before it is
    usable in a replay. Still the slower path: prefer ``search_news`` unless the
    query genuinely needs to match articles that share no words with it.
    """
    from services.news.embeddings.semantic_retrieval import search_news_embeddings
    return [
        _row(r)
        for r in search_news_embeddings(
            query,
            lookback_hours=lookback_hours,
            tickers=tickers,
            article_stream=article_stream,
            limit=limit,
            as_of=as_of,
        )
    ]


def embed_query(text: str, model: Optional[str] = None) -> list[float]:
    """Embed a query string via Ollama (mxbai-embed-large)."""
    from services.news.embeddings.semantic_retrieval import embed_query as _embed
    return _embed(text, model=model)


# ── Tag overlap ──────────────────────────────────────────────────────────────


def _by_tags(
    tickers: list[str], hours: int, limit: int,
    article_stream: Optional[str], as_of: "date | None",
) -> list[dict[str, Any]]:
    if as_of is not None:
        return _sql_window(
            "a.search_tags && %(tags)s::text[]",
            {"tags": tickers}, hours, limit, article_stream, as_of, rank=None,
        )
    client, schema = _client()
    try:
        res = client.schema(schema).rpc("search_news_by_tags", {
            "tag_filter": tickers,
            "match_count": limit,
            "lookback_hours": hours,
            "stream_filter": article_stream,
        }).execute()
    except Exception as exc:
        log.warning("search_news: tag path failed (%s); falling through", exc)
        return []
    return [_row(r) for r in (res.data or [])]


# ── Ranked full text ─────────────────────────────────────────────────────────


def _by_fulltext(
    query: str, hours: int, limit: int,
    article_stream: Optional[str], as_of: "date | None",
) -> list[dict[str, Any]]:
    if as_of is not None:
        return _sql_window(
            "a.fts @@ ts.q", {}, hours, limit, article_stream, as_of, rank=query,
        )
    client, schema = _client()
    try:
        res = client.schema(schema).rpc("search_news_fulltext", {
            "query_text": query,
            "match_count": limit,
            "lookback_hours": hours,
            "stream_filter": article_stream,
        }).execute()
    except Exception as exc:
        log.warning("search_news: fulltext path failed (%s)", exc)
        return []
    return [_row(r) for r in (res.data or [])]


# ── The as-of path ───────────────────────────────────────────────────────────
#
# The RPCs cannot be reused here: both anchor at NOW() server-side, and there is
# no parameter to move that edge. Rather than add an as-of argument to two
# SECURITY DEFINER functions on a live database, the replay path runs the same
# query shape directly with both edges bound. It is only reached in a backtest.


def _sql_window(
    predicate: str, params: dict[str, Any], hours: int, limit: int,
    article_stream: Optional[str], as_of: date, rank: Optional[str],
) -> list[dict[str, Any]]:
    """Run the tag or full-text query with BOTH window edges bound to ``as_of``."""
    from shared.db import get_pg_connection

    end = datetime.combine(as_of, dtime.max, tzinfo=timezone.utc)
    start = end - timedelta(hours=hours)

    # `ts` is a one-row CTE so the tsquery is built once; for the tag path it is
    # unused but harmless, which keeps a single SQL shape for both branches.
    sql = f"""
    WITH ts AS (
      SELECT CASE WHEN %(rank)s IS NULL THEN NULL::tsquery
                  ELSE to_tsquery('english',
                       (SELECT string_agg(lexeme, ' | ')
                        FROM unnest(to_tsvector('english', %(rank)s)))) END AS q
    ),
    cand AS (
      SELECT a.id
      FROM swingtrader.news_articles a, ts
      WHERE {predicate}
        AND a.published_at <= %(end)s
        AND a.published_at >= %(start)s
        AND (%(stream)s::text IS NULL OR a.article_stream = %(stream)s::text)
      ORDER BY a.published_at DESC NULLS LAST, a.id DESC
      LIMIT 2000
    )
    SELECT a.id, a.title, a.url, a.source, a.slug, a.image_url,
           a.article_stream, a.published_at, left(a.body, 280),
           CASE WHEN ts.q IS NULL THEN 1.0::float8
                ELSE ts_rank_cd(a.fts, ts.q)::float8 END AS similarity
    FROM cand JOIN swingtrader.news_articles a ON a.id = cand.id, ts
    ORDER BY similarity DESC, a.published_at DESC NULLS LAST, a.id DESC
    LIMIT %(lim)s
    """
    args = {"end": end, "start": start, "lim": limit,
            "stream": article_stream, "rank": rank, **params}
    try:
        with get_pg_connection() as conn, conn.cursor() as cur:
            cur.execute("SET statement_timeout = '20s'")
            cur.execute(sql, args)
            rows = cur.fetchall()
    except Exception as exc:
        log.warning("search_news: as-of path failed (%s)", exc)
        return []
    return [_row(dict(zip(_COLUMNS, r))) for r in rows]
