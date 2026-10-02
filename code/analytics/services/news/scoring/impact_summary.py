"""
IMPACT_SUMMARY head — the last head to run.

Every other head reads the article cold. This one reads what they produced
(claims and their novelty, per-ticker sentiment, relationships, the strongest
dimension scores) together with the latest priced-in reconstruction of each
affected company, and answers the question the others cannot: given what the
price already assumes, does this article change anything?

A headline that is "positive for NVDA" is worth nothing if the price already
pays for it. The reconstruction says what the price pays for and what it
declines to pay for, so the article can be placed against it: it confirms
an assumption the price already holds, challenges one, or carries
information the reconstruction never considered.

Storage (one ``news_impact_heads`` row, cluster ``IMPACT_SUMMARY``):
    scores    = {TICKER: impact in priced-in context, -1..+1}
    reasoning = {"_summary": overall read, TICKER: per-ticker read}
    meta      = {TICKER: {"relation", "assumption", "priced_in_as_of",
                          "priced_in_id"}}

Excluded from ``aggregate_heads`` (its keys are tickers, not dimensions) and
from ``head_carries_analysis`` (it summarises other heads, so it is never the
reason an article has analysis).
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import date, datetime
from typing import Awaitable, Callable, Optional

logger = logging.getLogger(__name__)

CLUSTER = "IMPACT_SUMMARY"
SUMMARY_KEY = "_summary"

# Tickers put in front of the model. Each one carries a reconstruction of a few
# hundred words; past three the prompt is mostly context for names the article
# only mentions in passing.
MAX_TICKERS = 3

# Below this |sentiment| a ticker is a mention, not an affected company.
MIN_SENTIMENT = 0.15

RELATIONS: tuple[str, ...] = ("confirms", "challenges", "new_information", "not_material")
# Set by the parser, never by the model: a ticker with no reconstruction has no
# assumption to confirm or challenge, and the model's guess at one is noise.
NO_RECONSTRUCTION = "no_reconstruction"

# A reconstruction is a loader result keyed by ticker. Injectable so tests and
# backfills can run without Supabase.
PricedInLoader = Callable[[list[str], Optional[date]], Awaitable[dict[str, dict]]]

_PRICED_IN_COLUMNS = (
    "id, ticker, as_of, price, n_targets, target_low, target_high, target_median, "
    "median_gap, implied_revenue_cagr, summary, summary_json, drivers_json"
)


# ── Affected tickers ──────────────────────────────────────────────────────────


def affected_tickers(prior_heads: list, limit: int = MAX_TICKERS) -> list[str]:
    """The companies the article is about, strongest sentiment first.

    TICKER_SENTIMENT is the source: it already decided which companies the
    article meaningfully affects. Relationship endpoints fill in only when the
    sentiment head found nothing — a supply-chain story can name two companies
    without being clearly good or bad for either.
    """
    by_cluster = {h.cluster: h for h in prior_heads if not getattr(h, "error", None)}

    sentiment = by_cluster.get("TICKER_SENTIMENT")
    ranked: list[str] = []
    if sentiment and sentiment.scores:
        ranked = [
            t
            for t, s in sorted(sentiment.scores.items(), key=lambda kv: abs(kv[1]), reverse=True)
            if abs(s) >= MIN_SENTIMENT
        ]

    if not ranked:
        rels = by_cluster.get("TICKER_RELATIONSHIPS")
        if rels and rels.scores:
            for key, _strength in sorted(rels.scores.items(), key=lambda kv: kv[1], reverse=True):
                parts = str(key).split("__")
                if len(parts) == 3:
                    for t in parts[:2]:
                        if t and t not in ranked:
                            ranked.append(t)

    return ranked[:limit]


# ── Priced-in lookup ──────────────────────────────────────────────────────────


def _as_date(value: object) -> Optional[date]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _fetch_priced_in_sync(tickers: list[str], as_of_max: Optional[date]) -> dict[str, dict]:
    from shared.db import get_supabase_client

    q = (
        get_supabase_client()
        .schema("swingtrader")
        .table("research_priced_in")
        .select(_PRICED_IN_COLUMNS)
        .in_("ticker", tickers)
        # The article page is public; so is everything it is put in context of.
        .eq("published", True)
    )
    # No lookahead: a reconstruction written after the article may already
    # contain its news, and then "is this priced in?" answers itself.
    if as_of_max is not None:
        q = q.lte("as_of", as_of_max.isoformat())
    # Same ordering as the quote page (lib/quote/priced-in.ts): created_at breaks
    # same-day ties toward the regenerated row.
    rows = q.order("as_of", desc=True).order("created_at", desc=True).limit(len(tickers) * 6).execute()

    latest: dict[str, dict] = {}
    for row in rows.data or []:
        t = str(row.get("ticker") or "").upper()
        if t and t not in latest:
            latest[t] = row
    return latest


async def load_priced_in(tickers: list[str], as_of_max: Optional[date]) -> dict[str, dict]:
    """Latest published reconstruction per ticker, as of ``as_of_max``. Never raises."""
    if not tickers:
        return {}
    try:
        return await asyncio.to_thread(_fetch_priced_in_sync, tickers, as_of_max)
    except Exception as exc:  # the summary still runs without it
        logger.warning("[impact_summary] priced-in lookup failed: %s", exc)
        return {}


# ── Prompt ────────────────────────────────────────────────────────────────────


def _fmt_num(v: object, fmt: str) -> Optional[str]:
    try:
        return format(float(v), fmt)
    except (TypeError, ValueError):
        return None


def _targets_trustworthy(row: dict) -> bool:
    """A median target 3x away from the price is a split inside the target
    window, not a view (see the nis-priced-in-story skill). The narrative is
    still usable; the numbers are not."""
    try:
        price = float(row["price"])
        median = float(row["target_median"])
        n = int(row.get("n_targets") or 0)
    except (KeyError, TypeError, ValueError):
        return False
    return n >= 5 and price > 0 and 1 / 3 <= median / price <= 3


def format_priced_in(ticker: str, row: Optional[dict]) -> str:
    if not row:
        return f"{ticker}: no priced-in reconstruction on file."

    lines = [f"{ticker} — reconstruction as of {row.get('as_of')}"]
    price = _fmt_num(row.get("price"), ".2f")
    if price and _targets_trustworthy(row):
        lines.append(
            f"  price ${price}; {row.get('n_targets')} analyst targets "
            f"${_fmt_num(row.get('target_low'), '.0f')}–${_fmt_num(row.get('target_high'), '.0f')}, "
            f"median ${_fmt_num(row.get('target_median'), '.0f')}"
        )
    cagr = _fmt_num(row.get("implied_revenue_cagr"), ".1%")
    if cagr:
        lines.append(f"  implied revenue CAGR (reverse DCF): {cagr}")

    parts = row.get("summary_json") if isinstance(row.get("summary_json"), dict) else None
    if parts:
        if parts.get("position"):
            lines.append(f"  position: {parts['position']}")
        for item in parts.get("pays_for") or []:
            lines.append(f"  price PAYS FOR: {item}")
        for item in parts.get("declines") or []:
            lines.append(f"  price DECLINES: {item}")
        if parts.get("crux"):
            lines.append(f"  crux: {parts['crux']}")
    elif row.get("summary"):
        lines.append(f"  summary: {str(row['summary'])[:1500]}")

    drivers = row.get("drivers_json") if isinstance(row.get("drivers_json"), list) else []
    for d in drivers[:6]:
        if isinstance(d, dict) and d.get("driver"):
            lines.append(f"  driver: {d['driver']}")
    return "\n".join(lines)


def format_prior_heads(prior_heads: list, tickers: list[str]) -> str:
    by_cluster = {h.cluster: h for h in prior_heads if not getattr(h, "error", None)}
    out: list[str] = []

    kp = by_cluster.get("STORY_KEY_POINTS")
    if kp and kp.reasoning:
        out.append("Key points (impact, novelty):")
        for kp_id, text in kp.reasoning.items():
            novelty = ((kp.meta or {}).get(kp_id) or {}).get("novelty", "?")
            out.append(f"  - [{kp.scores.get(kp_id, 0.0):+.2f}, {novelty}] {text}")

    sent = by_cluster.get("TICKER_SENTIMENT")
    if sent and sent.scores:
        out.append("Ticker sentiment:")
        for t, s in sorted(sent.scores.items(), key=lambda kv: abs(kv[1]), reverse=True)[:8]:
            out.append(f"  - {t} {s:+.2f}: {sent.reasoning.get(t, '')}")

    rels = by_cluster.get("TICKER_RELATIONSHIPS")
    if rels and rels.scores:
        out.append("Relationships:")
        for key, strength in sorted(rels.scores.items(), key=lambda kv: kv[1], reverse=True)[:6]:
            out.append(f"  - {key.replace('__', ' / ')} ({strength:.2f}): {rels.reasoning.get(key, '')}")

    from services.news.scoring.impact_scorer import aggregate_heads, top_dimensions

    dims = top_dimensions(aggregate_heads(prior_heads), n=6)
    if dims:
        out.append("Strongest company-type dimensions:")
        out.extend(f"  - {k} {v:+.2f}" for k, v in dims)

    return "\n".join(out) if out else "(no prior head produced output)"


SYSTEM = (
    "You are a buy-side analyst. You do not re-read news for whether it sounds good. "
    "You decide whether it changes what a stock's price already assumes. You are given "
    "the article, the structured analysis already extracted from it, and for each "
    "affected company a reconstruction of what its current price pays for and what it "
    "declines to pay for. Be concrete and conservative: good news the price already "
    "pays for is not a catalyst."
)

USER = """\
Headline: {title}
Published: {published}

