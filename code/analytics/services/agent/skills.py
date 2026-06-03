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

# Breakout thresholds. The price reference depends on the ticker: if the user
# has a logged entry note we measure against their planned entry price;
# otherwise against the trailing N-bar high. Volume must expand by at least
# _VOLUME_SURGE× the trailing average to confirm.
#
# Detection uses a BAND around the reference, biased toward EARLY detection —
# we start flagging while price is still approaching the level (pre band) and
# keep flagging just past it (post band). We'd rather alert slightly early than
# miss a breakout. Both are percentages of the reference price.
_BREAKOUT_LOOKBACK = 20       # trailing daily bars: high reference + volume average
_INTRADAY_LOOKBACK_BARS = 14  # trailing intraday (hourly) bars for the same
_VOLUME_SURGE = 1.5           # volume ≥ 1.5× trailing average to confirm
_ENTRY_PRE_BAND_PCT = 5.0     # begin flagging this far BEFORE the entry/high
_ENTRY_POST_BAND_PCT = 5.0    # keep flagging this far PAST the entry

# Breakout scans these timeframes. Each maps a tool-plan result slot (filled by
# the skill's `chart` calls) to a label; daily uses the realtime quote as the
# live price, intraday uses the latest bar. Add a slot here + a matching chart
# call in the skill to scan another timeframe.
_BREAKOUT_TIMEFRAMES = (
    {"label": "daily", "slot": "chart_daily", "use_quote": True, "lookback": _BREAKOUT_LOOKBACK},
    {"label": "1h", "slot": "chart_1h", "use_quote": False, "lookback": _INTRADAY_LOOKBACK_BARS},
)

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


def _spot_quote(data: dict[str, Any]) -> dict | None:
    """The realtime quote row from the ``quote`` slot (has ``price``/``volume``)."""
    for r in _as_list(data.get("quote")):
        if isinstance(r, dict) and r.get("price") is not None:
            return r
    return None


def _series_bars(data: dict[str, Any], slot: str) -> list[dict]:
    """Dated OHLCV bars from a named chart slot, sorted oldest→newest."""
    bars = [
        r
        for r in _as_list(data.get(slot))
        if isinstance(r, dict) and r.get("date") and _num(r, "close", "price", "c") is not None
    ]
    bars.sort(key=lambda r: str(r.get("date")))
    return bars


def _entry_from_metadata(meta: Any) -> dict | None:
    """Parse a planned entry out of a raw ``metadata_json`` value (string or
    dict) — a fallback for paths that don't pre-parse ``entry``."""
    meta = _coerce(meta)
    if isinstance(meta, dict):
        entry = meta.get("entry")
        return entry if isinstance(entry, dict) else None
    return None


def _planned_entry(data: dict[str, Any], ticker: str) -> dict | None:
    """The user's logged entry for this ticker from their latest screening notes.

    Shape (per get_user_screening_note_details): {price, direction, date,
    take_profit?, stop_loss?, bar_idx?}. The tool already parses ``entry`` out
    of ``metadata_json``; we fall back to parsing it ourselves for robustness.
    None when the user hasn't planned an entry (or the user tool is absent).
    """
    t = ticker.upper()
    for r in _as_list(data.get("get_user_screening_note_details")):
        if not isinstance(r, dict) or str(r.get("ticker") or "").upper() != t:
            continue
        entry = r.get("entry")
        if not (isinstance(entry, dict) and entry.get("price") is not None):
            entry = _entry_from_metadata(r.get("metadata_json"))
        if isinstance(entry, dict) and entry.get("price") is not None:
            return entry
    return None


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
        names = [
            t["name"]
            for t in self.tool_plan
            if t.get("name") not in _INTERNAL_TOOLS
        ]
        return list(dict.fromkeys(names))  # dedup (same tool may appear twice)


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


