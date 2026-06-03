"""Tests for services.agent.skills + its wiring into the multi-ticker pipeline.

Covers three layers:
  1. Skill registry integrity — every skill's required internal tools resolve.
  2. Deterministic analytics — the COMPUTE layer's decided/escalate behaviour.
  3. Classifier routing + pipeline divert — a matched skill skips the dynamic
     planner; NONE falls back to it.
"""

import asyncio
from unittest import mock

from services.agent import engine, multi_ticker, skills
from services.agent.run_trace import RunTrace
from services.agent.skills import SKILLS, TickerSignal, get_skill


# ── 1. Registry integrity ────────────────────────────────────────────────────


def test_every_skill_requires_resolve_against_registry():
    """Each skill's `requires` tools must exist in a user-scoped registry."""
    reg = engine._build_registry(user_id="u1")
    known = set(reg.names())
    for skill in SKILLS:
        missing = [t for t in skill.requires if t not in known]
        assert not missing, f"{skill.id} requires missing tools: {missing}"


def test_skill_ids_unique_and_resolvable():
    ids = [s.id for s in SKILLS]
    assert len(ids) == len(set(ids))
    for i in ids:
        assert get_skill(i) is not None
    assert get_skill("nonsense") is None
    assert get_skill(None) is None


def test_fmp_tools_helper_excludes_internal():
    bk = get_skill("breakout")
    # breakout mixes get_ticker_news (internal) with FMP quote/history
    assert "get_ticker_news" not in bk.fmp_tools()
    assert "quote" in bk.fmp_tools()


# ── 2. Deterministic analytics ──────────────────────────────────────────────


def test_news_impact_no_news_decides_not_triggered():
    sig = skills._analytics_news_impact("AAPL", {"get_ticker_news": []})
    assert sig.needs_llm is False
    assert sig.verdict == "not"
    assert sig.confidence == "high"


def test_news_impact_with_news_escalates_with_metrics():
    data = {"get_ticker_news": [
        {"ticker": "AAPL", "title": "Apple beats earnings", "sentiment_score": 0.6},
        {"ticker": "AAPL", "title": "Analyst upgrade", "sentiment_score": 0.4},
    ]}
    sig = skills._analytics_news_impact("AAPL", data)
    assert sig.needs_llm is True
    assert sig.metrics["article_count"] == 2
    assert sig.metrics["mean_sentiment"] == 0.5


def _dated_bars(prices, volumes):
    """Build FMP-shaped EOD bars (newest-first, like the real endpoint)."""
    n = len(prices)
    rows = [
        {"symbol": "AAPL", "date": f"2026-05-{day:02d}", "price": p, "volume": v}
        for day, p, v in zip(range(1, n + 1), prices, volumes)
    ]
    return list(reversed(rows))  # emulate FMP newest-first ordering


def _quote(price, volume):
    """FMP-shaped realtime quote row (no `date`)."""
    return [{"symbol": "AAPL", "price": price, "volume": volume, "timestamp": 1}]


def test_breakout_never_escalates():
    """Breakout is fully deterministic — every path decides, none escalate."""
    cases = [
        {"chart": _dated_bars(list(range(90, 111)), [100] * 21), "get_ticker_news": []},
        {"get_ticker_news": []},  # no price data
        {"chart": _dated_bars(list(range(90, 111)), [100] * 21),
         "quote": _quote(110, 300), "get_ticker_news": []},
    ]
    for data in cases:
        assert skills._analytics_breakout("AAPL", data).needs_llm is False


def test_breakout_new_daily_high_on_volume_confirms():
    # last bar is a fresh high (110 > prior-20 high 109) on 3x volume
    bars = _dated_bars(list(range(90, 111)), [100] * 20 + [300])
    sig = skills._analytics_breakout("AAPL", {"chart": bars, "get_ticker_news": []})
    assert sig.verdict == "triggered"
    assert sig.metrics["volume_ratio"] == 3.0
    assert "CONFIRMED" in sig.facts


def test_breakout_in_band_but_soft_volume_not_confirmed():
    bars = _dated_bars(list(range(90, 111)), [100] * 21)  # no volume surge
    sig = skills._analytics_breakout("AAPL", {"chart": bars, "get_ticker_news": []})
    assert sig.verdict == "not"
    assert "volume only" in sig.facts


