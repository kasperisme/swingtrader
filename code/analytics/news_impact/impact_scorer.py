"""
Impact scorer — runs 8 parallel LLM heads (one per cluster) and aggregates
scores into a single impact vector.

Each head is independent; a failure in one never blocks the others.
"""

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Optional

from news_impact.dimensions import CLUSTERS, DIMENSION_MAP
from news_impact.ollama_client import chat as _ollama_chat, OllamaError
from news_impact.anthropic_client import chat as _anthropic_chat, AnthropicError

# Select backend via NEWS_IMPACT_BACKEND=ollama (default) | anthropic
_BACKEND = os.environ.get("NEWS_IMPACT_BACKEND", "ollama").lower()

LLMError = OllamaError if _BACKEND != "anthropic" else AnthropicError


def set_news_impact_backend(backend: str) -> None:
    """
    Override the LLM backend for this process (``ollama`` or ``anthropic``).

    Updates ``os.environ[\"NEWS_IMPACT_BACKEND\"]`` so downstream code agrees.
    Used by ``score_news_cli --news-impact-backend``.
    """
    global _BACKEND, LLMError
    b = backend.strip().lower()
    if b not in ("ollama", "anthropic"):
        raise ValueError("NEWS_IMPACT_BACKEND must be 'ollama' or 'anthropic'")
    os.environ["NEWS_IMPACT_BACKEND"] = b
    _BACKEND = b
    LLMError = OllamaError if _BACKEND != "anthropic" else AnthropicError


async def _chat(prompt: str, system: str, model: Optional[str], timeout: float) -> tuple[str, int]:
    if _BACKEND == "anthropic":
        return await _anthropic_chat(prompt=prompt, system=system, model=model, timeout=timeout)
    return await _ollama_chat(prompt=prompt, system=system, model=model, timeout=timeout)


def _default_model() -> str:
    if _BACKEND == "anthropic":
        return os.environ.get("ANTHROPIC_IMPACT_MODEL", "claude-haiku-4-5-20251001")
    return os.environ.get("OLLAMA_IMPACT_MODEL", "devstral")


def _default_timeout() -> float:
    if _BACKEND == "anthropic":
        return float(os.environ.get("ANTHROPIC_TIMEOUT", "60"))
    return float(os.environ.get("OLLAMA_TIMEOUT", "120"))

logger = logging.getLogger(__name__)

# Ollama processes one request at a time on a single GPU. Running all 8 heads
# in parallel fills the queue and causes later ones to time out.
# Limit concurrency to 1 (sequential) by default; raise via OLLAMA_CONCURRENCY.
_CONCURRENCY = int(os.environ.get("OLLAMA_CONCURRENCY", "1"))
_sem: asyncio.Semaphore | None = None   # created lazily inside the running loop


def _get_semaphore() -> asyncio.Semaphore:
    global _sem
    if _sem is None:
        _sem = asyncio.Semaphore(_CONCURRENCY)
    return _sem


# Human-readable cluster labels for the system prompt
_CLUSTER_LABELS: dict[str, str] = {
    "MACRO_SENSITIVITY":    "macro-economic sensitivity",
    "SECTOR_ROTATION":      "sector rotation and GICS classification",
    "BUSINESS_MODEL":       "business model characteristics",
    "FINANCIAL_STRUCTURE":  "financial structure and balance sheet risk",
    "GROWTH_PROFILE":       "growth profile and earnings quality",
    "VALUATION_POSITIONING":"valuation and market positioning",
    "GEOGRAPHY_TRADE":      "geographic exposure and trade policy",
    "MARKET_BEHAVIOUR":     "market microstructure and institutional behaviour",
    "TICKER_RELATIONSHIPS": "inter-company relationships and supply chain links",
}

_SYSTEM_TEMPLATE = """\
You are a financial analyst specialising in {cluster_label}.
You assess how macro and company news affects different types of companies.
Be precise and conservative. Only score dimensions where the article has a
clear, direct implication. Most scores should be zero or omitted entirely."""

