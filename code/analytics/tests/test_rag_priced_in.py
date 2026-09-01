"""Pure-function tests for the priced-in retrieval layer.

No network: every test drives the shaping and ranking helpers off literal rows,
so they assert the joins and the trimming rather than the state of Supabase.
"""

import json

import pytest

from services.rag import priced_in as pi


# ── fixtures ────────────────────────────────────────────────────────────────

def _driver(i, **kw):
    d = {
        "driver": f"driver {i}",
        "segment": f"segment {i}",
        "basis": f"basis {i}",
        "priced_in_pct": 10 * i,
        "value_if_true_pct": 5 * i,
        "observable": "unit_volumes",
        "testable": True,
    }
    d.update(kw)
    return d


def _driver_case(i, **kw):
    c = {
        "ticker": "TEST",
        "driver_index": i,
        "driver": f"driver {i}",
        "segment": f"segment {i}",
        "priced_in_pct": 10 * i,
        "observable": "unit_volumes",
        "testable": True,
        "narrative": {"n_related": 3, "positive": 2, "negative": 1,
                      "net_impact": 0.4, "n_claims_scanned": 40,
                      "top": [{"text": f"claim {n}"} for n in range(6)]},
        "measurement": {"tool": "segment_revenue_history", "result": {"x": [1, 2, 3]},
                        "note": ""},
        "what_coverage_says": "coverage",
        "evidence_for": ["for"],
        "evidence_against": ["against"],
        "what_the_data_shows": "data",
        "still_needed": "more",
        "confidence": "low",
        "n_passages": 9,
        "sources": [{"title": "t", "slug": "s"}],
        "passages": [{"n": n, "title": f"p{n}"} for n in range(10)],
        "retrieval": {"k": 40, "threshold": 0.3},
    }
    c.update(kw)
    return c


def _analyst_case(firm="Baird"):
    return {"firm": firm, "analyst": "A. Nalyst", "stance": "endorsed",
            "target": 100.0, "case": "the case", "sources": []}


def _row(**kw):
    r = {
        "ticker": "TEST", "as_of": "2026-09-01", "price": 100.0,
        "n_targets": 9, "target_low": 90, "target_median": 110, "target_high": 130,
        "median_gap": 0.1, "implied_revenue_cagr": 0.08, "discount_rate": 0.09,
        "terminal_growth": 0.025, "fcf_margin": 0.15,
        "summary": "summary", "summary_json": {"crux": "the crux", "position": "pos",
                                               "pays_for": ["a"], "declines": ["b"]},
        "drivers_json": [_driver(0), _driver(1)],
        "cases_json": [_driver_case(0), _driver_case(1)],
        "pipeline_version": "priced-in/3", "model": "glm-5.1:cloud",
        "generation_is_pit": False, "created_at": "2026-09-01T00:00:00Z",
    }
    r.update(kw)
    return r


# ── case shape classification ───────────────────────────────────────────────

def test_case_kind_is_keyed_on_payload_not_pipeline_version():
    assert pi._case_kind(_driver_case(0)) == "driver"
    assert pi._case_kind(_analyst_case()) == "analyst"
    assert pi._case_kind({"something": "else"}) == "unknown"


def test_split_cases_separates_the_two_shapes():
    drivers, analysts = pi._split_cases(
        [_driver_case(0), _analyst_case(), {"junk": 1}, "not a dict"], 4, 6)
    assert len(drivers) == 1 and drivers[0]["case_kind"] == "driver"
    assert len(analysts) == 1 and analysts[0]["case_kind"] == "analyst"


def test_split_cases_parses_a_json_string_column():
    """`cases_json` may arrive as TEXT rather than parsed JSONB."""
    drivers, _ = pi._split_cases(json.dumps([_driver_case(0)]), 4, 6)
    assert len(drivers) == 1


# ── the driver ↔ case join ──────────────────────────────────────────────────

