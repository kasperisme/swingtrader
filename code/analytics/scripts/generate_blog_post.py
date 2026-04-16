#!/usr/bin/env python3
"""
generate_blog_post.py — Auto-generate and publish news impact blog posts to Sanity,
then post an X (Twitter) thread summarising the analysis with a backlink.

Queries the Supabase swingtrader schema for recently scored news articles,
uses the local Ollama instance to write a structured analysis post, then
publishes it to the newsimpactscreener Sanity project (project ID: y2lg8a3c).
Optionally posts a 4-tweet X thread using the same research data.

Modes:
  pre-market   — looks back 14 h (overnight news), run at 08:30 ET weekdays
  intra-market — looks back  6 h (morning session), run at 14:30 ET weekdays

Usage:
  python scripts/generate_blog_post.py --mode pre-market
  python scripts/generate_blog_post.py --mode intra-market
  python scripts/generate_blog_post.py --mode pre-market --dry-run
  python scripts/generate_blog_post.py --mode pre-market --skip-x
  python scripts/generate_blog_post.py --check-x-auth

Required env vars (analytics/.env):
  SUPABASE_URL, SUPABASE_KEY, SUPABASE_SCHEMA
  SANITY_TOKEN   — Sanity write token (Editor role or above)

Optional env vars:
  SANITY_PROJECT_ID        (default: y2lg8a3c)
  SANITY_DATASET           (default: production)
  OLLAMA_BASE_URL          (default: http://localhost:11434)
  OLLAMA_BLOG_MODEL        (default: OLLAMA_IMPACT_MODEL → gemma4:e4b)
  NEWS_LOOKBACK_HOURS      (override default per mode)
  NEWS_MAX_ARTICLES        (default: 20 — max articles pulled for analysis)
  SITE_BASE_URL            (default: https://newsimpactscreener.com)
  X_CONSUMER_KEY           — OAuth 1.0a API Key
  X_CONSUMER_SECRET        — OAuth 1.0a API Secret
  X_ACCESS_TOKEN           — OAuth 1.0a Access Token
  X_ACCESS_SECRET          — OAuth 1.0a Access Token Secret
  X_OAUTH1_CALLBACK        — OAuth 1.0a callback URL (default: oob)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import pathlib
import re
import sys
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=_REPO_ROOT / ".env")

sys.path.insert(0, str(_REPO_ROOT))

from src.db import get_supabase_client, get_schema, _as_json  # noqa: E402
from news_impact.semantic_retrieval import search_news_embeddings  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)
USE_SEMANTIC_RETRIEVAL = os.environ.get(
    "USE_SEMANTIC_RETRIEVAL", "true"
).strip().lower() not in {"0", "false", "no", "off"}

try:
    from xdk import Client as XClient  # type: ignore
    from xdk.oauth1_auth import OAuth1  # type: ignore

    _XDK_AVAILABLE = True
except ImportError:
    _XDK_AVAILABLE = False

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SANITY_PROJECT_ID = os.environ.get("SANITY_PROJECT_ID", "y2lg8a3c")
SANITY_DATASET = os.environ.get("SANITY_DATASET", "production")
SANITY_API_VER = "2021-06-07"
SANITY_TOKEN = os.environ.get("SANITY_TOKEN", "")

SITE_BASE_URL = os.environ.get(
    "SITE_BASE_URL", "https://newsimpactscreener.com"
).rstrip("/")
X_ACCESS_TOKEN = os.environ.get("X_ACCESS_TOKEN", "")
X_ACCESS_SECRET = os.environ.get("X_ACCESS_SECRET", "")
X_CONSUMER_KEY = os.environ.get("X_CONSUMER_KEY", "")
X_CONSUMER_SECRET = os.environ.get("X_CONSUMER_SECRET", "")
X_OAUTH1_CALLBACK = os.environ.get("X_OAUTH1_CALLBACK", "oob")

AUTHOR_ID = "81d00698-faa2-4dc7-81b8-bec6ec3b8884"

CATEGORY_IDS = {
    "pre-market": "1ca18181-78f8-4c58-8bf8-e9acc1c8c127",
    "intra-market": "3dcae939-2a2f-4768-aee0-adefd45f9f54",
    "news-impact": "728b9f28-2c16-4984-8764-c765fa27fa92",
}

LOOKBACK_HOURS = {
    "pre-market": 14,
    "intra-market": 6,
}

EASTERN_TZ_OFFSET = timedelta(hours=-4)  # EDT; use -5 for EST (standard)

# ---------------------------------------------------------------------------
# Supabase helpers
# ---------------------------------------------------------------------------


def _fetch_recent_articles(
    mode: str, lookback_hours: int, max_articles: int
) -> list[dict]:
    """
    Pull scored articles from Supabase: news_articles JOIN news_impact_vectors.

    Returns a list of dicts with keys:
      id, title, url, slug, source, created_at,
      impact_json, top_dimensions
    """
    client = get_supabase_client()
    schema = get_schema()

    since = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
    since_iso = since.isoformat()

    art_res = (
        client.schema(schema)
        .table("news_articles")
        .select("id, title, url, slug, source, created_at")
        .gte("created_at", since_iso)
        .order("created_at", desc=True)
        .limit(max_articles)
        .execute()
    )
    articles = art_res.data or []
    if not articles:
        log.warning("No articles found in the last %d hours.", lookback_hours)
        return []

    article_ids = [a["id"] for a in articles]

    vec_res = (
        client.schema(schema)
        .table("news_impact_vectors")
        .select("article_id, impact_json, top_dimensions")
        .in_("article_id", article_ids)
        .execute()
    )
    vectors_by_id: dict[int, dict] = {v["article_id"]: v for v in (vec_res.data or [])}

    # Attach impact data and filter to articles that have been scored
    enriched = []
    for a in articles:
        vec = vectors_by_id.get(a["id"])
        if vec is None:
            continue  # not yet scored — skip
        enriched.append(
            {
                **a,
                "impact_json": _as_json(vec["impact_json"], default={}),
                "top_dimensions": _as_json(vec["top_dimensions"], default=[]),
            }
        )

    log.info(
        "Fetched %d scored articles (of %d total in window).",
        len(enriched),
        len(articles),
    )
    return enriched


def _fetch_tickers_for_articles(article_ids: list[int]) -> dict[int, list[str]]:
    """Return {article_id: [ticker, ...]} for the given article IDs."""
    if not article_ids:
        return {}
    client = get_supabase_client()
    schema = get_schema()
    res = (
        client.schema(schema)
        .table("news_article_tickers")
        .select("article_id, ticker")
        .in_("article_id", article_ids)
        .execute()
    )
    out: dict[int, list[str]] = {}
    for row in res.data or []:
        out.setdefault(row["article_id"], []).append(row["ticker"])
    return out


def _fetch_company_metadata(tickers: list[str]) -> dict[str, dict]:
    """Return {ticker: metadata_json} (sector, industry, name) from company_vectors."""
    if not tickers:
        return {}
    client = get_supabase_client()
    schema = get_schema()
    meta: dict[str, dict] = {}
    for t in tickers:
        res = (
            client.schema(schema)
            .table("company_vectors")
            .select("ticker, metadata_json")
            .eq("ticker", t)
            .order("vector_date", desc=True)
            .limit(1)
            .execute()
        )
        if res.data:
            meta[t] = _as_json(res.data[0].get("metadata_json"), default={})
    return meta


# ---------------------------------------------------------------------------
# Data analysis helpers
# ---------------------------------------------------------------------------


def _impact_magnitude(impact_json: dict) -> float:
    """Sum of abs values of all impact dimensions — used to rank articles."""
    return sum(abs(v) for v in impact_json.values() if isinstance(v, (int, float)))


def _top_dims(impact_json: dict, n: int = 5) -> list[tuple[str, float]]:
    """Return top N dimensions by absolute score, descending."""
    items = [(k, v) for k, v in impact_json.items() if isinstance(v, (int, float))]
    return sorted(items, key=lambda x: abs(x[1]), reverse=True)[:n]


def _aggregate_dimensions(articles: list[dict]) -> list[tuple[str, float]]:
    """Cumulative average score per dimension across all articles."""
    totals: dict[str, float] = {}
    counts: dict[str, int] = {}
    for a in articles:
        for dim, score in (a.get("impact_json") or {}).items():
            if isinstance(score, (int, float)):
                totals[dim] = totals.get(dim, 0.0) + score
                counts[dim] = counts.get(dim, 0) + 1
    avgs = {dim: totals[dim] / counts[dim] for dim in totals}
    return sorted(avgs.items(), key=lambda x: abs(x[1]), reverse=True)


def _top_tickers(
    tickers_map: dict[int, list[str]],
    articles: list[dict],
    n: int = 5,
) -> list[str]:
    """Return the N tickers that appear across the highest-impact articles."""
    ticker_weight: dict[str, float] = {}
    for a in articles:
        mag = _impact_magnitude(a.get("impact_json") or {})
        for t in tickers_map.get(a["id"], []):
            ticker_weight[t] = ticker_weight.get(t, 0.0) + mag
    return [
        t
        for t, _ in sorted(ticker_weight.items(), key=lambda x: x[1], reverse=True)[:n]
    ]


def _fmt_dim(dim: str) -> str:
    """Convert snake_case dimension to Title Case display label."""
    return dim.replace("_", " ").title()


def _fmt_score(score: float) -> str:
    sign = "+" if score >= 0 else ""
    return f"{sign}{score:.2f}"


# ---------------------------------------------------------------------------
# Ollama blog post generation
# ---------------------------------------------------------------------------


def _build_prompt(
    mode: str,
    articles: list[dict],
    tickers_map: dict[int, list[str]],
    company_meta: dict[str, dict],
    now_et: datetime,
) -> str:
    """Build the user prompt for the Anthropic blog post generation call."""

    date_str = now_et.strftime("%A, %B %-d")
    period_label = "Pre-Market" if mode == "pre-market" else "Intra-Market"

    # Top 5 articles by impact magnitude
    ranked = sorted(
        articles,
        key=lambda a: _impact_magnitude(a.get("impact_json") or {}),
        reverse=True,
    )[:5]

    articles_block = ""
    for i, a in enumerate(ranked, 1):
        title = a.get("title") or "Untitled"
        source = a.get("source") or "Unknown source"
        tickers = tickers_map.get(a["id"], [])
        ticker_str = ", ".join(tickers) if tickers else "no tickers extracted"
        top = _top_dims(a.get("impact_json") or {}, n=4)
        dims_str = "\n".join(f"    - {_fmt_dim(d)}: {_fmt_score(s)}" for d, s in top)
        articles_block += (
            f"\n{i}. **{title}** ({source})\n"
            f"   Tickers: {ticker_str}\n"
            f"   Top impact dimensions:\n{dims_str}\n"
        )

    # Aggregate factor moves
    agg = _aggregate_dimensions(articles)[:8]
    agg_str = "\n".join(f"  - {_fmt_dim(d)}: {_fmt_score(s)} (avg)" for d, s in agg)

    # Top tickers + company context
    top_tickers = _top_tickers(tickers_map, articles, n=5)
    tickers_block = ""
    for t in top_tickers:
        meta = company_meta.get(t, {})
        name = meta.get("name") or t
        sector = meta.get("sector") or "Unknown sector"
        industry = meta.get("industry") or ""
        tickers_block += (
            f"  - {t} ({name}) — {sector}"
            + (f", {industry}" if industry else "")
            + "\n"
        )

    # Semantic evidence snippets (embedding retrieval over recent corpus).
    semantic_hits: list[dict] = []
    if USE_SEMANTIC_RETRIEVAL:
        retrieval_query = (
            f"{period_label} market narrative. "
            f"Top tickers: {', '.join(top_tickers) or 'none'}. "
            f"Key factor dimensions: {', '.join(_fmt_dim(d) for d, _ in agg[:5])}. "
            "Provide the most relevant recent snippets to support blog analysis."
        )
        semantic_hits = search_news_embeddings(
            retrieval_query,
            lookback_hours=LOOKBACK_HOURS.get(mode, 14),
            tickers=top_tickers or None,
            limit=10,
        )
    semantic_block = ""
    for i, hit in enumerate(semantic_hits[:8], 1):
        semantic_block += (
            f"  {i}. [article_id={hit['article_id']}] {hit.get('title','')[:90]}\n"
            f"     snippet: {str(hit.get('snippet') or '')[:220]}\n"
        )

    prompt = f"""You are writing a concise, insight-packed market analysis blog post for the NewsImpactScreener blog.