_USER_TEMPLATE = """\
Analyse how the following article affects companies that score HIGH on each dimension below.

Scale: -1.0 (very negative impact on this type of company)
        0.0  (no meaningful impact)
       +1.0  (very positive impact on this type of company)

Omit any dimension where |impact| < 0.1.

Dimensions:
{dimensions_block}

Article:
{article}

Return ONLY valid JSON, no markdown, no explanation outside the JSON:
{{
  "scores": {{"dimension_key": float}},
  "reasoning": {{"dimension_key": "one sentence"}},
  "confidence": float
}}

confidence = how relevant is this cluster to the article (0.0 to 1.0).
If the article is unrelated to this cluster, return confidence: 0.0 and empty scores."""

_FENCE_RE   = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)
_PLUS_RE    = re.compile(r'(?<!["\w])\+(\d)')   # strip leading + from JSON numbers


@dataclass
class HeadOutput:
    cluster:      str
    scores:       dict[str, float]
    reasoning:    dict[str, str]
    confidence:   float
    model:        str
    latency_ms:   int
    raw_response: str
    error:        Optional[str] = None


def _build_dimensions_block(cluster: str) -> str:
    dims = CLUSTERS.get(cluster, [])
    return "\n".join(
        f"  {d['key']} — {d['description']}"
        for d in dims
    )


def _extract_scores_partial(raw: str) -> dict:
    """
    Fallback: pull the "scores" object out of a truncated JSON string using
    a regex so we don't lose the important part when reasoning overruns the
    token budget and cuts the response mid-string.
    """
    m = re.search(r'"scores"\s*:\s*(\{[^}]+\})', raw)
    if not m:
        return {}
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return {}


def _extract_json_object(raw: str) -> str:
    """
    Best-effort normalization for LLM JSON responses:
    - remove markdown fences
    - strip illegal leading '+' on JSON numbers
    - keep only text through the last closing brace to drop trailing commentary
    """
    cleaned = _FENCE_RE.sub("", raw).strip()
    cleaned = _PLUS_RE.sub(r"\1", cleaned)
    brace = cleaned.rfind("}")
    if brace != -1:
        cleaned = cleaned[: brace + 1]
    return cleaned


def _parse_head_response(raw: str, cluster: str) -> tuple[dict, dict, float]:
    """
    Parse JSON from LLM response.  Strips markdown fences, validates keys/ranges.
    Returns (scores, reasoning, confidence).

    If the full JSON is malformed (e.g. truncated mid-reasoning), falls back to
    regex extraction of the scores block so partial results are not lost.
    """
    cleaned = _extract_json_object(raw)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        # Try to salvage scores from truncated response
        partial_scores = _extract_scores_partial(cleaned)
        if partial_scores:
            logger.debug("[impact_scorer] %s: truncated JSON — recovered scores via regex", cluster)
            data = {"scores": partial_scores, "reasoning": {}, "confidence": 0.5}
        else:
            raise  # nothing to salvage; let the caller handle it

    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object, got {type(data).__name__}: {cleaned[:100]}")

    raw_scores    = data.get("scores",    {})
    raw_reasoning = data.get("reasoning", {})
    # Guard against the LLM returning a string or list instead of an object
    if not isinstance(raw_scores,    dict): raw_scores    = {}
    if not isinstance(raw_reasoning, dict): raw_reasoning = {}
    confidence   = float(data.get("confidence", 0.0))
    confidence   = max(0.0, min(1.0, confidence))

    valid_keys = {d["key"] for d in CLUSTERS.get(cluster, [])}

    scores: dict[str, float] = {}
    for k, v in raw_scores.items():
        if k not in DIMENSION_MAP:
            logger.debug("[impact_scorer] unknown dimension key %r — skipping", k)
            continue
        if k not in valid_keys:
            logger.debug("[impact_scorer] key %r not in cluster %s — skipping", k, cluster)
            continue
        scores[k] = max(-1.0, min(1.0, float(v)))

    reasoning: dict[str, str] = {
        k: str(v) for k, v in raw_reasoning.items() if k in valid_keys
    }

    return scores, reasoning, confidence