def test_cases_join_to_drivers_on_index():
    joined = pi._attach_cases([_driver(0), _driver(1)],
                              [pi._slim_case(_driver_case(1), 4, 6),
                               pi._slim_case(_driver_case(0), 4, 6)])
    assert [d["driver_index"] for d in joined] == [0, 1]
    # Order of the cases list must not matter — the index is the contract.
    assert joined[0]["case"]["driver"] == "driver 0"
    assert joined[1]["case"]["driver"] == "driver 1"
    assert all(d["case_matches_driver"] for d in joined)


def test_driver_without_a_case_is_still_returned():
    joined = pi._attach_cases([_driver(0), _driver(1)],
                              [pi._slim_case(_driver_case(0), 4, 6)])
    assert joined[1]["case"] is None
    assert joined[1]["case_matches_driver"] is None
    assert joined[1]["driver"] == "driver 1"


def test_mismatched_pairing_is_flagged_not_hidden():
    """The index joins; the text disagreeing means the pairing is suspect."""
    joined = pi._attach_cases(
        [_driver(0, driver="reordered driver")],
        [pi._slim_case(_driver_case(0), 4, 6)])
    assert joined[0]["case"] is not None
    assert joined[0]["case_matches_driver"] is False


# ── trimming ────────────────────────────────────────────────────────────────

def test_slim_case_truncates_claims_and_passages_but_keeps_all_prose():
    c = pi._slim_case(_driver_case(0), top_claims=2, passages=3)
    assert len(c["coverage"]["top_claims"]) == 2
    assert len(c["passages"]) == 3
    for field in ("what_coverage_says", "what_the_data_shows", "still_needed"):
        assert c[field]
    assert c["evidence_for"] and c["evidence_against"]
    # The retriever's own bookkeeping is not evidence and is dropped.
    assert "retrieval" not in c


def test_slim_case_keeps_every_source():
    """A citation the reader cannot follow is worth little, so sources survive."""
    case = _driver_case(0, sources=[{"title": f"t{n}", "slug": f"s{n}"} for n in range(12)])
    assert len(pi._slim_case(case, 1, 1)["sources"]) == 12


def test_bound_result_leaves_a_small_series_alone():
    small = {"a": [1, 2, 3, 4, 5]}
    out, truncated = pi._bound_result(small, 2000)
    assert out == small and truncated is False


def test_bound_result_shortens_lists_to_fit_and_says_so():
    big = {"periods": [{"revenue": 1_000_000, "label": "x" * 200} for _ in range(50)]}
    out, truncated = pi._bound_result(big, 2000)
    assert truncated is True
    assert len(json.dumps(out)) <= 2000
    assert len(out["periods"]) < 50
    # Cut from the tail: the leading periods and the shape survive.
    assert out["periods"][0] == big["periods"][0]


def test_bound_result_passes_none_through():
    assert pi._bound_result(None, 2000) == (None, False)


def test_unwired_measurement_reports_the_gap_rather_than_a_proxy():
    case = _driver_case(0, measurement={"tool": None, "result": None,
                                        "note": "no series for this observable"})
    m = pi._slim_case(case, 4, 6)["measurement"]
    assert m["wired"] is False
    assert m["note"] == "no series for this observable"


# ── row shaping ─────────────────────────────────────────────────────────────

def test_shape_row_separates_the_three_tiers_and_carries_the_caveat():
    s = pi._shape_row(_row(), include_cases=True, top_claims=4, passages=6)
    assert s["vote"]["n_targets"] == 9              # grounded
    assert s["implied"]["implied_revenue_cagr"] == 0.08   # assumption-sensitive
    assert s["drivers"][0]["priced_in_pct"] == 0    # judged
    assert "UNVALIDATED" in s["caveat"]
    assert s["crux"] == "the crux"


def test_analyst_cases_are_counted_by_default_and_returned_on_request():
    row = _row(pipeline_version="priced-in/2",
               cases_json=[_analyst_case("Baird"), _analyst_case("Jefferies")])
    off = pi._shape_row(row, True, 4, 6)
    assert off["analyst_cases_available"] == 2
    assert off["analyst_cases"] == []
    on = pi._shape_row(row, True, 4, 6, include_analyst_cases=True)
    assert len(on["analyst_cases"]) == 2
    assert on["analyst_cases"][0]["firm"] == "Baird"