Prior analysis of this article:
{prior}

Priced-in reconstructions:
{priced_in}

Article:
{article}

Task: put the article in the context of what each company's price already assumes.

For each ticker listed under "Priced-in reconstructions" decide:
- relation:
    confirms         the article supports an assumption the price already PAYS FOR — little news for the price
    challenges       the article cuts against something the price pays for, or supports something it DECLINES
    new_information  material for the company but neither assumed nor declined by the reconstruction
    not_material     the article does not touch anything the price depends on
- assumption: the specific pays-for / declines / crux item touched, quoted briefly ("" if none)
- impact: -1.0..+1.0, the effect on the price GIVEN what is priced in. Confirming an
  already-paid-for assumption is near 0 even if the news is positive. Supporting a declined
  assumption is positive; undermining a paid-for one is negative. Discount claims whose
  novelty is priced_in.
- read: one or two sentences tying the article's specific claim to the specific assumption.
  Use the article's and reconstruction's figures. Never invent a number.
  Write for a reader: never echo this prompt's labels ("PAYS FOR", "DECLINES", "crux",
  "reconstruction") — say "the price already assumes", "the market isn't paying for".
For a ticker with no reconstruction: give relation "new_information", assumption "",
and judge impact from the article and the prior analysis as any analyst would. Do NOT
mention the missing reconstruction in read or summary — the reader is told separately.