def _breakout_band(current: float, ref_high: float, entry: dict | None) -> tuple[bool, float, str]:
    """(in_band, pct_vs_ref, ref_label) for one timeframe's current price.

    Early-biased band: with an entry note we band around the planned entry
    (direction-aware); otherwise around the trailing high (within pre% below it,
    or any new high). pre/post come from the module-level band constants.
    """
    pre = _ENTRY_PRE_BAND_PCT / 100.0
    post = _ENTRY_POST_BAND_PCT / 100.0
    if entry and entry.get("price") is not None:
        ep = float(entry["price"])
        direction = str(entry.get("direction") or "long").lower()
        if direction == "short":
            lower, upper = ep * (1 - post), ep * (1 + pre)
        else:
            lower, upper = ep * (1 - pre), ep * (1 + post)
        pct = round((current - ep) / ep * 100.0, 2) if ep else 0.0
        return (lower <= current <= upper), pct, f"{direction} entry {ep:g}"
    pct = round((current - ref_high) / ref_high * 100.0, 2) if ref_high else 0.0
    return (ref_high > 0 and current >= ref_high * (1 - pre)), pct, f"high {ref_high:.2f}"


def _eval_breakout_timeframe(
    data: dict[str, Any], tf: dict, entry: dict | None
) -> dict | None:
    """Deterministic breakout check for one timeframe. None if no usable data.

    Daily uses the realtime quote as the live price/volume; intraday uses the
    latest bar. The reference high (and volume average) is taken from the prior
    bars of that timeframe's own series.
    """
    bars = _series_bars(data, tf["slot"])
    closes = [c for b in bars if (c := _num(b, "close", "price", "c")) is not None]
    highs = [h for b in bars if (h := _num(b, "high", "close", "price")) is not None]
    vols = [v for b in bars if (v := _num(b, "volume", "v")) is not None]

    quote = _spot_quote(data) if tf.get("use_quote") else None
    current = (_num(quote, "price") if quote else None) or (closes[-1] if closes else None)
    cur_vol = (_num(quote, "volume") if quote else None) or (vols[-1] if vols else None)

    n = tf["lookback"]
    prior_highs = highs[:-1][-n:] if len(highs) > 1 else highs
    prior_vols = vols[:-1][-n:] if len(vols) > 1 else vols
    if current is None or len(prior_highs) < 5 or not prior_vols or not cur_vol:
        return None

    avg_v = sum(prior_vols) / len(prior_vols)
    vol_ratio = (cur_vol / avg_v) if avg_v else None
    vol_ok = vol_ratio is not None and vol_ratio >= _VOLUME_SURGE
    ref_high = max(prior_highs)
    in_band, pct, ref = _breakout_band(current, ref_high, entry)
    return {
        "label": tf["label"],
        "confirmed": bool(in_band and vol_ok),
        "in_band": bool(in_band),
        "vol_ok": bool(vol_ok),
        "current": round(current, 2),
        "pct": pct,
        "vol_ratio": round(vol_ratio, 2) if vol_ratio is not None else None,
        "ref": ref,
    }