def test_breakout_handles_json_string_results():
    """FMP returns a JSON string; analytics must parse it, not choke."""
    import json as _json
    bars = _dated_bars(list(range(90, 111)), [100] * 20 + [300])
    sig = skills._analytics_breakout("AAPL", {"chart": _json.dumps(bars),
                                              "get_ticker_news": []})
    assert sig.verdict == "triggered"
    assert sig.metrics["bars"] == 21


def test_breakout_below_daily_high_band_not_confirmed():
    # current far below the prior high → outside the early band, no breakout
    bars = _dated_bars(list(range(100, 120)) + [105], [100] * 20 + [300])
    sig = skills._analytics_breakout("AAPL", {"chart": bars, "get_ticker_news": []})
    assert sig.verdict == "not"  # 105 vs 119 high (band floor ~113) → out of band


def test_breakout_insufficient_data_decides_not():
    sig = skills._analytics_breakout("AAPL", {
        "get_ticker_news": [{"ticker": "AAPL", "title": "x", "sentiment_score": 0.1}],
    })
    assert sig.needs_llm is False
    assert sig.verdict == "not"
    assert sig.confidence == "low"


def _entry_note(price, direction="long"):
    return [{"ticker": "AAPL", "entry": {"price": price, "direction": direction,
                                         "stop_loss": price * 0.9,
                                         "take_profit": price * 1.2}}]


def test_breakout_entry_band_confirms_within_post_band():
    # price 102 is +2% over a long entry of 100 → inside [95,105] band, on volume
    bars = _dated_bars([100] * 21, [100] * 21)
    sig = skills._analytics_breakout("AAPL", {
        "chart": bars, "quote": _quote(102, 300), "get_ticker_news": [],
        "get_user_screening_note_details": _entry_note(100),
    })
    assert sig.verdict == "triggered"
    assert sig.metrics["planned_entry_price"] == 100
    assert sig.metrics["pct_vs_entry"] == 2.0


def test_breakout_entry_band_fires_early_below_entry():
    # price 96 is -4% (within the 5% PRE band) → early detection still confirms
    bars = _dated_bars([100] * 21, [100] * 21)
    sig = skills._analytics_breakout("AAPL", {
        "chart": bars, "quote": _quote(96, 300), "get_ticker_news": [],
        "get_user_screening_note_details": _entry_note(100),
    })
    assert sig.verdict == "triggered"
    assert sig.metrics["pct_vs_entry"] == -4.0


def test_breakout_entry_too_far_below_not_confirmed():
    # price 90 is -10%, outside the 5% pre band → not yet a breakout
    bars = _dated_bars([100] * 21, [100] * 21)
    sig = skills._analytics_breakout("AAPL", {
        "chart": bars, "quote": _quote(90, 300), "get_ticker_news": [],
        "get_user_screening_note_details": _entry_note(100),
    })
    assert sig.verdict == "not"


def test_quote_row_excluded_from_price_series():
    """The realtime quote (no `date`) must not pollute the bar series."""
    bars = _dated_bars(list(range(90, 111)), [100] * 21)
    quote = [{"symbol": "AAPL", "price": 999, "volume": 1, "timestamp": 1}]
    extracted = skills._price_bars({"chart": bars, "quote": quote})
    assert all("date" in b for b in extracted)
    assert 999 not in [b.get("price") for b in extracted]


def test_portfolio_rundown_always_triggered():
    sig = skills._analytics_portfolio_rundown("AAPL", {"get_ticker_news": []})
    assert sig.needs_llm is False
    assert sig.verdict == "triggered"


def test_contagion_no_edges_decides_not():
    sig = skills._analytics_relationship_contagion(
        "AAPL", {"get_ticker_relationships": {"edges": []}})
    assert sig.verdict == "not"
    assert sig.needs_llm is False


def test_analytics_tolerates_error_results():
    # A tool that returned an error envelope must not raise.
    sig = skills._analytics_news_impact("AAPL", {"get_ticker_news": {"error": "boom"}})
    assert sig.verdict == "not"


# ── 3. Classifier routing ───────────────────────────────────────────────────


def _run(coro):
    return asyncio.run(coro)


def _mock_simple_chat(return_value):
    async def _fake(*args, **kwargs):
        return return_value
    return _fake