The post is for the **{period_label} Edition — {date_str}**.

Audience: quantitative-minded swing traders who care about which news events move which factor dimensions (macro sensitivity, sector rotation, tariff exposure, etc.) and which companies are most exposed.

Tone: direct, analytical, no fluff. Think Bloomberg Brief meets quantitative hedge fund morning note.

---

**Top {len(ranked)} stories by impact magnitude:**
{articles_block}

**Aggregate factor moves across all {len(articles)} scored articles:**
{agg_str}

**Top exposed companies (by appearance in high-impact stories):**
{tickers_block}

**Semantic evidence snippets (for grounding and citations):**
{semantic_block if semantic_block else "  (none)"}

---

Write the blog post body. Structure it as:

1. A 2-3 sentence opening that sets the tone for what moved and why it matters for {period_label.lower()} positioning.

2. **Top Stories** — a brief breakdown of the 3-5 most impactful articles, explaining *why* each matters from a factor exposure angle (not just what happened).

3. **Key Factor Moves** — which dimensions are getting hit today and in which direction (bullish/bearish). Keep it to the top 4-5 with one sentence each.

4. **Company Exposure Spotlight** — call out the most-mentioned companies and briefly note their relevant exposures.

5. A 1-sentence closing that frames the setup going into {"the open" if mode == "pre-market" else "the close"}.

