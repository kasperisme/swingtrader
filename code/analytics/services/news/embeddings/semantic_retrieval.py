from __future__ import annotations

import logging
import os
import threading
import time
from datetime import date, datetime, time as dtime, timezone
from typing import Optional

import httpx

from shared.db import get_supabase_client

logger = logging.getLogger(__name__)

_DEFAULT_OLLAMA_BASE = "http://localhost:11434"
_DEFAULT_EMBED_MODEL = "mxbai-embed-large"
_MXBAI_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

# ── Timing ───────────────────────────────────────────────────────────────────
#
# A semantic search is two very different waits stacked on top of each other:
# the LOCAL Ollama embed (`/api/embed`) and the REMOTE Postgres RPC. They fail
# and slow down for unrelated reasons, so a single "search took 8s" number is
# not actionable — it does not say whether to look at the GPU box or the
# database. These are measured apart and reported apart.
#
# Cheap enough to leave on permanently: two `perf_counter` reads per call.

_STATS_LOCK = threading.Lock()
_STATS: dict[str, dict[str, float]] = {}

#: Log a single call at WARNING when it blows past this. The embed is a local
#: model round-trip that should be tens of milliseconds; a second means the
#: model is being re-loaded (keep_alive expired) or is contending for the GPU.
_SLOW_EMBED_MS = 1_000.0
_SLOW_RPC_MS = 5_000.0


def _record(stage: str, ms: float, *, failed: bool = False) -> None:
    with _STATS_LOCK:
        s = _STATS.setdefault(stage, {"n": 0.0, "ms": 0.0, "max_ms": 0.0, "errors": 0.0})
        s["n"] += 1
        s["ms"] += ms
        s["max_ms"] = max(s["max_ms"], ms)
        if failed:
            s["errors"] += 1


def search_timings() -> dict[str, dict[str, float]]:
    """Snapshot of {stage: {n, ms, max_ms, errors, avg_ms}} since the last reset."""
    with _STATS_LOCK:
        out = {}
        for stage, s in _STATS.items():
            d = dict(s)
            d["avg_ms"] = (s["ms"] / s["n"]) if s["n"] else 0.0
            out[stage] = d
        return out


def reset_search_timings() -> None:
    with _STATS_LOCK:
        _STATS.clear()


def format_search_timings(stats: Optional[dict[str, dict[str, float]]] = None) -> str:
    """One-line human summary, e.g. `embed 14x avg 41ms max 190ms | rpc 14x ...`."""
    stats = search_timings() if stats is None else stats
    if not stats:
        return "no semantic searches"
    parts = []
    for stage in sorted(stats):
        s = stats[stage]
        err = f" err {int(s['errors'])}" if s.get("errors") else ""
        parts.append(
            f"{stage} {int(s['n'])}x avg {s['avg_ms']:.0f}ms max {s['max_ms']:.0f}ms{err}"
        )
    return " | ".join(parts)


def embed_query(text: str, model: Optional[str] = None, timeout: float = 30.0) -> list[float]:
    q = (text or "").strip()
    if not q:
        return []
    base = os.environ.get("OLLAMA_BASE_URL", _DEFAULT_OLLAMA_BASE).rstrip("/")
    embed_model = (model or os.environ.get("OLLAMA_EMBED_MODEL") or _DEFAULT_EMBED_MODEL).strip()
    input_text = _MXBAI_QUERY_PREFIX + q
    t0 = time.perf_counter()
    failed = True
    try:
        with httpx.Client(timeout=timeout) as client:
            r = client.post(f"{base}/api/embed", json={"model": embed_model, "input": [input_text]})
            if r.status_code == 404:
                r = client.post(f"{base}/api/embeddings", json={"model": embed_model, "prompt": input_text})
                r.raise_for_status()
                d = r.json()
                emb = d.get("embedding")
                if not isinstance(emb, list):
                    return []
                failed = False
                return [float(x) for x in emb]
            r.raise_for_status()
            d = r.json()
            embs = d.get("embeddings")
            if not isinstance(embs, list) or not embs or not isinstance(embs[0], list):
                return []
            failed = False
            return [float(x) for x in embs[0]]
    finally:
        ms = (time.perf_counter() - t0) * 1000.0
        _record("embed", ms, failed=failed)
        # WARNING not DEBUG: a slow local embed is never normal, and the whole
        # point of measuring is that this shows up without re-running anything.
        if ms >= _SLOW_EMBED_MS:
            logger.warning(
                "embed_query SLOW: %.0fms (model=%s base=%s chars=%d)",
                ms, embed_model, base, len(input_text),
            )
        else:
            logger.debug("embed_query %.0fms (model=%s)", ms, embed_model)


def _as_of_bound(as_of: "datetime | date") -> str:
    """The inclusive upper edge of a replayed session, as an ISO timestamp.

    A bare date means the END of that day: a session dated 2026-08-15 may read
    anything published on the 15th, and nothing from the 16th.
    """
    if isinstance(as_of, datetime):
        dt = as_of if as_of.tzinfo else as_of.replace(tzinfo=timezone.utc)
    else:
        dt = datetime.combine(as_of, dtime.max, tzinfo=timezone.utc)
    return dt.isoformat()


def search_news_embeddings(
    query: str,
    *,
    lookback_hours: int = 24,
    tickers: Optional[list[str]] = None,
    article_stream: Optional[str] = None,
    limit: int = 12,
    as_of: "datetime | date | None" = None,
) -> list[dict]:
    """
    Search news_article_embeddings via the swingtrader.search_news_embeddings()
    SQL function (HNSW + oversample/post-filter). Returns a list of dicts with
    article_id, title, url, published_at, snippet, similarity, article_stream.
    """
    qvec = embed_query(query)
    if not qvec:
        return []
    client = get_supabase_client()
    t0 = time.perf_counter()
    failed = True
    try:
        payload = {
            "query_embedding": qvec,
            "match_count": limit,
            "lookback_hours": lookback_hours,
            "stream_filter": article_stream,
            "ticker_filter": [t.upper() for t in tickers] if tickers else None,
        }
        # Sent ONLY when set. The `as_of` parameter exists in the function from
        # migration 20260904190000 onward; omitting the key when it is None
        # keeps this working against a database where that has not been applied
        # yet, instead of failing with "function does not exist".
        if as_of is not None:
            payload["as_of"] = _as_of_bound(as_of)
        res = client.schema("swingtrader").rpc("search_news_embeddings", payload).execute()
        failed = False
    finally:
        ms = (time.perf_counter() - t0) * 1000.0
        _record("rpc", ms, failed=failed)
        # `lookback_hours` is the dominant cost term — it sets how many vectors
        # the RPC has to rank — so it is logged with the timing or the number
        # cannot be interpreted.
        if ms >= _SLOW_RPC_MS:
            logger.warning(
                "search_news_embeddings SLOW: %.0fms (lookback=%dh limit=%d tickers=%s)",
                ms, lookback_hours, limit, len(tickers or []) or None,
            )
        else:
            logger.debug(
                "search_news_embeddings %.0fms (lookback=%dh)", ms, lookback_hours
            )
    return [
        {
            "article_id": int(r["article_id"]),
            "title": r["title"] or "",
            "url": r["url"] or "",
            "published_at": r["published_at"],
            "snippet": (r["snippet"] or "")[:260],
            "similarity": float(r["similarity"]) if r["similarity"] is not None else 0.0,
            "article_stream": r["article_stream"] or "",
        }
        for r in (res.data or [])
    ]