def test_legacy_row_still_yields_drivers_with_no_cases_attached():
    row = _row(pipeline_version="priced-in/2", cases_json=[_analyst_case()])
    s = pi._shape_row(row, True, 4, 6)
    assert len(s["drivers"]) == 2
    assert all(d["case"] is None for d in s["drivers"])


def test_include_cases_false_skips_the_bodies():
    s = pi._shape_row(_row(), include_cases=False, top_claims=4, passages=6)
    assert all(d["case"] is None for d in s["drivers"])
    assert len(s["drivers"]) == 2


@pytest.mark.parametrize("as_of,stale", [
    ("2026-09-01", False),
    ("1999-01-01", True),
])
def test_staleness_follows_the_reconstruction_date(as_of, stale):
    s = pi._shape_row(_row(as_of=as_of), False, 4, 6)
    assert s["stale"] is stale


def test_unparseable_as_of_does_not_claim_staleness():
    s = pi._shape_row(_row(as_of=None), False, 4, 6)
    assert s["age_days"] is None
    assert s["stale"] is False


# ── ticker normalisation ────────────────────────────────────────────────────

@pytest.mark.parametrize("given,expected", [
    ("aapl", ["AAPL"]),
    ([" msft ", "msft", "NVDA"], ["MSFT", "NVDA"]),   # uppercased + deduped
    ([None, "", "  "], []),
    (None, []),
])
def test_norm(given, expected):
    assert pi._norm(given) == expected


# ── the public reads, off a stubbed row source ──────────────────────────────

@pytest.fixture
def rows(monkeypatch):
    """Stub the only function that touches Supabase."""
    store: list[dict] = []
    monkeypatch.setattr(pi, "_latest_published_rows", lambda tickers: list(store))
    return store


def test_get_priced_in_returns_tickers_in_the_order_asked(rows):
    rows.extend([_row(ticker="AAA"), _row(ticker="BBB"), _row(ticker="CCC")])
    got = [r["ticker"] for r in pi.get_priced_in(["CCC", "AAA", "BBB"])]
    assert got == ["CCC", "AAA", "BBB"]


def test_get_priced_in_on_empty_input_does_not_query(monkeypatch):
    def _boom(_):
        raise AssertionError("should not have queried")
    monkeypatch.setattr(pi, "_latest_published_rows", _boom)
    assert pi.get_priced_in([]) == []


def test_get_priced_in_drivers_filters_to_the_unpriced_end(rows):
    rows.append(_row(drivers_json=[_driver(0, priced_in_pct=10),
                                   _driver(1, priced_in_pct=90)],
                     cases_json=[]))
    out = pi.get_priced_in_drivers(["TEST"], max_priced_in_pct=50)
    assert [d["priced_in_pct"] for d in out] == [10]


def test_get_priced_in_drivers_drops_unknown_priced_in_when_filtering(rows):
    """A driver with no percentage cannot be shown to be under the ceiling."""
    rows.append(_row(drivers_json=[_driver(0, priced_in_pct=None)], cases_json=[]))
    assert pi.get_priced_in_drivers(["TEST"], max_priced_in_pct=50) == []
    assert len(pi.get_priced_in_drivers(["TEST"])) == 1


def test_get_priced_in_drivers_testable_only(rows):
    rows.append(_row(drivers_json=[_driver(0, testable=False), _driver(1, testable=True)],
                     cases_json=[]))
    out = pi.get_priced_in_drivers(["TEST"], testable_only=True)
    assert [d["driver"] for d in out] == ["driver 1"]


def test_get_priced_in_drivers_sorts_least_priced_first(rows):
    rows.append(_row(drivers_json=[_driver(0, priced_in_pct=80),
                                   _driver(1, priced_in_pct=20)],
                     cases_json=[]))
    assert [d["priced_in_pct"] for d in pi.get_priced_in_drivers(["TEST"])] == [20, 80]


