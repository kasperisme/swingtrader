#!/usr/bin/env python3
"""
generate_blog_post.py — Auto-generate and publish news impact blog posts to Sanity.

Queries the Supabase swingtrader schema for recently scored news articles,
uses the local Ollama instance to write a structured analysis post, then
publishes it to the newsimpactscreener Sanity project (project ID: y2lg8a3c).

Modes:
  pre-market   — looks back 14 h (overnight news), run at 08:30 ET weekdays
  intra-market — looks back  6 h (morning session), run at 14:30 ET weekdays

Usage:
  python scripts/generate_blog_post.py --mode pre-market
  python scripts/generate_blog_post.py --mode intra-market
  python scripts/generate_blog_post.py --mode pre-market --dry-run

Required env vars (analytics/.env):
  SUPABASE_URL, SUPABASE_KEY, SUPABASE_SCHEMA
  SANITY_TOKEN   — Sanity write token (Editor role or above)

Optional env vars:
  SANITY_PROJECT_ID      (default: y2lg8a3c)
  SANITY_DATASET         (default: production)
  OLLAMA_BASE_URL        (default: http://localhost:11434)
  OLLAMA_BLOG_MODEL      (default: OLLAMA_IMPACT_MODEL → gemma4:e4b)
  NEWS_LOOKBACK_HOURS    (override default per mode)
  NEWS_MAX_ARTICLES      (default: 20 — max articles pulled for analysis)
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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SANITY_PROJECT_ID = os.environ.get("SANITY_PROJECT_ID", "y2lg8a3c")
SANITY_DATASET    = os.environ.get("SANITY_DATASET", "production")
SANITY_API_VER    = "2021-06-07"
SANITY_TOKEN      = os.environ.get("SANITY_TOKEN", "")

AUTHOR_ID = "81d00698-faa2-4dc7-81b8-bec6ec3b8884"

CATEGORY_IDS = {
    "pre-market":    "1ca18181-78f8-4c58-8bf8-e9acc1c8c127",
    "intra-market":  "3dcae939-2a2f-4768-aee0-adefd45f9f54",
    "news-impact":   "728b9f28-2c16-4984-8764-c765fa27fa92",
}

LOOKBACK_HOURS = {
    "pre-market":   14,
    "intra-market":  6,
}

EASTERN_TZ_OFFSET = timedelta(hours=-4)  # EDT; use -5 for EST (standard)

# ---------------------------------------------------------------------------
# Supabase helpers
# ---------------------------------------------------------------------------

def _fetch_recent_articles(mode: str, lookback_hours: int, max_articles: int) -> list[dict]:
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
    vectors_by_id: dict[int, dict] = {
        v["article_id"]: v for v in (vec_res.data or [])
    }

    # Attach impact data and filter to articles that have been scored
    enriched = []
    for a in articles:
        vec = vectors_by_id.get(a["id"])
        if vec is None:
            continue  # not yet scored — skip
        enriched.append({
            **a,
            "impact_json":    _as_json(vec["impact_json"], default={}),
            "top_dimensions": _as_json(vec["top_dimensions"], default=[]),
        })

    log.info("Fetched %d scored articles (of %d total in window).", len(enriched), len(articles))
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
    for row in (res.data or []):
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
    return [t for t, _ in sorted(ticker_weight.items(), key=lambda x: x[1], reverse=True)[:n]]


def _fmt_dim(dim: str) -> str:
    """Convert snake_case dimension to Title Case display label."""
    return dim.replace("_", " ").title()


def _fmt_score(score: float) -> str:
    sign = "+" if score >= 0 else ""
    return f"{sign}{score:.2f}"


# ---------------------------------------------------------------------------
# Ollama blog post generation
# ---------------------------------------------------------------------------

def _build_prompt(mode: str, articles: list[dict], tickers_map: dict[int, list[str]], company_meta: dict[str, dict], now_et: datetime) -> str:
    """Build the user prompt for the Anthropic blog post generation call."""

    date_str = now_et.strftime("%A, %B %-d")
    period_label = "Pre-Market" if mode == "pre-market" else "Intra-Market"

    # Top 5 articles by impact magnitude
    ranked = sorted(articles, key=lambda a: _impact_magnitude(a.get("impact_json") or {}), reverse=True)[:5]

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
        name   = meta.get("name") or t
        sector = meta.get("sector") or "Unknown sector"
        industry = meta.get("industry") or ""
        tickers_block += f"  - {t} ({name}) — {sector}" + (f", {industry}" if industry else "") + "\n"

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


def _block(children: list[dict], style: str = "normal", mark_defs: Optional[list] = None) -> dict:
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
    mode: str,
    published_at: str,
    dry_run: bool = False,
) -> Optional[str]:
    """Create and immediately publish a post to Sanity. Returns the document ID."""
    if not SANITY_TOKEN:
        raise RuntimeError("SANITY_TOKEN is not set in .env")

    doc_id = f"blog-auto-{uuid.uuid4().hex[:16]}"
    slug   = _slug_from_title(title)

    category_refs = [
        {"_type": "reference", "_ref": CATEGORY_IDS[mode], "_key": _key()},
        {"_type": "reference", "_ref": CATEGORY_IDS["news-impact"], "_key": _key()},
    ]

    body_blocks = _markdown_to_portable_text(body_markdown)

    document = {
        "_id":         doc_id,
        "_type":       "post",
        "title":       title,
        "slug":        {"_type": "slug", "current": slug},
        "author":      {"_type": "reference", "_ref": AUTHOR_ID},
        "categories":  category_refs,
        "publishedAt": published_at,
        "body":        body_blocks,
    }

    mutations = [{"createOrReplace": document}]

    url = f"https://{SANITY_PROJECT_ID}.api.sanity.io/v{SANITY_API_VER}/data/mutate/{SANITY_DATASET}"
    headers = {
        "Authorization": f"Bearer {SANITY_TOKEN}",
        "Content-Type":  "application/json",
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
# Main
# ---------------------------------------------------------------------------

async def main() -> None:
    parser = argparse.ArgumentParser(description="Auto-generate Sanity blog post from Supabase news impact data")
    parser.add_argument("--mode", choices=["pre-market", "intra-market"], required=True)
    parser.add_argument("--dry-run", action="store_true", help="Build and log the post without publishing")
    parser.add_argument("--lookback-hours", type=int, default=None, help="Override default lookback window")
    parser.add_argument("--max-articles", type=int, default=int(os.environ.get("NEWS_MAX_ARTICLES", 20)))
    args = parser.parse_args()

    lookback = args.lookback_hours or int(os.environ.get("NEWS_LOOKBACK_HOURS", LOOKBACK_HOURS[args.mode]))

    now_utc = datetime.now(timezone.utc)
    now_et  = now_utc + EASTERN_TZ_OFFSET  # approximate ET

    log.info("Mode: %s | Lookback: %d h | Now ET: %s", args.mode, lookback, now_et.strftime("%Y-%m-%d %H:%M"))

    # 1. Pull data from Supabase
    articles = _fetch_recent_articles(args.mode, lookback, args.max_articles)
    if not articles:
        log.warning("No scored articles found — skipping blog post generation.")
        sys.exit(0)

    article_ids = [a["id"] for a in articles]
    tickers_map  = _fetch_tickers_for_articles(article_ids)

    all_tickers = list({t for ts in tickers_map.values() for t in ts})
    top_tickers = _top_tickers(tickers_map, articles, n=8)
    company_meta = _fetch_company_metadata(top_tickers)

    log.info("Articles: %d | Unique tickers: %d", len(articles), len(all_tickers))

    # 2. Generate blog post via Ollama
    prompt = _build_prompt(args.mode, articles, tickers_map, company_meta, now_et)
    body_markdown = await _call_ollama(prompt)

    # 3. Build title
    period_label = "Pre-Market" if args.mode == "pre-market" else "Intra-Market"
    date_str = now_et.strftime("%b %-d")
    title = f"{period_label} News Impact: {date_str}"

    log.info("Generated post: %r (%d chars)", title, len(body_markdown))
    if args.dry_run:
        print("\n" + "=" * 60)
        print(f"TITLE: {title}")
        print("=" * 60)
        print(body_markdown)
        print("=" * 60 + "\n")

    # 4. Publish to Sanity
    doc_id = _publish_to_sanity(
        title=title,
        body_markdown=body_markdown,
        mode=args.mode,
        published_at=now_utc.isoformat(),
        dry_run=args.dry_run,
    )

    log.info("Done. Sanity document ID: %s", doc_id)


if __name__ == "__main__":
    asyncio.run(main())
