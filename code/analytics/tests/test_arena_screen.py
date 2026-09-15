"""The price screen on Jim Chaos's FMP results (`tools.priced_names_only`).

A filings feed lists every SEC filer, some with no ticker and some with no
quote. The screen must drop exactly those from multi-company results, leave a
single-company call alone, and never lose data when the quote call fails.
"""

from __future__ import annotations

import json

import pytest

from services.arena import tools as arena_tools


FILINGS = json.dumps([
    {"symbol": "LRDC", "formType": "NT 10-K"},
    {"symbol": "None", "cik": "0002087656", "formType": "NT 10-K"},
    {"symbol": "GONE", "formType": "8-K"},
    {"symbol": "AAPL", "formType": "8-K"},
])


def quotes(symbols):
    return {s: px for s, px in {"LRDC": 0.63, "AAPL": 230.0}.items() if s in symbols}


@pytest.fixture(autouse=True)
def live(monkeypatch):
    monkeypatch.setattr(arena_tools, "_AS_OF", None)


def test_drops_symbolless_and_unpriced_filers():
    call = arena_tools.priced_names_only(lambda n, a: FILINGS, quotes=quotes)
    out = json.loads(call("secFilings", {}))
    assert [r["symbol"] for r in out["results"]] == ["LRDC", "AAPL"]
    assert out["dropped"] == ["(no symbol)", "GONE"]


def test_single_company_result_is_untouched():
    one = json.dumps([{"symbol": "GONE", "revenue": 1}, {"symbol": "GONE", "revenue": 2}])
    call = arena_tools.priced_names_only(lambda n, a: one, quotes=quotes)
    assert call("statements", {}) == one


def test_quote_failure_keeps_every_named_row():
    def boom(_):
        raise RuntimeError("FMP down")
    call = arena_tools.priced_names_only(lambda n, a: FILINGS, quotes=boom)
    out = json.loads(call("secFilings", {}))
    assert [r["symbol"] for r in out["results"]] == ["LRDC", "GONE", "AAPL"]


def test_replay_drops_only_symbolless_rows(monkeypatch):
    from datetime import date
    monkeypatch.setattr(arena_tools, "_AS_OF", date(2026, 7, 2))
    called = []
    call = arena_tools.priced_names_only(lambda n, a: FILINGS,
                                         quotes=lambda s: called.append(s) or {})
    out = json.loads(call("secFilings", {}))
    assert [r["symbol"] for r in out["results"]] == ["LRDC", "GONE", "AAPL"]
    assert not called                      # today's quote says nothing about July


def test_non_json_and_error_results_pass_through():
    call = arena_tools.priced_names_only(lambda n, a: {"error": "tier"}, quotes=quotes)
    assert call("secFilings", {}) == {"error": "tier"}
    call = arena_tools.priced_names_only(lambda n, a: "not json", quotes=quotes)
    assert call("secFilings", {}) == "not json"
