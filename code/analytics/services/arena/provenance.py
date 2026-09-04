"""
Provenance — turn an agent's tool calls into links a reader can follow.

Recording that an agent "called get_screening_results" is trivia. Recording that
it **read the NIS Momentum board, and here it is**, is a claim the reader can
check. This module turns the raw (tool, arguments, result) stream of a decision
into a list of platform resources with real URLs:

    {kind: "screening", key: "nis-momentum",
     label: "NIS Momentum", href: "/marketscreenings/nis-momentum",
     detail: "12 symbols passed"}

Which means the arena stops being a closed box bolted onto the side of the site
and starts being the thing that demonstrates the rest of it: every decision
points at the screening, the quote page, the article that produced it.

Two rules kept throughout:

  - **Never invent a link.** A resource is emitted only when the tool call or its
    result actually names the thing. Article slugs are resolved against
    `news_articles` rather than guessed from a title, and an id that does not
    resolve is dropped rather than linked to a 404.
  - **Cap everything.** An agent that reads 60 articles produces a decision card
    nobody scrolls. Caps are per kind and the counts are kept, so the UI can say
    "and 47 more" honestly.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Iterable, Optional

from shared.db import get_supabase_client

log = logging.getLogger(__name__)

#: A single tool call slower than this is called out in the log as it happens.
_SLOW_TOOL_MS = 10_000.0

#: Per-kind caps on what gets stored for one decision.
_MAX_PER_KIND = {"ticker": 12, "article": 8, "screening": 6, "topic": 6}


# ── Recording ────────────────────────────────────────────────────────────────


class ToolCallRecorder:
    """Wraps a tool fn and records every call's arguments and result.

    The registry is built once per decision, so one recorder instance follows
    one agent through one session.
    """

    __slots__ = ("fn", "name", "calls")

    def __init__(self, name: str, fn: Any, calls: list[dict[str, Any]]) -> None:
        self.name = name
        self.fn = fn
        self.calls = calls

    def __call__(self, **kwargs: Any) -> Any:
        # Wall time per call. A decision that takes 6 minutes is not debuggable
        # from a total: the answer is always "which tool", and without this the
        # only way to find out is to re-run with a profiler attached.
        t0 = time.perf_counter()
        try:
            result = self.fn(**kwargs)
        finally:
            ms = (time.perf_counter() - t0) * 1000.0
        # The result is kept only long enough to derive resources from it, then
        # dropped — decision rows must not become a second copy of the corpus.
        self.calls.append(
            {"name": self.name, "args": kwargs, "result": result, "ms": ms}
        )
        if ms >= _SLOW_TOOL_MS:
            log.warning("arena: tool %s took %.1fs", self.name, ms / 1000.0)
        return result


def wrap_registry(registry: Any, calls: list[dict[str, Any]]) -> Any:
    """Return ``registry`` with every tool wrapped in a recorder."""
    from services.agent_core import Tool

    for name in list(registry.names()):
        tool = registry.get(name)
        if tool is None:
            continue
        registry.add(
            Tool(name=name, schema=tool.schema, fn=ToolCallRecorder(name, tool.fn, calls))
        )
    return registry


# ── Derivation ───────────────────────────────────────────────────────────────


def _as_list(v: Any) -> list[str]:
    if v is None:
        return []
    if isinstance(v, str):
        return [v]
    if isinstance(v, (list, tuple, set)):
        return [str(x) for x in v]
    return []


def _tickers_from_result(result: Any, keys: Iterable[str]) -> list[str]:
    """Pull ticker-ish values out of a tool result of unknown shape."""
    out: list[str] = []
    rows = result if isinstance(result, list) else [result] if isinstance(result, dict) else []
    for row in rows:
        if not isinstance(row, dict):
            continue
        for k in keys:
            v = row.get(k)
            if isinstance(v, str) and v:
                out.append(v)
        # Nested collections (get_pair_signals -> {"pairs": [...]}) etc.
        for v in row.values():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                out.extend(_tickers_from_result(v, keys))
    return out


def _article_ids(result: Any) -> list[int]:
    out: list[int] = []
    rows = result if isinstance(result, list) else []
    for row in rows:
        if not isinstance(row, dict):
            continue
        for key in ("id", "article_id"):
            v = row.get(key)
            if isinstance(v, int):
                out.append(v)
                break
    return out


_TICKER_KEYS = ("ticker", "symbol", "ticker_a", "ticker_b")


def derive(calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Turn a decision's recorded tool calls into linkable resources."""
    tickers: dict[str, str] = {}       # TICKER -> why it was looked at
    screenings: dict[str, None] = {}
    topics: dict[str, None] = {}
    article_ids: list[int] = []

    for call in calls:
        name, args, result = call["name"], call.get("args") or {}, call.get("result")

        # -- the screening boards -------------------------------------------
        if name == "get_screening_results":
            slug = str(args.get("screening_slug") or "nis-momentum")
            if isinstance(result, dict) and not result.get("error"):
                screenings.setdefault(slug, None)
                for row in result.get("rows") or []:
                    sym = row.get("symbol")
                    if sym:
                        tickers.setdefault(str(sym).upper(), "on the screen")

        # -- the priced-in decomposition ------------------------------------
        elif name in (
            "get_priced_in", "get_priced_in_drivers", "get_priced_in_case",
            "search_priced_in_drivers",
        ):
            for t in _as_list(args.get("tickers")) + _as_list(args.get("ticker")):
                tickers.setdefault(t.upper(), "priced-in decomposition")
            for t in _tickers_from_result(result, _TICKER_KEYS):
                tickers.setdefault(t.upper(), "priced-in decomposition")

        # -- the relationship graph -----------------------------------------
        elif name == "get_ticker_relationships":
            seed = args.get("ticker")
            if seed:
                tickers.setdefault(str(seed).upper(), "graph seed")
            for t in _tickers_from_result(
                (result or {}).get("nodes") if isinstance(result, dict) else None,
                _TICKER_KEYS,
            ):
                tickers.setdefault(t.upper(), "graph neighbour")

        # -- pairs -----------------------------------------------------------
        elif name == "get_pair_signals":
            for t in _tickers_from_result(result, _TICKER_KEYS):
                tickers.setdefault(t.upper(), "pair leg")

        # -- attention / sentiment / fundamentals ----------------------------
        elif name in ("get_trending_tickers", "get_ticker_sentiment", "get_company_vectors"):
            for t in _as_list(args.get("tickers")):
                tickers.setdefault(t.upper(), "looked up")
            for t in _tickers_from_result(result, _TICKER_KEYS):
                tickers.setdefault(t.upper(), "trending")

        # -- articles ---------------------------------------------------------
        elif name in ("get_top_articles", "get_ticker_news", "search_news", "get_news_by_tag"):
            for t in _as_list(args.get("tickers")):
                tickers.setdefault(t.upper(), "news lookup")
            article_ids.extend(_article_ids(result))
            tag = args.get("tag")
            if tag:
                topics.setdefault(str(tag), None)

    resources: list[dict[str, Any]] = []
    resources += _screening_resources(list(screenings))
    resources += _article_resources(article_ids)
    resources += _ticker_resources(tickers)
    resources += _topic_resources(list(topics))
    return resources