def _analytics_breakout(ticker: str, data: dict[str, Any]) -> TickerSignal:
    """Deterministic, multi-timeframe breakout verdict (never escalates).

    Scans each timeframe in _BREAKOUT_TIMEFRAMES (daily EOD + intraday hourly).
    A timeframe confirms when price is in the early-biased band around its
    reference (planned entry if noted, else trailing high) AND volume ≥ 1.5×
    the trailing average. The ticker triggers if ANY timeframe confirms — so an
    intraday move is caught as it develops, before the daily candle has run up.
    The decision is fully hardcoded; the LLM concluder only writes the message.
    """
    news = _news_items(data)
    entry = _planned_entry(data, ticker)
    metrics: dict[str, Any] = {"news_count": len(news)}
    if entry:
        metrics["planned_entry_price"] = entry.get("price")
        metrics["planned_direction"] = entry.get("direction")

    results = [r for tf in _BREAKOUT_TIMEFRAMES if (r := _eval_breakout_timeframe(data, tf, entry))]
    if not results:
        return TickerSignal.decided(
            ticker, triggered=False,
            facts=f"{ticker}: insufficient price/volume data on any timeframe.",
            metrics=metrics, confidence="low",
        )

    metrics["timeframes"] = {r["label"]: r for r in results}
    confirmed_tfs = [r["label"] for r in results if r["confirmed"]]
    triggered = bool(confirmed_tfs)

    frags = []
    for r in results:
        status = "CONFIRMED" if r["confirmed"] else ("in-band" if r["in_band"] else "no")
        vr = f"{r['vol_ratio']:.2f}x" if r["vol_ratio"] is not None else "n/a"
        frags.append(f"{r['label']}={status} ({r['current']:.2f} vs {r['ref']}, vol {vr})")
    head = (
        f"{ticker}: CONFIRMED breakout on {'+'.join(confirmed_tfs)}"
        if triggered else f"{ticker}: no confirmed breakout"
    )
    facts = f"{head} — " + "; ".join(frags) + "."
    if news:
        facts += f" Latest: {str(news[0].get('title') or '')[:60]}"

    return TickerSignal.decided(
        ticker, triggered=triggered, facts=facts, metrics=metrics, confidence="high",
    )


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
            "Multi-timeframe technical breakouts (daily + intraday): price "
            "breaking above a planned entry or the recent high WITH volume "
            "confirmation. 'Confirmed breakout on price and volume', momentum, "
            "breaking resistance, intraday moves."
        ),
        # Two `chart` calls under distinct slots feed the deterministic
        # multi-timeframe math: chart_daily (EOD-light, ~45d window) and chart_1h
        # (hourly, ~5d window) catch intraday moves before the daily candle runs
        # up. Realtime `quote` is the live price for the daily check; the user's
        # planned entry comes from their latest screening notes. Unknown/
        # access-denied FMP tools (e.g. intraday on a lower tier) are dropped and
        # that timeframe is simply skipped. Confirm with `validate-skills`.
        tool_plan=[
            {"name": "get_ticker_news", "args": {"tickers": [_TICKER_PLACEHOLDER], "hours": 72, "per_ticker_limit": 5}},
            {"name": "get_user_screening_note_details", "args": {"tickers": [_TICKER_PLACEHOLDER]}},
            {"name": "quote", "args": {"endpoint": "quote", "symbol": _TICKER_PLACEHOLDER}},
            {"name": "chart", "key": "chart_daily", "args": {"endpoint": "historical-price-eod-light", "symbol": _TICKER_PLACEHOLDER, "from_date": "{FROM_DATE}", "to_date": "{TO_DATE}"}},
            {"name": "chart", "key": "chart_1h", "args": {"endpoint": "intraday-1-hour", "symbol": _TICKER_PLACEHOLDER, "from_date": "{FROM_DATE_INTRADAY}", "to_date": "{TO_DATE}"}},
        ],
        analytics=_analytics_breakout,
        # Breakout is decided deterministically per ticker and never escalates,
        # so this focus is unused unless the pipeline path changes; kept for
        # parity with the eval contract.
        eval_focus=(
            "Multi-timeframe breakout. The metrics already give the verdict per "
            "timeframe (price vs entry/high band + volume_ratio). Do not re-judge."
        ),
        requires=("get_ticker_news",),
        conclude_hint=(
            "Each per-ticker verdict was decided deterministically across "
            "timeframes (daily + intraday hourly): price entered the breakout "
            "band around the planned entry or the trailing high AND volume ≥1.5× "
            "the trailing average. The facts/metrics name WHICH timeframe(s) "
            "confirmed. Write the message from these verdicts: list EVERY ticker "
            "whose verdict is triggered=true, add or re-judge NONE, call out the "
            "timeframe (e.g. intraday-only moves are early), and note the planned-"
            "entry context where present. Detection is biased early."
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
screening prompt, choose the SINGLE best-matching predefined skill.

SKILLS:
{CATALOG}

The predefined skills are the optimized, preferred processing path. PRIORITISE \
them: pick the closest-matching skill whenever the prompt plausibly fits one. \
Only return "NONE" when the prompt clearly fits NONE of the skills — NONE is a \
fallback to a slower general planner, so do not pick it for a borderline case.

Rules:
- Pick exactly one skill id. Reserve "NONE" for prompts that genuinely match no skill.
- A user-set trigger CONDITION (if given) is part of the intent — route on it too.
- Be consistent: the same prompt must always map to the same skill.

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
            # Greedy + fixed seed so the SAME prompt always routes to the SAME
            # skill. Without this the router samples and routing looks random.
            # think=False keeps reasoning models from burning the token budget
            # (and varying) before emitting the tiny JSON.
            options={"num_predict": 200, "temperature": 0.0, "top_p": 1.0, "seed": 0},
            think=False,
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