Then write summary: 2–3 sentences — what the article means for the affected names once
you account for what is already in their prices. Lead with the conclusion.

Return ONLY valid JSON:
{{
  "summary": "...",
  "tickers": [
    {{"ticker": "NVDA", "relation": "challenges", "assumption": "...", "impact": -0.3, "read": "..."}}
  ],
  "confidence": 0.8
}}
confidence = how clearly the article bears on what these prices assume (0.0–1.0)."""


def build_prompt(
    article_text: str,
    prior_heads: list,
    tickers: list[str],
    priced_in: dict[str, dict],
    *,
    title: Optional[str],
    published: str,
) -> str:
    blocks = "\n\n".join(format_priced_in(t, priced_in.get(t)) for t in tickers)
    return USER.format(
        title=(title or "").strip() or "(none)",
        published=published,
        prior=format_prior_heads(prior_heads, tickers),
        priced_in=blocks or "(no affected companies identified)",
        article=article_text[:5000],
    )


# ── Parse ─────────────────────────────────────────────────────────────────────


def parse_response(
    raw: str,
    tickers: list[str],
    priced_in: dict[str, dict],
) -> tuple[dict[str, float], dict[str, str], float, dict[str, dict]]:
    """(scores, reasoning, confidence, meta). Tickers outside ``tickers`` are
    dropped — the model only gets to speak about the names it was given context
    for, and those are already canonical."""
    from services.news.scoring.impact_scorer import _extract_json_object

    data = json.loads(_extract_json_object(raw))
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object, got {type(data).__name__}")

    confidence = max(0.0, min(1.0, float(data.get("confidence", 0.0) or 0.0)))
    allowed = set(tickers)

    scores: dict[str, float] = {}
    reasoning: dict[str, str] = {}
    meta: dict[str, dict] = {}

    summary = str(data.get("summary", "") or "").strip()
    if summary:
        reasoning[SUMMARY_KEY] = summary

    for item in data.get("tickers", []) or []:
        if not isinstance(item, dict):
            continue
        t = str(item.get("ticker", "")).upper().strip()
        if t not in allowed or t in scores:
            continue
        try:
            impact = max(-1.0, min(1.0, float(item.get("impact", 0.0))))
        except (TypeError, ValueError):
            impact = 0.0
        row = priced_in.get(t)
        relation = str(item.get("relation", "")).strip().lower()
        if not row:
            relation = NO_RECONSTRUCTION
        elif relation not in RELATIONS:
            relation = "not_material"

        scores[t] = impact
        reasoning[t] = str(item.get("read", "") or "").strip()
        entry: dict = {"relation": relation}
        assumption = str(item.get("assumption", "") or "").strip()
        if assumption and row and assumption.lower() not in ("unknown", "none", "n/a"):
            entry["assumption"] = assumption[:200]
        if row:
            entry["priced_in_as_of"] = str(row.get("as_of"))
            entry["priced_in_id"] = row.get("id")
        meta[t] = entry

    return scores, reasoning, confidence, meta


# ── Run ───────────────────────────────────────────────────────────────────────


async def run_impact_summary_head(
    article_text: str,
    prior_heads: list,
    *,
    title: Optional[str] = None,
    published_at: object = None,
    priced_in_loader: Optional[PricedInLoader] = None,
):
    """Run the summary over ``prior_heads``. Must be called after they finish."""
    from services.news.scoring.impact_scorer import (
        HeadOutput,
        LLMError,
        _chat,
        _default_model,
        _default_timeout,
        _get_semaphore,
        _published_label,
    )

    model = _default_model()

    def _empty(error: str, raw: str = "", latency_ms: int = 0) -> HeadOutput:
        return HeadOutput(
            cluster=CLUSTER, scores={}, reasoning={}, confidence=0.0,
            model=model, latency_ms=latency_ms, raw_response=raw, error=error,
        )

    # A rescore can hand back the previous summary among the stored heads.
    prior_heads = [h for h in prior_heads if h.cluster != CLUSTER]
    if not any(not h.error and (h.scores or h.reasoning) for h in prior_heads):
        return _empty("no prior head output to summarise")

    tickers = affected_tickers(prior_heads)
    loader = priced_in_loader or load_priced_in
    priced_in = await loader(tickers, _as_date(published_at)) if tickers else {}

    prompt = build_prompt(
        article_text, prior_heads, tickers, priced_in,
        title=title, published=_published_label(published_at),
    )

    async with _get_semaphore():
        try:
            raw, latency_ms = await _chat(
                prompt=prompt, system=SYSTEM, model=model, timeout=_default_timeout()
            )
        except LLMError as exc:
            logger.warning("[impact_scorer] %s head failed: %s", CLUSTER, exc)
            return _empty(str(exc))

    try:
        scores, reasoning, confidence, meta = parse_response(raw, tickers, priced_in)
    except (json.JSONDecodeError, KeyError, ValueError, TypeError) as exc:
        logger.warning("[impact_scorer] %s parse error: %s | raw=%r", CLUSTER, exc, raw[:200])
        return _empty(f"parse error: {exc}", raw, latency_ms)

    return HeadOutput(
        cluster=CLUSTER,
        scores=scores,
        reasoning=reasoning,
        confidence=confidence,
        model=model,
        latency_ms=latency_ms,
        raw_response=raw,
        meta=meta,
    )