async def _run_head(article_text: str, cluster: str) -> HeadOutput:
    """Run a single cluster head, respecting the global concurrency semaphore."""
    model   = _default_model()
    timeout = _default_timeout()

    system = _SYSTEM_TEMPLATE.format(
        cluster_label=_CLUSTER_LABELS.get(cluster, cluster.lower()),
    )
    user = _USER_TEMPLATE.format(
        dimensions_block=_build_dimensions_block(cluster),
        article=article_text[:6000],
    )

    async with _get_semaphore():
        try:
            raw, latency_ms = await _chat(prompt=user, system=system, model=model, timeout=timeout)
        except LLMError as exc:
            logger.warning("[impact_scorer] %s head failed: %s", cluster, exc)
            return HeadOutput(
                cluster=cluster, scores={}, reasoning={},
                confidence=0.0, model=model, latency_ms=0,
                raw_response="", error=str(exc),
            )

        try:
            scores, reasoning, confidence = _parse_head_response(raw, cluster)
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            logger.warning(
                "[impact_scorer] %s JSON parse error: %s | raw=%r", cluster, exc, raw[:200]
            )
            return HeadOutput(
                cluster=cluster, scores={}, reasoning={},
                confidence=0.0, model=model, latency_ms=latency_ms,
                raw_response=raw, error=f"parse error: {exc}",
            )

        return HeadOutput(
            cluster=cluster,
            scores=scores,
            reasoning=reasoning,
            confidence=confidence,
            model=model,
            latency_ms=latency_ms,
            raw_response=raw,
        )


# ── Ticker relationship head ──────────────────────────────────────────────────

_REL_SYSTEM = (
    "You are a financial analyst specialising in inter-company relationships, "
    "supply chains, and competitive dynamics. "
    "Identify only relationships that are clearly supported by the article text."
)

_REL_USER = """\
Analyse the article and identify relationships between publicly traded companies mentioned.

Relationship types:
  competitor  — directly compete for the same customers / market
  supplier    — one company supplies goods or services to the other
  customer    — one company is a significant customer of the other
  partner     — strategic partnership, joint venture, or licensing deal
  acquirer    — one company is acquiring or has acquired the other
  subsidiary  — one company is a subsidiary / division of the other

For each relationship also provide:
  strength  — 0.0 (weak / indirect) to 1.0 (primary / core relationship)
  direction — "a_to_b" means `from` supplies/sells/acquires `to`;
               "b_to_a" means the reverse;
               "mutual"  for symmetric relationships (e.g. competitors, partners)
  notes     — one sentence explaining the relationship as shown in the article

Article:
{article}

Return ONLY valid JSON, no markdown:
{{
  "relationships": [
    {{
      "from": "TICKER_A",
      "to":   "TICKER_B",
      "type": "competitor|supplier|customer|partner|acquirer|subsidiary",
      "strength": 0.85,
      "direction": "a_to_b|b_to_a|mutual",
      "notes": "TICKER_A supplies advanced chips to TICKER_B for its AI servers."
    }}
  ],
  "confidence": 0.0
}}

Rules:
- Include any publicly traded company regardless of exchange or country (NYSE, NASDAQ, LSE, Euronext, TSE, HKEX, etc.).
- Use the company's primary ticker on its home exchange (e.g. "ASML" for ASML on Euronext, "7203" for Toyota on TSE). For companies with multiple listings, prefer the most liquid ticker.
- Only include relationships clearly evidenced by the article.
- Return {{"relationships": [], "confidence": 0.0}} if fewer than 2 companies are mentioned
  or no relationships are evident.
- confidence = how clearly the article reveals inter-company relationships (0.0–1.0)."""