Use markdown headers (##). Be specific with dimension names. Scores range from -1.0 (very negative impact) to +1.0 (very positive). Keep total length under 500 words.
"""
    return prompt


def _build_caveman_prompt(body_markdown: str) -> str:
    """Build prompt to compress a blog post body into caveman style."""
    return f"""Compress the blog post below into caveman style. Same structure and sections. ~70% fewer words.

Rules:
- Drop: articles (a/an/the), filler words (just/basically/really), hedging, pleasantries
- Keep: technical terms exact, ticker symbols, numbers, dimension names, direction (bullish/bearish)
- Pattern: [thing] [action] [reason]. [next step].
- Fragments OK. Short synonyms. Active voice only.
- Preserve all ## headings. Preserve bold (**text**).
- Output ONLY the compressed markdown. No preamble, no commentary.

Original post:
{body_markdown}
"""


async def _call_ollama_caveman(body_markdown: str) -> str:
    """Call Ollama to produce a caveman-compressed version of the blog post."""
    model = (
        os.environ.get("OLLAMA_BLOG_MODEL")
        or os.environ.get("OLLAMA_IMPACT_MODEL")
        or "gemma4:e4b"
    )
    base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    url = f"{base_url}/api/chat"
    num_predict = int(os.environ.get("OLLAMA_CAVEMAN_NUM_PREDICT", "600"))

    payload = {
        "model": model,
        "stream": False,
        "think": False,
        "options": {"num_predict": num_predict},
        "messages": [
            {
                "role": "system",
                "content": (
                    "You compress financial blog posts into ultra-terse caveman prose. "
                    "Same structure, ~70% fewer words. No articles, no filler, no hedging. "
                    "Keep all technical terms, tickers, numbers, and dimension names exact."
                ),
            },
            {"role": "user", "content": _build_caveman_prompt(body_markdown)},
        ],
    }

    log.info("Calling Ollama for caveman body, model=%s", model)
    async with httpx.AsyncClient() as client:
        try:
            r = await client.post(url, json=payload, timeout=120.0)
        except httpx.TimeoutException:
            raise RuntimeError("Ollama timed out generating caveman body")
        except httpx.RequestError as exc:
            raise RuntimeError(f"Ollama connection error: {exc}") from exc

    if r.status_code != 200:
        raise RuntimeError(f"Ollama returned HTTP {r.status_code}: {r.text[:200]}")

    return r.json()["message"]["content"].strip()


async def _call_ollama(prompt: str) -> str:
    """Call the local Ollama instance and return the blog post markdown."""
    model = (
        os.environ.get("OLLAMA_BLOG_MODEL")
        or os.environ.get("OLLAMA_IMPACT_MODEL")
        or "gemma4:e4b"
    )
    base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    url = f"{base_url}/api/chat"
    num_predict = int(os.environ.get("OLLAMA_BLOG_NUM_PREDICT", "1500"))

    payload = {
        "model": model,
        "stream": False,
        "think": False,
        "options": {"num_predict": num_predict},
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a quantitative finance market analyst writing concise, insight-dense blog posts "
                    "about how news events shift factor exposures. Use plain English, no emojis, no hype."
                ),
            },
            {"role": "user", "content": prompt},
        ],
    }

    log.info("Calling Ollama model=%s at %s", model, base_url)
    async with httpx.AsyncClient() as client:
        try:
            r = await client.post(url, json=payload, timeout=120.0)
        except httpx.TimeoutException:
            raise RuntimeError(f"Ollama timed out after 120s (model={model})")
        except httpx.RequestError as exc:
            raise RuntimeError(f"Ollama connection error: {exc}") from exc

    if r.status_code != 200:
        raise RuntimeError(f"Ollama returned HTTP {r.status_code}: {r.text[:200]}")

    data = r.json()
    return data["message"]["content"].strip()


# ---------------------------------------------------------------------------
# Portable Text (Sanity blockContent) builder
# ---------------------------------------------------------------------------


def _key() -> str:
    return uuid.uuid4().hex[:12]


def _span(text: str, marks: Optional[list[str]] = None) -> dict:
    return {
        "_type": "span",
        "_key": _key(),
        "text": text,
        "marks": marks or [],
    }


def _block(
    children: list[dict], style: str = "normal", mark_defs: Optional[list] = None
) -> dict:
    return {
        "_type": "block",
        "_key": _key(),
        "style": style,
        "markDefs": mark_defs or [],
        "children": children,
    }


def _markdown_to_portable_text(md: str) -> list[dict]:
    """
    Convert simple markdown (##, **, plain paragraphs) to Sanity Portable Text blocks.
    Handles: ## headings, **bold** inline, blank-line-separated paragraphs.
    """
    blocks: list[dict] = []

    for para in re.split(r"\n{2,}", md.strip()):
        lines = para.strip().splitlines()
        if not lines:
            continue

        first = lines[0].strip()

        # Heading
        if first.startswith("## "):
            heading_text = first[3:].strip()
            blocks.append(_block([_span(heading_text)], style="h2"))
            rest = "\n".join(lines[1:]).strip()
            if rest:
                blocks.extend(_markdown_to_portable_text(rest))
            continue

        if first.startswith("# "):
            heading_text = first[2:].strip()
            blocks.append(_block([_span(heading_text)], style="h1"))
            rest = "\n".join(lines[1:]).strip()
            if rest:
                blocks.extend(_markdown_to_portable_text(rest))
            continue

        # Normal paragraph — inline bold parsing
        full_text = " ".join(lines)
        children = _parse_inline(full_text)
        if children:
            blocks.append(_block(children, style="normal"))

    return blocks


def _parse_inline(text: str) -> list[dict]:
    """Split text on **bold** markers and return span children."""
    parts = re.split(r"\*\*(.+?)\*\*", text)
    children = []
    for i, part in enumerate(parts):
        if not part:
            continue
        marks = ["strong"] if i % 2 == 1 else []
        children.append(_span(part, marks))
    return children


# ---------------------------------------------------------------------------
# Sanity publishing
# ---------------------------------------------------------------------------


def _slug_from_title(title: str) -> str:
    slug = title.lower()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"[\s]+", "-", slug.strip())
    return slug[:96]


def _publish_to_sanity(
    title: str,
    body_markdown: str,
    caveman_markdown: str,
    mode: str,
    published_at: str,
    dry_run: bool = False,
) -> Optional[str]:
    """Create and immediately publish a post to Sanity. Returns the document ID."""
    if not SANITY_TOKEN:
        raise RuntimeError("SANITY_TOKEN is not set in .env")

    doc_id = f"blog-auto-{uuid.uuid4().hex[:16]}"
    slug = _slug_from_title(title)

    category_refs = [
        {"_type": "reference", "_ref": CATEGORY_IDS[mode], "_key": _key()},
        {"_type": "reference", "_ref": CATEGORY_IDS["news-impact"], "_key": _key()},
    ]

    body_blocks = _markdown_to_portable_text(body_markdown)
    caveman_blocks = _markdown_to_portable_text(caveman_markdown)

    document = {
        "_id": doc_id,
        "_type": "post",
        "title": title,
        "slug": {"_type": "slug", "current": slug},
        "author": {"_type": "reference", "_ref": AUTHOR_ID},
        "categories": category_refs,
        "publishedAt": published_at,
        "body": body_blocks,
        "cavemanBody": caveman_blocks,
    }

    mutations = [{"createOrReplace": document}]

    url = f"https://{SANITY_PROJECT_ID}.api.sanity.io/v{SANITY_API_VER}/data/mutate/{SANITY_DATASET}"
    headers = {
        "Authorization": f"Bearer {SANITY_TOKEN}",
        "Content-Type": "application/json",
    }

    if dry_run:
        log.info("[dry-run] Would POST to %s", url)
        log.info("[dry-run] Document: %s", json.dumps(document, indent=2)[:800])
        return doc_id

    resp = httpx.post(url, headers=headers, json={"mutations": mutations}, timeout=30)
    resp.raise_for_status()
    result = resp.json()
    log.info("Sanity mutation result: %s", result)

    # Now publish (move from drafts to published)
    publish_mutations = [{"patch": {"id": doc_id, "unset": ["_id"]}}]
    publish_url = (
        f"https://{SANITY_PROJECT_ID}.api.sanity.io/v{SANITY_API_VER}"
        f"/data/mutate/{SANITY_DATASET}?returnDocuments=false"
    )
    # Sanity auto-publishes createOrReplace when id has no drafts. prefix
    # The doc was created as published already (no "drafts." prefix on _id).
    log.info("Published post: %s (slug: %s)", doc_id, slug)
    return doc_id


# ---------------------------------------------------------------------------
# X (Twitter) thread generation and posting
# ---------------------------------------------------------------------------


def _build_x_thread_prompt(
    mode: str,
    articles: list[dict],
    tickers_map: dict[int, list[str]],
    company_meta: dict[str, dict],
    now_et: datetime,
    blog_url: str,
) -> str:
    date_str = now_et.strftime("%b %-d")
    period_label = "Pre-Market" if mode == "pre-market" else "Intra-Market"

    ranked = sorted(
        articles,
        key=lambda a: _impact_magnitude(a.get("impact_json") or {}),
        reverse=True,
    )[:5]
    top_tickers = _top_tickers(tickers_map, articles, n=5)
    agg = _aggregate_dimensions(articles)[:5]

    articles_block = ""
    for i, a in enumerate(ranked[:3], 1):
        title = (a.get("title") or "Untitled")[:80]
        tickers = tickers_map.get(a["id"], [])
        ticker_str = " ".join(f"${t}" for t in tickers[:3])
        articles_block += f"\n{i}. {title} {ticker_str}"

    dims_block = "\n".join(f"  {_fmt_dim(d)}: {_fmt_score(s)}" for d, s in agg)
    ticker_list = " ".join(f"${t}" for t in top_tickers)

    return f"""Write a 4-tweet X (Twitter) thread for the {period_label} News Impact update on {date_str}.

Rules:
- Each tweet must be under 280 characters.
- No emojis. No hype.
- Separate each tweet with the exact delimiter on its own line: ---TWEET---
- Do NOT number the tweets or add any labels.

Context:
Top stories:{articles_block}

Aggregate factor moves:
{dims_block}

Top tickers: {ticker_list}

Thread structure:
Tweet 1: 2-sentence hook — what moved and why it matters for {period_label.lower()} positioning. Mention 1-2 key tickers with $ prefix.
Tweet 2: Top 2 factor dimension moves with direction (bullish/bearish) and which stocks or sectors are most exposed.
Tweet 3: One sharp observation — a risk or setup that traders might be missing from this data.
Tweet 4: "Full {period_label} analysis: {blog_url}" followed by hashtags #SwingTrading #MarketNews #NewsImpact

Output only the 4 tweets separated by ---TWEET---. No other text before or after.
"""


async def _call_ollama_for_x(prompt: str) -> str:
    """Call Ollama with a reduced token budget suited for short tweet content."""
    model = (
        os.environ.get("OLLAMA_BLOG_MODEL")
        or os.environ.get("OLLAMA_IMPACT_MODEL")
        or "gemma4:e4b"
    )
    base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    url = f"{base_url}/api/chat"

    payload = {
        "model": model,
        "stream": False,
        "think": False,
        "options": {"num_predict": 500},
        "messages": [
            {
                "role": "system",
                "content": (
                    "You write short, factual X (Twitter) threads about market-moving news. "
                    "Each tweet is strictly under 280 characters. No emojis. No filler. No numbering."
                ),
            },
            {"role": "user", "content": prompt},
        ],
    }

    log.info("Calling Ollama for X thread, model=%s", model)
    async with httpx.AsyncClient() as client:
        try:
            r = await client.post(url, json=payload, timeout=60.0)
        except httpx.TimeoutException:
            raise RuntimeError("Ollama timed out generating X thread")
        except httpx.RequestError as exc:
            raise RuntimeError(f"Ollama connection error: {exc}") from exc

    if r.status_code != 200:
        raise RuntimeError(f"Ollama returned HTTP {r.status_code}: {r.text[:200]}")

    return r.json()["message"]["content"].strip()


def _parse_x_thread(raw: str) -> list[str]:
    """Split Ollama output into individual tweets, enforcing 280-char hard cap."""
    tweets = [t.strip() for t in raw.split("---TWEET---") if t.strip()]
    return [t[:280] for t in tweets]


def _build_x_client() -> Optional[Any]:
    """Create an authenticated X client using OAuth 1.0a user context."""
    if not _XDK_AVAILABLE:
        log.error("xdk is not installed — cannot use X API. Run: pip install xdk")
        return None

    if not X_ACCESS_TOKEN or not X_ACCESS_SECRET or not X_CONSUMER_KEY or not X_CONSUMER_SECRET:
        log.warning(
            "Missing OAuth 1.0a credentials. Set X_ACCESS_TOKEN, X_ACCESS_SECRET, "
            "X_CONSUMER_KEY, and X_CONSUMER_SECRET."
        )
        return None

    oauth1 = OAuth1(
        api_key=X_CONSUMER_KEY,
        api_secret=X_CONSUMER_SECRET,
        callback=X_OAUTH1_CALLBACK,
        access_token=X_ACCESS_TOKEN,
        access_token_secret=X_ACCESS_SECRET,
    )
    return XClient(auth=oauth1)


def _check_x_auth() -> bool:
    """Validate OAuth 1.0a credentials by calling the authenticated user endpoint."""
    client = _build_x_client()
    if client is None:
        return False

    try:
        response = client.users.get_me()
        user = response.data
    except Exception as exc:
        log.error("X OAuth 1.0a auth check failed: %s", exc)
        return False

    username = getattr(user, "username", None) or getattr(user, "user_name", None)
    user_id = getattr(user, "id", None)
    name = getattr(user, "name", None)
    log.info(
        "X OAuth 1.0a auth check succeeded. user_id=%s username=%s name=%s",
        user_id or "unknown",
        username or "unknown",
        name or "unknown",
    )
    return True


def _post_x_thread(tweets: list[str], dry_run: bool = False) -> Optional[str]:
    """
    Post a tweet thread to X. Each tweet replies to the previous one.
    Returns the ID of the root tweet, or None on failure/skip.
    """
    if not tweets:
        log.warning("No tweets to post — skipping X thread.")
        return None

    if dry_run:
        log.info("[dry-run] X thread (%d tweets):", len(tweets))
        for i, t in enumerate(tweets, 1):
            log.info("  [%d/%d] (%d chars) %s", i, len(tweets), len(t), t)
        return "dry-run-id"

    client = _build_x_client()
    if client is None:
        log.warning("Skipping X thread because OAuth 1.0a client could not be created.")
        return None

    root_id: Optional[str] = None
    reply_to: Optional[str] = None

    for i, text in enumerate(tweets):
        body: dict[str, Any] = {"text": text}
        if reply_to:
            body["reply"] = {"in_reply_to_tweet_id": reply_to}
        response = client.posts.create(body=body)
        tweet_id = str(response.data.id)
        log.info("Posted tweet %d/%d id=%s", i + 1, len(tweets), tweet_id)
        if root_id is None:
            root_id = tweet_id
        reply_to = tweet_id

    return root_id


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Auto-generate Sanity blog post from Supabase news impact data"
    )
    parser.add_argument("--mode", choices=["pre-market", "intra-market"])
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build and log the post without publishing or posting",
    )
    parser.add_argument(
        "--check-x-auth",
        action="store_true",
        help="Only verify X OAuth 1.0a credentials and exit",
    )
    parser.add_argument(
        "--skip-x", action="store_true", help="Skip X thread generation and posting"
    )
    parser.add_argument(
        "--skip-sanity",
        action="store_true",
        help="Skip blog post generation and Sanity publishing (X thread only)",
    )
    parser.add_argument(
        "--lookback-hours",
        type=int,
        default=None,
        help="Override default lookback window",
    )
    parser.add_argument(
        "--max-articles", type=int, default=int(os.environ.get("NEWS_MAX_ARTICLES", 20))
    )
    args = parser.parse_args()

    if args.check_x_auth:
        sys.exit(0 if _check_x_auth() else 1)

    if not args.mode:
        parser.error("--mode is required unless --check-x-auth is used")

    lookback = args.lookback_hours or int(
        os.environ.get("NEWS_LOOKBACK_HOURS", LOOKBACK_HOURS[args.mode])
    )

    now_utc = datetime.now(timezone.utc)
    now_et = now_utc + EASTERN_TZ_OFFSET  # approximate ET

    log.info(
        "Mode: %s | Lookback: %d h | Now ET: %s",
        args.mode,
        lookback,
        now_et.strftime("%Y-%m-%d %H:%M"),
    )

    # 1. Pull data from Supabase
    articles = _fetch_recent_articles(args.mode, lookback, args.max_articles)
    if not articles:
        log.warning("No scored articles found — exiting.")
        sys.exit(0)

    article_ids = [a["id"] for a in articles]
    tickers_map = _fetch_tickers_for_articles(article_ids)

    all_tickers = list({t for ts in tickers_map.values() for t in ts})
    top_tickers = _top_tickers(tickers_map, articles, n=8)
    company_meta = _fetch_company_metadata(top_tickers)

    log.info("Articles: %d | Unique tickers: %d", len(articles), len(all_tickers))

    # 2. Derive title/slug/URL (needed by both blog and X thread)
    period_label = "Pre-Market" if args.mode == "pre-market" else "Intra-Market"
    date_str = now_et.strftime("%b %-d")
    title = f"{period_label} News Impact: {date_str}"
    slug = _slug_from_title(title)
    blog_url = f"{SITE_BASE_URL}/blog/{slug}"

    # 3. Generate and publish blog post (unless skipped)
    if not args.skip_sanity:
        prompt = _build_prompt(args.mode, articles, tickers_map, company_meta, now_et)
        body_markdown = await _call_ollama(prompt)
        log.info("Generated post: %r (%d chars)", title, len(body_markdown))

        caveman_markdown = await _call_ollama_caveman(body_markdown)
        log.info("Generated caveman body (%d chars)", len(caveman_markdown))

        if args.dry_run:
            print("\n" + "=" * 60)
            print(f"TITLE: {title}")
            print(f"URL:   {blog_url}")
            print("=" * 60)
            print(body_markdown)
            print("\n--- CAVEMAN BODY ---")
            print(caveman_markdown)
            print("=" * 60 + "\n")
        doc_id = _publish_to_sanity(
            title=title,
            body_markdown=body_markdown,
            caveman_markdown=caveman_markdown,
            mode=args.mode,
            published_at=now_utc.isoformat(),
            dry_run=args.dry_run,
        )
        log.info("Sanity document ID: %s", doc_id)
    else:
        log.info("Skipping Sanity blog post (--skip-sanity). Blog URL: %s", blog_url)

    # 4. Generate and post X thread
    if not args.skip_x:
        x_prompt = _build_x_thread_prompt(
            mode=args.mode,
            articles=articles,
            tickers_map=tickers_map,
            company_meta=company_meta,
            now_et=now_et,
            blog_url=blog_url,
        )
        x_raw = await _call_ollama_for_x(x_prompt)
        tweets = _parse_x_thread(x_raw)
        log.info("Generated X thread: %d tweets", len(tweets))
        if args.dry_run:
            print("\n--- X THREAD ---")
            for i, t in enumerate(tweets, 1):
                print(f"[{i}] ({len(t)} chars) {t}\n")
            print("--- END X THREAD ---\n")
        root_id = _post_x_thread(tweets, dry_run=args.dry_run)
        if root_id and not args.dry_run:
            log.info("X thread posted. Root tweet ID: %s", root_id)
        elif not args.dry_run and tweets:
            try:
                from src.health import PartialJobFailure  # noqa: E402
                raise PartialJobFailure("X thread was not posted (xdk unavailable or missing credentials)")
            except ImportError:
                pass

    log.info("Done.")


if __name__ == "__main__":
    import sys as _sys
    _args_preview = _sys.argv[1:]
    _mode = next(
        (_args_preview[i + 1] for i, a in enumerate(_args_preview) if a == "--mode" and i + 1 < len(_args_preview)),
        "unknown",
    )
    _job_name = f"blog_post_{_mode.replace('-', '_')}"  # blog_post_pre_market / blog_post_intra_market
    try:
        from src.health import JobHeartbeat
        with JobHeartbeat(_job_name, expected_interval=24.0):
            asyncio.run(main())
    except ImportError:
        asyncio.run(main())