# ── Resolvers (each returns rows that are safe to render as links) ───────────


def _sb():
    return get_supabase_client().schema("swingtrader")


def _screening_resources(slugs: list[str]) -> list[dict[str, Any]]:
    slugs = slugs[: _MAX_PER_KIND["screening"]]
    if not slugs:
        return []
    try:
        rows = (
            _sb().table("market_screenings")
            .select("slug,name,description")
            .in_("slug", slugs)
            .eq("is_published", True)
            .execute()
            .data
            or []
        )
    except Exception as exc:
        log.warning("provenance: screening lookup failed: %s", exc)
        return []
    return [
        {
            "kind": "screening",
            "key": r["slug"],
            "label": r["name"],
            "href": f"/marketscreenings/{r['slug']}",
            "detail": (r.get("description") or "")[:120] or None,
        }
        for r in rows
    ]


def _article_resources(ids: list[int]) -> list[dict[str, Any]]:
    """Resolve article ids to their published slugs.

    Only articles that actually have a slug are returned — the arena links to
    the site's own article page, and an article without one has no page.
    """
    seen: list[int] = []
    for i in ids:
        if i not in seen:
            seen.append(i)
    seen = seen[: _MAX_PER_KIND["article"]]
    if not seen:
        return []
    try:
        rows = (
            _sb().table("news_articles")
            .select("id,title,slug,source,published_at")
            .in_("id", seen)
            .not_.is_("slug", "null")
            .execute()
            .data
            or []
        )
    except Exception as exc:
        log.warning("provenance: article lookup failed: %s", exc)
        return []
    return [
        {
            "kind": "article",
            "key": str(r["id"]),
            "label": (r.get("title") or "Untitled")[:140],
            "href": f"/articles/{r['slug']}",
            "detail": r.get("source"),
        }
        for r in rows
        if r.get("slug")
    ]


def _ticker_resources(tickers: dict[str, str]) -> list[dict[str, Any]]:
    """Only tickers the platform actually publishes a quote page for."""
    names = [t for t in tickers if t.isalpha()][: _MAX_PER_KIND["ticker"] * 2]
    if not names:
        return []
    try:
        rows = (
            _sb().table("tickers")
            .select("symbol,company_name")
            .in_("symbol", names)
            .execute()
            .data
            or []
        )
    except Exception as exc:
        log.warning("provenance: ticker lookup failed: %s", exc)
        return []
    known = {r["symbol"]: r.get("company_name") for r in rows}
    return [
        {
            "kind": "ticker",
            "key": sym,
            "label": sym,
            "href": f"/quote/{sym}",
            "detail": known.get(sym) or tickers.get(sym),
        }
        for sym in list(tickers)
        if sym in known
    ][: _MAX_PER_KIND["ticker"]]