def _parse_relationship_response(raw: str) -> tuple[dict[str, float], dict[str, str], float]:
    """
    Parse the relationship head response.
    Returns (scores, reasoning, confidence) where scores uses composite keys:
      "<FROM>__<TO>__<type>" → strength (float)
    and reasoning uses the same keys → notes (str).
    """
    cleaned = _extract_json_object(raw)
    data = json.loads(cleaned)
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object, got {type(data).__name__}")

    confidence = float(data.get("confidence", 0.0))
    confidence = max(0.0, min(1.0, confidence))

    scores:    dict[str, float] = {}
    reasoning: dict[str, str]   = {}

    for rel in data.get("relationships", []):
        frm      = str(rel.get("from", "")).upper().strip()
        to       = str(rel.get("to",   "")).upper().strip()
        rel_type = str(rel.get("type", "unknown")).lower().strip()
        strength = float(rel.get("strength", 0.5))
        strength = max(0.0, min(1.0, strength))
        notes    = str(rel.get("notes", ""))
        direction = str(rel.get("direction", "mutual")).lower().strip()

        if not frm or not to:
            continue

        key = f"{frm}__{to}__{rel_type}"
        scores[key]    = strength
        reasoning[key] = f"[{direction}] {notes}"

    return scores, reasoning, confidence


async def _run_relationship_head(article_text: str) -> HeadOutput:
    """Run the ticker-relationship head. Uses its own prompt and parser."""
    model   = _default_model()
    timeout = _default_timeout()

    prompt = _REL_USER.format(article=article_text[:6000])

    async with _get_semaphore():
        try:
            raw, latency_ms = await _chat(prompt=prompt, system=_REL_SYSTEM, model=model, timeout=timeout)
        except LLMError as exc:
            logger.warning("[impact_scorer] TICKER_RELATIONSHIPS head failed: %s", exc)
            return HeadOutput(
                cluster="TICKER_RELATIONSHIPS", scores={}, reasoning={},
                confidence=0.0, model=model, latency_ms=0,
                raw_response="", error=str(exc),
            )

    try:
        scores, reasoning, confidence = _parse_relationship_response(raw)
    except (json.JSONDecodeError, KeyError, ValueError) as exc:
        logger.warning(
            "[impact_scorer] TICKER_RELATIONSHIPS parse error: %s | raw=%r", exc, raw[:200]
        )
        return HeadOutput(
            cluster="TICKER_RELATIONSHIPS", scores={}, reasoning={},
            confidence=0.0, model=model, latency_ms=latency_ms,
            raw_response=raw, error=f"parse error: {exc}",
        )

    return HeadOutput(
        cluster="TICKER_RELATIONSHIPS",
        scores=scores,
        reasoning=reasoning,
        confidence=confidence,
        model=model,
        latency_ms=latency_ms,
        raw_response=raw,
    )


# ── Ticker sentiment head ─────────────────────────────────────────────────────

_SENTIMENT_SYSTEM = (
    "You are a financial analyst. "
    "For each publicly traded company mentioned in a news article, assess whether "
    "the article is positive, negative, or neutral for that specific company."
)

_SENTIMENT_USER = """\
Read the article and score the sentiment for every publicly traded company mentioned.

Scale:
  -1.0  very negative for this company (bad news, headwinds, losses)
   0.0  neutral / not meaningfully affected
  +1.0  very positive for this company (good news, tailwinds, gains)

For each company also write one sentence explaining why.

Article:
{article}

Return ONLY valid JSON, no markdown:
{{
  "sentiments": [
    {{
      "ticker": "AAPL",
      "score": 0.75,
      "reason": "Apple named as key beneficiary of the new trade deal."
    }}
  ],
  "confidence": 0.9
}}

Rules:
- Include any publicly traded company regardless of exchange or country.
- Use the company's primary ticker on its home exchange.
- Omit companies where |score| < 0.05 (truly neutral — no meaningful mention).
- confidence = how clearly the article expresses sentiment toward specific companies (0.0–1.0).
- Return {{"sentiments": [], "confidence": 0.0}} if no companies are meaningfully mentioned."""


