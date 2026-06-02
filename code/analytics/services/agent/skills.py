"""
skills.py — predefined screening skills for the multi-ticker pipeline.

A ``ScreeningSkill`` is a hardcoded, pre-validated recipe for one *kind* of
screening (news impact, breakout, portfolio rundown, …). It replaces the
per-run LLM planner on the happy path: the only thing a model decides is which
skill id a prompt maps to (``classify_skill``). Everything downstream is fixed:

  1. FETCH    — ``tool_plan`` is a literal string of tool calls (internal RAG
                tools AND FMP tools), args + enums baked in. The model never
                picks tools or endpoints.
  2. COMPUTE  — ``analytics(ticker, tool_data)`` is pure Python. It turns raw
                tool output into a ``TickerSignal`` with computed metrics and,
                where the data is unambiguous, a deterministic verdict.
  3. JUDGE    — only tickers whose ``TickerSignal.needs_llm`` is True are sent
                to the per-ticker LLM evaluator (``eval_focus`` tunes it). Clear
                yes/no cases are resolved in step 2 with no LLM cost.
  4. VERDICT  — the pipeline's stage-3 concluder (LLM) synthesises the overall
                {triggered, summary} from the per-ticker verdicts.

Skills stand on a statically-guaranteed internal floor (``requires`` lists only
internal RAG tools). FMP calls are best-effort: the multi-ticker pipeline drops
any FMP tool that's unknown to the registry or fails a trial probe, and the
analytics layer degrades gracefully (escalating to the LLM) when price data is
absent. Run ``python -m services.agent.cli validate-skills`` after an FMP plan
change to see which skills' FMP calls are actually live.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable

import httpx

from services.agent_core import ToolRegistry, simple_chat

log = logging.getLogger(__name__)

_TICKER_PLACEHOLDER = "{TICKER}"

# Breakout: how many trailing bars define the "recent high" the price is
# measured against, and the trigger thresholds. Kept here so the deterministic
# layer and the docs agree.
_BREAKOUT_LOOKBACK = 20
_NEAR_HIGH_PCT = -2.0   # within 2% of the lookback high
_FAR_BELOW_PCT = -8.0   # clearly off the highs → not a breakout
_VOLUME_SURGE = 1.5     # latest volume ≥ 1.5× trailing average

# Internal RAG tool names. Anything in a skill's tool_plan NOT in this set is
# treated as an external (FMP) call — used by the price extractor to know which
# tool results may carry OHLC bars without hardcoding FMP's exact tool name.
_INTERNAL_TOOLS = frozenset(
    {
        "get_ticker_news",
        "get_ticker_sentiment",
        "get_company_vectors",
        "get_ticker_relationships",
        "get_top_articles",
        "get_cluster_trends",
        "get_dimension_trends",
        "search_news",
        "get_user_positions",
        "get_user_alerts",
        "get_user_screening_notes",
        "get_user_screening_note_details",
        "get_ticker_chat_history",
    }
)


# ── Per-ticker signal (output of the deterministic analytics layer) ──────────


@dataclass
class TickerSignal:
    """Result of a skill's deterministic analytics for one ticker.

    ``needs_llm`` is the escalation switch: when False, ``verdict`` + ``facts``
    are taken as the final per-ticker verdict (no LLM call). When True, the
    ticker is batched for the per-ticker LLM evaluator, which sees ``metrics``
    and ``facts`` alongside trimmed raw tool data.
    """

    ticker: str
    metrics: dict[str, Any] = field(default_factory=dict)
    verdict: str | None = None  # "triggered" | "not" | None (ambiguous)
    facts: str = ""
    confidence: str = "medium"
    needs_llm: bool = False

    @classmethod
    def decided(
        cls,
        ticker: str,
        *,
        triggered: bool,
        facts: str,
        metrics: dict[str, Any] | None = None,
        confidence: str = "medium",
    ) -> "TickerSignal":
        """A conclusive deterministic verdict — no LLM needed."""
        return cls(
            ticker=ticker.upper(),
            metrics=metrics or {},
            verdict="triggered" if triggered else "not",
            facts=facts,
            confidence=confidence,
            needs_llm=False,
        )

    @classmethod
    def escalate(
        cls,
        ticker: str,
        *,
        facts: str = "",
        metrics: dict[str, Any] | None = None,
    ) -> "TickerSignal":
        """Ambiguous / qualitative — hand to the per-ticker LLM evaluator."""
        return cls(
            ticker=ticker.upper(),
            metrics=metrics or {},
            verdict=None,
            facts=facts,
            needs_llm=True,
        )

    def to_verdict(self) -> dict:
        """Render as the canonical per-ticker verdict (decided path only)."""
        return {
            "ticker": self.ticker,
            "triggered_for_ticker": self.verdict == "triggered",
            "key_findings": self.facts[:600],
            "confidence": self.confidence,
        }


# ── Analytics parsing helpers (shared across skills) ─────────────────────────


def _coerce(result: Any) -> Any:
    """Parse a JSON-string tool result into Python.

    FMP MCP tools return their payload as a JSON *string* (the text content of
    the MCP response), whereas internal RAG tools return Python objects. The
    deterministic analytics layer needs real lists/dicts, so we json.loads any
    string that looks like JSON and leave everything else untouched.
    """
    if isinstance(result, str):
        s = result.strip()
        if s[:1] in ("[", "{"):
            try:
                return json.loads(s)
            except json.JSONDecodeError:
                return result
    return result


def _as_list(result: Any) -> list:
    """Coerce a tool result into a list of rows.

    Internal tools return a list directly; FMP tools return a JSON string; some
    return ``{"error": ...}`` or a dict wrapping a list. Errors and scalars
    collapse to an empty list so analytics never raises on a bad tool response.
    """
    result = _coerce(result)
    if isinstance(result, list):
        return result
    if isinstance(result, dict):
        if "error" in result:
            return []
        for v in result.values():
            if isinstance(v, list):
                return v
    return []


def _news_items(data: dict[str, Any]) -> list[dict]:
    """All news rows from a per-ticker ``get_ticker_news`` result.

    In the per-ticker fan-out the call is substituted with a single ticker, so
    every row already belongs to this ticker — we just keep the dict rows.
    """
    return [r for r in _as_list(data.get("get_ticker_news")) if isinstance(r, dict)]


def _mean_sentiment(items: list[dict]) -> float:
    vals = [
        float(i.get("sentiment_score") or 0.0)
        for i in items
        if isinstance(i, dict) and i.get("sentiment_score") is not None
    ]
    return sum(vals) / len(vals) if vals else 0.0


def _external_rows(data: dict[str, Any]) -> list[dict]:
    """Rows from non-internal (FMP) tool results — the OHLC source.

    Name-agnostic on purpose: a skill's FMP price tool can be renamed without
    touching the extractor, since anything outside ``_INTERNAL_TOOLS`` is
    assumed to be a market-data call that may carry bars.
    """
    rows: list[dict] = []
    for name, result in data.items():
        if name in _INTERNAL_TOOLS:
            continue
        result = _coerce(result)
        rows.extend(r for r in _as_list(result) if isinstance(r, dict))
        if isinstance(result, dict) and "error" not in result:
            rows.append(result)  # a single-quote dict
    return rows


def _num(row: dict, *keys: str) -> float | None:
    for k in keys:
        v = row.get(k)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return None


def _price_bars(data: dict[str, Any]) -> list[dict]:
    """Dated OHLC bars from FMP, sorted oldest→newest.

    FMP's EOD endpoints return newest-first, so we sort by ``date`` ascending —
    the last element is then genuinely the most recent bar. Requiring a ``date``
    field cleanly excludes the realtime ``quote`` row (which has no ``date``),
    keeping the series and the spot quote from contaminating each other.
    """
    bars = [
        r
        for r in _external_rows(data)
        if isinstance(r, dict) and r.get("date") and _num(r, "close", "price", "c") is not None
    ]
    bars.sort(key=lambda r: str(r.get("date")))
    return bars


def _planned_entry(data: dict[str, Any], ticker: str) -> dict | None:
    """The user's logged entry for this ticker from their latest screening notes.

    Shape (per get_user_screening_note_details): {price, direction, date,
    take_profit?, stop_loss?, bar_idx?}. None when the user hasn't planned an
    entry (or the user tool isn't available).
    """
    t = ticker.upper()
    for r in _as_list(data.get("get_user_screening_note_details")):
        if isinstance(r, dict) and str(r.get("ticker") or "").upper() == t:
            entry = r.get("entry")
            if isinstance(entry, dict) and entry.get("price") is not None:
                return entry
    return None


def _format_entry(entry: dict) -> str:
    """One-line rendering of a planned entry for facts/metrics."""
    direction = str(entry.get("direction") or "?")
    parts = [f"planned {direction} @ {entry.get('price')}"]
    if entry.get("stop_loss") is not None:
        parts.append(f"SL {entry['stop_loss']}")
    if entry.get("take_profit") is not None:
        parts.append(f"TP {entry['take_profit']}")
    return ", ".join(parts)


# ── Skill definition ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ScreeningSkill:
    """A predefined, validated recipe for one kind of multi-ticker screening."""

    id: str
    description: str  # one line shown to the classifier
    tool_plan: list[dict]  # literal calls, {TICKER} placeholders, enums baked in
    analytics: Callable[[str, dict[str, Any]], TickerSignal]
    eval_focus: str  # intent-specific guidance appended to the batch evaluator
    requires: tuple[str, ...]  # internal tools that MUST exist, else disqualified
    conclude_hint: str = ""
    batch_size: int | None = None
    model: str | None = None
    always_send: bool | None = None

    def fmp_tools(self) -> list[str]:
        return [
            t["name"]
            for t in self.tool_plan
            if t.get("name") not in _INTERNAL_TOOLS
        ]


# ── Analytics implementations ────────────────────────────────────────────────


def _analytics_news_impact(ticker: str, data: dict[str, Any]) -> TickerSignal:
    news = _news_items(data)
    metrics = {
        "article_count": len(news),
        "mean_sentiment": round(_mean_sentiment(news), 3),
    }
    if not news:
        return TickerSignal.decided(
            ticker,
            triggered=False,
            facts=f"No news for {ticker} in the lookback window.",
            metrics=metrics,
            confidence="high",
        )
    # Whether a headline is materially impactful is a qualitative call — escalate
    # to the LLM, but hand it the computed aggregates + the actual top headlines.
    top = "; ".join(str(i.get("title") or "").strip()[:90] for i in news[:3])
    return TickerSignal.escalate(
        ticker,
        facts=(
            f"{len(news)} articles, mean sentiment "
            f"{metrics['mean_sentiment']:+.2f}. Top: {top}"
        ),
        metrics=metrics,
    )


def _analytics_breakout(ticker: str, data: dict[str, Any]) -> TickerSignal:
    news = _news_items(data)
    bars = _price_bars(data)
    closes = [c for b in bars if (c := _num(b, "close", "price", "c")) is not None]
    vols = [v for b in bars if (v := _num(b, "volume", "v")) is not None]
    entry = _planned_entry(data, ticker)
    metrics: dict[str, Any] = {
        "news_count": len(news),
        "mean_sentiment": round(_mean_sentiment(news), 3),
        "bars": len(closes),
    }
    if entry:
        metrics["planned_entry_price"] = entry.get("price")
        metrics["planned_direction"] = entry.get("direction")
    entry_note = f" | {_format_entry(entry)}" if entry else ""

    if len(closes) < 5:
        # No usable price series (FMP unavailable / unexpected shape). Without
        # prices there's no deterministic breakout call: escalate if there's at
        # least news or a planned entry to reason about, else conclude no-breakout.
        if news or entry:
            return TickerSignal.escalate(
                ticker,
                facts=(
                    f"{ticker}: no price series available; "
                    f"{len(news)} recent headlines to assess{entry_note}."
                ),
                metrics=metrics,
            )
        return TickerSignal.decided(
            ticker,
            triggered=False,
            facts=f"{ticker}: no price data and no news — cannot confirm a breakout.",
            metrics=metrics,
            confidence="low",
        )

    window = closes[-_BREAKOUT_LOOKBACK:] if len(closes) >= _BREAKOUT_LOOKBACK else closes
    current = closes[-1]
    hi = max(window)
    pct_from_high = ((current - hi) / hi * 100.0) if hi else 0.0
    metrics["pct_from_high"] = round(pct_from_high, 2)

    vol_ratio: float | None = None
    if len(vols) >= 5:
        prior = vols[:-1]
        avg_v = sum(prior) / len(prior) if prior else 0.0
        if avg_v:
            vol_ratio = vols[-1] / avg_v
            metrics["volume_ratio"] = round(vol_ratio, 2)

    facts = f"{ticker}: {pct_from_high:+.1f}% from {len(window)}-bar high"
    if vol_ratio is not None:
        facts += f", volume {vol_ratio:.1f}x avg"
    if news:
        facts += f"; latest: {str(news[0].get('title') or '')[:80]}"
    facts += entry_note

    near_high = pct_from_high >= _NEAR_HIGH_PCT
    far_below = pct_from_high <= _FAR_BELOW_PCT
    strong_vol = (vol_ratio or 0.0) >= _VOLUME_SURGE

    # A confirmed price+volume breakout is deterministic — UNLESS the user has a
    # planned entry, in which case we escalate so the LLM can judge the breakout
    # against their plan (price vs entry, stop, target) rather than rubber-stamp.
    if near_high and strong_vol and not entry:
        return TickerSignal.decided(
            ticker,
            triggered=True,
            facts=facts + " — breakout confirmed (at highs on volume).",
            metrics=metrics,
            confidence="high",
        )
    if far_below and not entry:
        return TickerSignal.decided(
            ticker,
            triggered=False,
            facts=facts + " — well off the highs, no breakout.",
            metrics=metrics,
            confidence="high",
        )
    # Near the high but volume soft, mid-range, or a planned entry exists — a
    # judgment call. Escalate with the computed numbers so the LLM reasons over
    # facts (and the user's plan), not raw bars.
    return TickerSignal.escalate(ticker, facts=facts, metrics=metrics)


def _analytics_portfolio_rundown(ticker: str, data: dict[str, Any]) -> TickerSignal:
    news = _news_items(data)
    metrics = {
        "article_count": len(news),
        "mean_sentiment": round(_mean_sentiment(news), 3),
    }
    if news:
        top = str(news[0].get("title") or "").strip()[:90]
        facts = (
            f"{ticker}: {len(news)} headlines, sentiment "
            f"{metrics['mean_sentiment']:+.2f}. Latest: {top}"
        )
    else:
        facts = f"{ticker}: no fresh news in the window."
    # A rundown is informational: don't spend an LLM call per ticker. The
    # deterministic fact line feeds straight into the stage-3 narrative.
    return TickerSignal.decided(
        ticker, triggered=True, facts=facts, metrics=metrics, confidence="medium"
    )


def _analytics_relationship_contagion(ticker: str, data: dict[str, Any]) -> TickerSignal:
    rel = data.get("get_ticker_relationships")
    edges = rel.get("edges") if isinstance(rel, dict) else None
    edges = edges if isinstance(edges, list) else []
    news = _news_items(data)
    metrics = {"edge_count": len(edges), "news_count": len(news)}
    if not edges:
        return TickerSignal.decided(
            ticker,
            triggered=False,
            facts=f"{ticker}: no graph relationships found — no contagion path.",
            metrics=metrics,
            confidence="high",
        )
    return TickerSignal.escalate(
        ticker,
        facts=(
            f"{ticker}: {len(edges)} graph edges, {len(news)} recent "
            "headlines — assess whether a neighbour's catalyst spreads here."
        ),
        metrics=metrics,
    )


# ── Skill registry ───────────────────────────────────────────────────────────

SKILLS: list[ScreeningSkill] = [
    ScreeningSkill(
        id="news_impact",
        description=(
            "News-driven impact on specific tickers: fresh headlines, sentiment "
            "shifts, catalysts, 'what's the news on X', impact scores."
        ),
        tool_plan=[
            {"name": "get_ticker_news", "args": {"tickers": [_TICKER_PLACEHOLDER], "hours": 48, "per_ticker_limit": 8}},
            {"name": "get_ticker_sentiment", "args": {"tickers": [_TICKER_PLACEHOLDER], "hours": 48}},
            {"name": "get_company_vectors", "args": {"tickers": [_TICKER_PLACEHOLDER]}},
            {"name": "get_ticker_relationships", "args": {"ticker": _TICKER_PLACEHOLDER, "hops": 1}},
        ],
        analytics=_analytics_news_impact,
        eval_focus=(
            "Focus: does the news materially move the thesis for this ticker? "
            "Weigh sentiment magnitude, headline substance (earnings, guidance, "
            "M&A, regulatory) over noise, and the company factor profile. "
            "triggered_for_ticker=true only on a concrete, market-moving catalyst."
        ),
        requires=("get_ticker_news", "get_ticker_sentiment"),
        conclude_hint="Lead with the tickers carrying the strongest fresh catalysts.",
    ),
    ScreeningSkill(
        id="breakout",
        description=(
            "Technical breakouts / momentum: price pushing to recent highs, "
            "volume surges, breaking resistance, 'which names are breaking out'."
        ),
        # FMP `chart` (EOD-light series) + `quote` feed the deterministic
        # price/volume math; the user's planned entry is pulled from their latest
        # screening notes. {FROM_DATE}/{TO_DATE} are substituted at runtime
        # (lookback window ending today). If an FMP tool is unknown or
        # access-denied the pipeline drops it and analytics escalates on the
        # news floor instead. Confirm names with `validate-skills --probe`.
        tool_plan=[
            {"name": "get_ticker_news", "args": {"tickers": [_TICKER_PLACEHOLDER], "hours": 72, "per_ticker_limit": 5}},
            {"name": "get_user_screening_note_details", "args": {"tickers": [_TICKER_PLACEHOLDER]}},
            {"name": "quote", "args": {"endpoint": "quote", "symbol": _TICKER_PLACEHOLDER}},
            {"name": "chart", "args": {"endpoint": "historical-price-eod-light", "symbol": _TICKER_PLACEHOLDER, "from_date": "{FROM_DATE}", "to_date": "{TO_DATE}"}},
        ],
        analytics=_analytics_breakout,
        eval_focus=(
            "Focus: is this a real breakout? The metrics already give pct_from_high "
            "and volume_ratio. triggered_for_ticker=true only when price is at/near "
            "the recent high AND volume confirms — never on news alone. If the user "
            "logged a planned entry (planned_entry_price / planned_direction), state "
            "whether the current price/breakout confirms or contradicts that plan."
        ),
        requires=("get_ticker_news",),
        conclude_hint=(
            "Name only tickers with a confirmed price+volume breakout. Where the "
            "user has a planned entry, note if the breakout supports it."
        ),
    ),
    ScreeningSkill(
        id="portfolio_rundown",
        description=(
            "Informational rundown of the user's portfolio / positions / "
            "watchlist: 'give me a rundown', 'what's happening with my holdings', "
            "overview, summary. Not a conditional alert."
        ),
        tool_plan=[
            {"name": "get_user_positions", "args": {}},
            {"name": "get_user_alerts", "args": {}},
            {"name": "get_user_screening_note_details", "args": {"tickers": [_TICKER_PLACEHOLDER]}},
            {"name": "get_ticker_news", "args": {"tickers": [_TICKER_PLACEHOLDER], "hours": 48, "per_ticker_limit": 5}},
        ],
        analytics=_analytics_portfolio_rundown,
        eval_focus=(
            "Focus: a concise per-position status — recent news, sentiment, and "
            "any alert proximity. This is informational; summarise, don't gate."
        ),
        requires=("get_user_positions", "get_ticker_news"),
        conclude_hint=(
            "Write a scannable portfolio rundown: one clause per holding with its "
            "freshest signal. This is always-send — never return summary=null."
        ),
        always_send=True,
    ),
    ScreeningSkill(
        id="relationship_contagion",
        description=(
            "Second-order / contagion effects through the relationship graph: "
            "supplier/customer/peer spillover, 'who's affected if X moves', "
            "knock-on impact from a related name's catalyst."
        ),
        tool_plan=[
            {"name": "get_ticker_relationships", "args": {"ticker": _TICKER_PLACEHOLDER, "hops": 1}},
            {"name": "get_ticker_news", "args": {"tickers": [_TICKER_PLACEHOLDER], "hours": 48, "per_ticker_limit": 6}},
        ],
        analytics=_analytics_relationship_contagion,
        eval_focus=(
            "Focus: does a catalyst on a graph neighbour plausibly transmit to "
            "this ticker? Cite the specific relationship (supplier, peer) and the "
            "neighbour event. triggered_for_ticker=true only with a clear path."
        ),
        requires=("get_ticker_relationships", "get_ticker_news"),
        conclude_hint="Explain the transmission path, not just the correlation.",
    ),
]

_SKILLS_BY_ID = {s.id: s for s in SKILLS}


def get_skill(skill_id: str | None) -> ScreeningSkill | None:
    if not skill_id:
        return None
    return _SKILLS_BY_ID.get(skill_id.strip())


def skill_catalog() -> str:
    """Render the skill list for the classifier prompt."""
    return "\n".join(f"- {s.id}: {s.description}" for s in SKILLS)


# ── Classifier ───────────────────────────────────────────────────────────────

_CLASSIFY_SYSTEM = """You are a router for a stock-screening agent. Given a \
screening prompt, choose the SINGLE best-matching skill from the list, or NONE \
if no skill clearly fits.

SKILLS:
{CATALOG}

Rules:
- Pick exactly one skill id, or "NONE" when the prompt is a poor fit for all.
- A user-set trigger CONDITION (if given) is part of the intent — route on it too.
- Prefer NONE over a weak/forced match; NONE routes to the general planner.

Respond with ONLY this JSON (no markdown, no commentary):
{"skill": "<skill_id>" | "NONE", "reason": "<short>"}
"""


async def classify_skill(
    client: httpx.AsyncClient,
    *,
    base_url: str,
    model: str,
    prompt: str,
    trigger_condition: str | None = None,
) -> ScreeningSkill | None:
    """Route a screening prompt to a predefined skill, or None to fall back.

    One cheap JSON call: the model's only job is to emit a skill id. Any parse
    failure or unknown id resolves to None (→ dynamic planner), so a flaky
    classify never blocks a run.
    """
    system = _CLASSIFY_SYSTEM.replace("{CATALOG}", skill_catalog())
    user_parts = [f"SCREENING PROMPT:\n{prompt}"]
    if trigger_condition and trigger_condition.strip():
        user_parts.append(f"TRIGGER CONDITION:\n{trigger_condition.strip()}")
    user_parts.append("Return the JSON now.")
    try:
        raw = await simple_chat(
            client,
            base_url=base_url,
            model=model,
            system=system,
            user="\n\n".join(user_parts),
            request_format="json",
            options={"num_predict": 200},
            label="Skill classifier",
        )
    except Exception as exc:  # noqa: BLE001 — never let routing kill a run
        log.warning("Skill classifier call failed (%s) — falling back to planner", exc)
        return None

    skill_id = _parse_skill_id(raw)
    skill = get_skill(skill_id)
    log.info(
        "Skill classifier: raw=%r → id=%r matched=%s",
        raw[:160], skill_id, bool(skill),
    )
    return skill


def _parse_skill_id(raw: str) -> str | None:
    raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        log.warning("Skill classifier: non-JSON response, head=%r", raw[:160])
        return None
    if not isinstance(data, dict):
        return None
    skill_id = str(data.get("skill") or "").strip()
    if not skill_id or skill_id.upper() == "NONE":
        return None
    return skill_id