def test_get_priced_in_case_scopes_to_one_driver(rows):
    rows.append(_row())
    assert len(pi.get_priced_in_case("TEST")) == 2
    one = pi.get_priced_in_case("TEST", driver_index=1)
    assert len(one) == 1 and one[0]["driver"] == "driver 1"
    assert one[0]["basis"] == "basis 1"          # carried from the driver row


def test_get_priced_in_case_is_empty_for_a_legacy_row(rows):
    """`/2` rows hold per-analyst cases; there is no driver case to return."""
    rows.append(_row(pipeline_version="priced-in/2", cases_json=[_analyst_case()]))
    assert pi.get_priced_in_case("TEST") == []


def test_get_priced_in_case_on_a_missing_ticker(monkeypatch):
    monkeypatch.setattr(pi, "_latest_published_rows", lambda t: [])
    assert pi.get_priced_in_case("NOPE") == []


# ── cross-ticker driver search ──────────────────────────────────────────────

def test_search_ranks_the_rare_term_above_the_common_one(rows):
    """An unweighted hit count puts "…ETF demand" above "…obesity" on one hit each."""
    common = [_row(ticker=f"C{i}", drivers_json=[_driver(0, driver="ETF demand tailwind")],
                   cases_json=[]) for i in range(20)]
    rows.extend(common)
    rows.append(_row(ticker="RARE",
                     drivers_json=[_driver(0, driver="Pipeline optionality (obesity)")],
                     cases_json=[]))
    out = pi.search_priced_in_drivers("obesity demand", limit=5)
    assert out[0]["ticker"] == "RARE"
    assert out[0]["matched"] == ["obesity"]


def test_search_scores_more_matched_terms_higher(rows):
    rows.append(_row(ticker="BOTH", drivers_json=[_driver(0, driver="data center power")],
                     cases_json=[]))
    rows.append(_row(ticker="ONE", drivers_json=[_driver(0, driver="power generation")],
                     cases_json=[]))
    out = pi.search_priced_in_drivers("data center power")
    assert out[0]["ticker"] == "BOTH"
    assert out[0]["match_terms"] == 3


def test_search_matches_segment_observable_and_basis_too(rows):
    rows.append(_row(ticker="SEG",
                     drivers_json=[_driver(0, driver="nothing", segment="Datacenter Systems")],
                     cases_json=[]))
    assert [d["ticker"] for d in pi.search_priced_in_drivers("datacenter")] == ["SEG"]


def test_search_ignores_short_tokens_and_empty_queries(rows):
    rows.append(_row())
    assert pi.search_priced_in_drivers("") == []
    assert pi.search_priced_in_drivers("a of") == []


def test_search_respects_the_priced_in_ceiling(rows):
    rows.append(_row(ticker="HIGH",
                     drivers_json=[_driver(0, driver="power capacity", priced_in_pct=90)],
                     cases_json=[]))
    assert pi.search_priced_in_drivers("power", max_priced_in_pct=50) == []


def test_search_honours_the_limit(rows):
    rows.extend(_row(ticker=f"T{i}", drivers_json=[_driver(0, driver="power")],
                     cases_json=[]) for i in range(10))
    assert len(pi.search_priced_in_drivers("power", limit=3)) == 3


def test_every_public_read_carries_the_caveat(rows):
    rows.append(_row(drivers_json=[_driver(0, driver="power")], cases_json=[_driver_case(0)]))
    assert "UNVALIDATED" in pi.get_priced_in(["TEST"])[0]["caveat"]
    assert "UNVALIDATED" in pi.get_priced_in_drivers(["TEST"])[0]["caveat"]
    assert "UNVALIDATED" in pi.get_priced_in_case("TEST")[0]["caveat"]
    assert "UNVALIDATED" in pi.search_priced_in_drivers("power")[0]["caveat"]