def _parse_sentiment_response(raw: str) -> tuple[dict[str, float], dict[str, str], float]:
    """
    Parse the ticker-sentiment head response.
    Returns (scores, reasoning, confidence) where scores = {ticker: sentiment_float}.
    """
    cleaned = _extract_json_object(raw)
    data = json.loads(cleaned)
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object, got {type(data).__name__}")

    confidence = float(data.get("confidence", 0.0))
    confidence = max(0.0, min(1.0, confidence))

    scores:    dict[str, float] = {}
    reasoning: dict[str, str]   = {}

    for item in data.get("sentiments", []):
        ticker = str(item.get("ticker", "")).upper().strip()
        score  = float(item.get("score", 0.0))
        reason = str(item.get("reason", ""))
        if not ticker:
            continue
        scores[ticker]    = max(-1.0, min(1.0, score))
        reasoning[ticker] = reason

    return scores, reasoning, confidence


async def _run_sentiment_head(article_text: str) -> HeadOutput:
    """Run the per-ticker sentiment head."""
    model   = _default_model()
    timeout = _default_timeout()

    prompt = _SENTIMENT_USER.format(article=article_text[:6000])

    async with _get_semaphore():
        try:
            raw, latency_ms = await _chat(prompt=prompt, system=_SENTIMENT_SYSTEM, model=model, timeout=timeout)
        except LLMError as exc:
            logger.warning("[impact_scorer] TICKER_SENTIMENT head failed: %s", exc)
            return HeadOutput(
                cluster="TICKER_SENTIMENT", scores={}, reasoning={},
                confidence=0.0, model=model, latency_ms=0,
                raw_response="", error=str(exc),
            )

    try:
        scores, reasoning, confidence = _parse_sentiment_response(raw)
    except (json.JSONDecodeError, KeyError, ValueError) as exc:
        logger.warning(
            "[impact_scorer] TICKER_SENTIMENT parse error: %s | raw=%r", exc, raw[:200]
        )
        return HeadOutput(
            cluster="TICKER_SENTIMENT", scores={}, reasoning={},
            confidence=0.0, model=model, latency_ms=latency_ms,
            raw_response=raw, error=f"parse error: {exc}",
        )

    return HeadOutput(
        cluster="TICKER_SENTIMENT",
        scores=scores,
        reasoning=reasoning,
        confidence=confidence,
        model=model,
        latency_ms=latency_ms,
        raw_response=raw,
    )


# ── Ticker extraction ─────────────────────────────────────────────────────────

_EXTRACT_SYSTEM = (
    "You are a financial data extraction assistant. "
    "Extract only publicly listed company ticker symbols explicitly mentioned or "
    "clearly implied in the article. Do not infer or add companies not referenced."
)

_EXTRACT_USER = """\
List the ticker symbols for every publicly traded company mentioned in the article below.

Rules:
- Include companies listed on any exchange worldwide (NYSE, NASDAQ, LSE, Euronext, TSE, HKEX, etc.).
- Use the primary ticker on the company's home exchange (e.g. "ASML" for ASML, "7203" for Toyota).
- If a company name is mentioned but you are not confident of its ticker, omit it.
- Return ONLY valid JSON, no markdown:
{{"tickers": ["AAPL", "ASML", "7203"]}}
- Return {{"tickers": []}} if no companies are mentioned.

Article:
{article}"""


async def extract_tickers(article_text: str) -> list[str]:
    """
    Use the LLM to extract US ticker symbols mentioned in the article.
    Returns a (possibly empty) list of uppercase ticker strings.
    Never raises — returns [] on any failure.
    """
    model   = _default_model()
    timeout = _default_timeout()
    prompt  = _EXTRACT_USER.format(article=article_text[:4000])
    try:
        async with _get_semaphore():
            raw, _ = await _chat(prompt=prompt, system=_EXTRACT_SYSTEM, model=model, timeout=timeout)
        cleaned = _extract_json_object(raw)
        data    = json.loads(cleaned)
        tickers = [str(t).upper().strip() for t in data.get("tickers", []) if t]
        tickers = [t for t in tickers if re.fullmatch(r"[A-Z0-9]{1,8}(\.[A-Z]{1,2})?", t)]
        return tickers
    except Exception as exc:
        logger.warning("[impact_scorer] ticker extraction failed: %s", exc)
        return []