def test_classify_returns_matched_skill():
    with mock.patch.object(skills, "simple_chat",
                           _mock_simple_chat('{"skill": "breakout"}')):
        skill = _run(skills.classify_skill(
            object(), base_url="x", model="m", prompt="which names are breaking out"))
    assert skill is not None and skill.id == "breakout"


def test_classify_uses_greedy_deterministic_sampling():
    """Routing must be deterministic — temperature 0 + fixed seed, no thinking."""
    captured = {}

    async def _capture(*args, **kwargs):
        captured.update(kwargs)
        return '{"skill": "breakout"}'

    with mock.patch.object(skills, "simple_chat", _capture):
        _run(skills.classify_skill(object(), base_url="x", model="m",
                                   prompt="breakouts?"))
    assert captured["options"]["temperature"] == 0.0
    assert "seed" in captured["options"]
    assert captured["think"] is False


def test_classify_none_falls_through():
    with mock.patch.object(skills, "simple_chat",
                           _mock_simple_chat('{"skill": "NONE"}')):
        skill = _run(skills.classify_skill(
            object(), base_url="x", model="m", prompt="something weird"))
    assert skill is None


def test_classify_bad_json_returns_none():
    with mock.patch.object(skills, "simple_chat", _mock_simple_chat("not json")):
        skill = _run(skills.classify_skill(
            object(), base_url="x", model="m", prompt="p"))
    assert skill is None


def test_classify_exception_returns_none():
    async def _boom(*a, **k):
        raise RuntimeError("ollama down")
    with mock.patch.object(skills, "simple_chat", _boom):
        skill = _run(skills.classify_skill(
            object(), base_url="x", model="m", prompt="p"))
    assert skill is None


# ── 3b. Pipeline divert ─────────────────────────────────────────────────────


class _FakeRegistry:
    """Minimal ToolRegistry stand-in: every call returns empty data."""

    def __init__(self, names):
        self._names = set(names)

    def has(self, name):
        return name in self._names

    def names(self):
        return list(self._names)

    def schemas(self):
        return [{"function": {"name": n}} for n in self._names]

    async def call(self, name, args):
        return []  # empty → news_impact analytics decides "not", no LLM


def test_matched_skill_skips_dynamic_planner():
    """A classified skill must NOT invoke the dynamic _plan_tools planner."""
    skill = get_skill("news_impact")
    reg = _FakeRegistry({e["name"] for e in skill.tool_plan})

    async def _no_plan(*a, **k):
        raise AssertionError("dynamic planner must not run on the skill path")

    async def _fake_classify(*a, **k):
        return skill

    async def _fake_conclude(*a, **k):
        return {"triggered": True, "summary": "ok"}

    with mock.patch.object(multi_ticker, "classify_skill", _fake_classify), \
         mock.patch.object(multi_ticker, "_plan_tools", _no_plan), \
         mock.patch.object(multi_ticker, "_conclude", _fake_conclude):
        result = _run(multi_ticker.run_multi_ticker_async(
            prompt="news on my names", tickers=["AAPL", "MSFT"], registry=reg))

    assert result["data_used"]["skill"] == "news_impact"
    # Both tickers have empty news → decided deterministically, zero LLM evals.
    assert result["data_used"]["decided_count"] == 2
    assert result["data_used"]["escalated_count"] == 0


def test_date_placeholders_substituted():
    """{FROM_DATE}/{TO_DATE} resolve to ISO dates; {TICKER} still works."""
    import re
    args = {"symbol": "{TICKER}", "from_date": "{FROM_DATE}", "to_date": "{TO_DATE}"}
    out = multi_ticker._substitute_ticker(args, "AAPL")
    assert out["symbol"] == "AAPL"
    iso = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    assert iso.match(out["from_date"]) and iso.match(out["to_date"])
    assert out["from_date"] < out["to_date"]