def _topic_resources(tags: list[str]) -> list[dict[str, Any]]:
    tags = tags[: _MAX_PER_KIND["topic"]]
    if not tags:
        return []
    try:
        rows = (
            _sb().table("topics").select("slug,title").in_("slug", tags).execute().data or []
        )
    except Exception as exc:
        log.warning("provenance: topic lookup failed: %s", exc)
        return []
    return [
        {
            "kind": "topic",
            "key": r["slug"],
            "label": r.get("title") or r["slug"],
            "href": f"/topics/{r['slug']}",
            "detail": None,
        }
        for r in rows
    ]


# ── The tool surface, described for the public page ──────────────────────────
# What each tool reads, in the reader's language, and where on the site the same
# data is published. This is what makes "which internal tools does this agent
# use" answerable without reading the source.

TOOL_SURFACE: dict[str, dict[str, str]] = {
    "get_top_articles": {
        "label": "News impact scores",
        "reads": "Every article, scored by an LLM across impact dimensions and ranked by magnitude.",
        "href": "/articles",
    },
    "get_ticker_news": {
        "label": "Per-ticker news",
        "reads": "The scored articles that actually concern a given ticker.",
        "href": "/articles",
    },
    "get_ticker_sentiment": {
        "label": "Ticker sentiment",
        "reads": "Article-level sentiment per ticker, with confidence.",
        "href": "/articles",
    },
    "search_news": {
        "label": "News search",
        "reads": "Tag and full-text search over the scored article corpus.",
        "href": "/articles",
    },
    "get_news_by_tag": {
        "label": "Theme search",
        "reads": "Articles grouped by theme tag.",
        "href": "/topics",
    },
    "get_cluster_trends": {
        "label": "Cluster trends",
        "reads": "Cluster-level sentiment aggregates over the news corpus.",
        "href": "/articles",
    },
    "get_dimension_trends": {
        "label": "Dimension trends",
        "reads": "Impact-dimension aggregates over the news corpus.",
        "href": "/articles",
    },
    "get_trending_tickers": {
        "label": "Attention acceleration",
        "reads": "Tickers whose news volume is accelerating against their own baseline.",
        "href": "/articles",
    },
    "get_priced_in": {
        "label": "Priced-in decomposition",
        "reads": "What a share price already assumes, driver by driver.",
        "href": "/quote",
    },
    "get_priced_in_drivers": {
        "label": "Priced-in drivers",
        "reads": "The individual assumptions behind a price, and how much of each is absorbed.",
        "href": "/quote",
    },
    "get_priced_in_case": {
        "label": "Driver evidence",
        "reads": "The evidence behind one priced-in driver.",
        "href": "/quote",
    },
    "search_priced_in_drivers": {
        "label": "Driver search",
        "reads": "Priced-in drivers matching a theme, across the covered universe.",
        "href": "/quote",
    },
    "get_ticker_relationships": {
        "label": "Relationship graph",
        "reads": "Typed, evidence-backed links between companies — suppliers, customers, competitors.",
        "href": "/quote",
    },
    "get_company_vectors": {
        "label": "Company factor profile",
        "reads": "Per-ticker fundamental dimension scores.",
        "href": "/quote",
    },
    "get_screening_results": {
        "label": "Market screenings",
        "reads": "The platform's published screening boards and what passed them.",
        "href": "/marketscreenings",
    },
    "list_screenings": {
        "label": "Screening index",
        "reads": "Every available screening board and what it looks for.",
        "href": "/marketscreenings",
    },
    "get_pair_signals": {
        "label": "Pair divergence",
        "reads": "Cointegrated pairs whose spread has stretched, with hedge ratio and half-life.",
        "href": "/quote",
    },
    "get_my_portfolio": {
        "label": "Own book",
        "reads": "Its own cash, positions and risk limits.",
        "href": "",
    },
    "get_my_recent_trades": {
        "label": "Own order history",
        "reads": "Its own past orders, including the ones the broker refused.",
        "href": "",
    },
    "place_order": {
        "label": "Place order",
        "reads": "The one write it has: queue an order for the next session's open.",
        "href": "",
    },
    "fetch_url": {
        "label": "Fetch a URL",
        "reads": "Read the text of a public web page.",
        "href": "",
    },
}


def describe_tools(names: Iterable[str]) -> list[dict[str, Optional[str]]]:
    """Public-facing descriptions for an agent's tool surface.

    Unknown names (the FMP MCP set, which is discovered at runtime) are grouped
    rather than dropped, so the page never implies an agent sees less than it
    does.
    """
    out: list[dict[str, Optional[str]]] = []
    has_fmp = False
    for name in sorted(set(names)):
        entry = TOOL_SURFACE.get(name)
        if entry:
            out.append({"name": name, **entry})
        else:
            # The FMP set is discovered from its MCP server at runtime, so the
            # exact endpoint list is not known here. It is named as one surface
            # rather than counted, because a count taken from the spec would be
            # wrong the moment the server's catalogue changes.
            has_fmp = True
    if has_fmp:
        out.append(
            {
                "name": "fmp",
                "label": "Financial data (FMP)",
                "reads": "Company statements, ratios, growth, ownership and technicals.",
                "href": "",
            }
        )
    return out