async def score_article(article_text: str) -> list[HeadOutput]:
    """
    Run all cluster heads plus the ticker-relationship head in parallel.

    Always returns one HeadOutput per cluster (including TICKER_RELATIONSHIPS).
    Failed heads have error set and confidence=0.0 with empty scores.
    """
    cluster_tasks = [_run_head(article_text, cluster) for cluster in CLUSTERS]
    all_tasks = cluster_tasks + [_run_relationship_head(article_text), _run_sentiment_head(article_text)]
    all_clusters = list(CLUSTERS.keys()) + ["TICKER_RELATIONSHIPS", "TICKER_SENTIMENT"]

    results = await asyncio.gather(*all_tasks, return_exceptions=True)

    outputs: list[HeadOutput] = []
    for cluster, result in zip(all_clusters, results):
        if isinstance(result, Exception):
            logger.error("[impact_scorer] unexpected exception in %s: %s", cluster, result)
            outputs.append(HeadOutput(
                cluster=cluster, scores={}, reasoning={},
                confidence=0.0,
                model=_default_model(),
                latency_ms=0, raw_response="",
                error=str(result),
            ))
        else:
            outputs.append(result)

    return outputs


def aggregate_heads(head_outputs: list[HeadOutput]) -> dict[str, float]:
    """
    Merge all head scores into a single impact vector.

    Each score is weighted by the head's confidence.
    Dimensions appearing in multiple heads are averaged.
    Dimensions with zero total confidence weight are omitted.

    TICKER_RELATIONSHIPS heads are excluded — their scores are ticker-pair
    keys, not impact dimensions, and are stored separately in scores_json.
    """
    weighted_sum: dict[str, float] = {}
    weight_total: dict[str, float] = {}

    for head in head_outputs:
        if head.cluster in ("TICKER_RELATIONSHIPS", "TICKER_SENTIMENT"):
            continue
        if head.confidence <= 0.0 or not head.scores:
            continue
        for dim, score in head.scores.items():
            weighted_sum[dim] = weighted_sum.get(dim, 0.0) + score * head.confidence
            weight_total[dim] = weight_total.get(dim, 0.0) + head.confidence

    impact: dict[str, float] = {}
    for dim, total_w in weight_total.items():
        if total_w > 0:
            impact[dim] = weighted_sum[dim] / total_w

    return impact


def top_dimensions(
    impact: dict[str, float],
    n: int = 5,
) -> list[tuple[str, float]]:
    """Return top N dimensions by abs(score), sorted descending."""
    return sorted(impact.items(), key=lambda x: abs(x[1]), reverse=True)[:n]


if __name__ == "__main__":
    import asyncio
    import pathlib
    from dotenv import load_dotenv

    load_dotenv(pathlib.Path(__file__).parent.parent / ".env")

    _DEMO_ARTICLE = (
        "The Federal Reserve raised interest rates by 50 basis points today, "
        "surprising markets that had expected only 25bps. Chair Powell signalled "
        "further hikes ahead to combat persistent inflation. Treasury yields surged "
        "and bank stocks rallied while growth stocks sold off sharply."
    )

    async def _demo():
        heads = await score_article(_DEMO_ARTICLE)
        print(f"\nScored {len(heads)} cluster heads:")
        for h in sorted(heads, key=lambda x: x.confidence, reverse=True):
            status = f"ERR({h.error})" if h.error else f"conf={h.confidence:.2f}"
            print(f"  {h.cluster:<24} {status}  scores={h.scores}")
        impact = aggregate_heads(heads)
        print(f"\nAggregated impact vector ({len(impact)} dims):")
        for dim, score in top_dimensions(impact, n=10):
            bar = "+" if score > 0 else ""
            print(f"  {dim:<40} {bar}{score:.3f}")

    asyncio.run(_demo())