def test_no_skill_diverts_to_dynamic_planner():
    """classify → None routes through the dynamic planner path."""
    reg = _FakeRegistry({"get_ticker_news", "get_ticker_sentiment"})

    async def _fake_classify(*a, **k):
        return None

    async def _fake_plan(*a, **k):
        return {
            "tool_plan": [{"name": "get_ticker_news",
                           "args": {"tickers": ["{TICKER}"], "hours": 24}}],
            "per_ticker_brief": "brief",
            "rationale": "dynamic",
        }

    captured = {}

    async def _fake_eval(*a, **k):
        captured["tickers"] = k["tickers"]
        return [{"ticker": t.upper(), "triggered_for_ticker": False,
                 "key_findings": "x", "confidence": "low"} for t in k["tickers"]]

    async def _fake_conclude(*a, **k):
        return {"triggered": False, "summary": None}

    with mock.patch.object(multi_ticker, "classify_skill", _fake_classify), \
         mock.patch.object(multi_ticker, "_plan_tools", _fake_plan), \
         mock.patch.object(multi_ticker, "_evaluate_ticker_batch", _fake_eval), \
         mock.patch.object(multi_ticker, "_conclude", _fake_conclude):
        result = _run(multi_ticker.run_multi_ticker_async(
            prompt="weird custom prompt", tickers=["AAPL", "MSFT"], registry=reg))

    assert result["data_used"]["skill"] is None
    assert result["data_used"]["plan"]["rationale"] == "dynamic"
    # No skill → all tickers escalate to the LLM evaluator.
    assert result["data_used"]["escalated_count"] == 2
    assert set(captured["tickers"]) == {"AAPL", "MSFT"}


# ── 4. Run trace ─────────────────────────────────────────────────────────────


def test_runtrace_records_ordered_events():
    tr = RunTrace()
    tr.event("plan", "done", tools=["a", "b"])
    tr.event("eval", "start", tickers=["AAPL"])
    d = tr.as_dict()
    assert d["event_count"] == 2
    assert [e["seq"] for e in d["events"]] == [0, 1]
    assert d["events"][0]["stage"] == "plan" and d["events"][0]["tools"] == ["a", "b"]
    assert "started_at" in d and "elapsed" in d


def test_trace_captures_skill_run_sequence():
    """A skill run records classify → plan → analytics → stage2 → conclude."""
    skill = get_skill("news_impact")
    reg = _FakeRegistry({e["name"] for e in skill.tool_plan})
    trace = RunTrace()

    async def _fake_classify(*a, **k):
        return skill

    async def _fake_conclude(*a, **k):
        return {"triggered": True, "summary": "ok"}

    with mock.patch.object(multi_ticker, "classify_skill", _fake_classify), \
         mock.patch.object(multi_ticker, "_conclude", _fake_conclude):
        _run(multi_ticker.run_multi_ticker_async(
            prompt="news on my names", tickers=["AAPL", "MSFT"],
            registry=reg, trace=trace))

    stages = [(e["stage"], e["event"]) for e in trace.events]
    assert ("run", "start") in stages
    assert ("classify", "done") in stages
    assert ("plan", "skill") in stages
    # both tickers had empty news → decided deterministically
    assert sum(1 for e in trace.events
               if e["stage"] == "analytics" and e["event"] == "decided") == 2
    assert ("stage2", "done") in stages
    assert ("conclude", "done") in stages


def test_trace_survives_simulated_timeout():
    """Events recorded before a cancellation remain in the shared recorder."""
    import asyncio as _aio

    skill = get_skill("news_impact")
    reg = _FakeRegistry({e["name"] for e in skill.tool_plan})
    trace = RunTrace()

    async def _fake_classify(*a, **k):
        trace.event("classify", "done", skill=skill.id)  # mirror real call
        return skill

    async def _hang_conclude(*a, **k):
        await _aio.sleep(10)  # never completes within the timeout

    async def _go():
        with mock.patch.object(multi_ticker, "classify_skill", _fake_classify), \
             mock.patch.object(multi_ticker, "_conclude", _hang_conclude):
            await _aio.wait_for(
                multi_ticker.run_multi_ticker_async(
                    prompt="news", tickers=["AAPL"], registry=reg, trace=trace),
                timeout=0.2,
            )

    with __import__("pytest").raises(_aio.TimeoutError):
        _run(_go())

    # Despite the timeout, the pre-conclude sequence is preserved.
    stages = [(e["stage"], e["event"]) for e in trace.events]
    assert ("run", "start") in stages
    assert ("stage2", "done") in stages
    assert not any(s == ("conclude", "done") for s in stages)
