"""Tests for apply_scan_filters — the row-data + workflow filter engine."""

from services.rag.screening import apply_scan_filters


def row(symbol, **row_data):
    return {"symbol": symbol, "row_data": row_data}


def _f(**overrides):
    """Empty filter dict by default; any override merges in."""
    return overrides


def test_no_filters_returns_all_symbols_in_input_order():
    rows = [row("AAPL"), row("MSFT"), row("NVDA")]
    assert apply_scan_filters(rows, _f()) == ["AAPL", "MSFT", "NVDA"]


def test_dedupes_repeated_symbols_keeping_first():
    rows = [row("AAPL", price=1), row("AAPL", price=2), row("MSFT")]
    assert apply_scan_filters(rows, _f()) == ["AAPL", "MSFT"]


def test_symbol_contains_filter_is_case_insensitive():
    """Filter compares case-insensitively (lowercased). Symbol strings pass through unchanged."""
    rows = [row("AAPL"), row("MSFT"), row("AMZN")]
    out = apply_scan_filters(rows, _f(symbolContains="aa"))   # lowercase needle still matches
    assert out == ["AAPL"]


# ── numeric filters ────────────────────────────────────────────────────────

def test_num_min_includes_equal_value():
    rows = [row("A", rs=80), row("B", rs=90), row("C", rs=70)]
    assert apply_scan_filters(rows, _f(numMin={"rs": "80"})) == ["A", "B"]


def test_num_max_includes_equal_value():
    rows = [row("A", rs=80), row("B", rs=90), row("C", rs=70)]
    assert apply_scan_filters(rows, _f(numMax={"rs": "80"})) == ["A", "C"]


def test_num_gt_strict():
    rows = [row("A", rs=80), row("B", rs=81)]
    assert apply_scan_filters(rows, _f(numGt={"rs": "80"})) == ["B"]


def test_num_lt_strict():
    rows = [row("A", rs=80), row("B", rs=79)]
    assert apply_scan_filters(rows, _f(numLt={"rs": "80"})) == ["B"]


def test_num_filter_skips_non_numeric_value():
    rows = [row("A", rs="N/A"), row("B", rs=85)]
    assert apply_scan_filters(rows, _f(numMin={"rs": "80"})) == ["B"]


def test_empty_string_bounds_are_treated_as_no_filter():
    rows = [row("A", rs=10), row("B", rs=99)]
    assert apply_scan_filters(rows, _f(numMin={"rs": ""}, numMax={"rs": ""})) == ["A", "B"]


# ── boolean filters ────────────────────────────────────────────────────────

def test_bool_require_keeps_only_truthy():
    rows = [row("A", inSp500=True), row("B", inSp500=False), row("C")]
    assert apply_scan_filters(rows, _f(boolRequire={"inSp500": True})) == ["A"]


def test_bool_reject_drops_truthy():
    rows = [row("A", inSp500=True), row("B", inSp500=False), row("C")]
    assert apply_scan_filters(rows, _f(boolReject={"inSp500": True})) == ["B", "C"]


def test_bool_require_with_off_flag_is_inactive():
    rows = [row("A", inSp500=True), row("B", inSp500=False)]
    assert apply_scan_filters(rows, _f(boolRequire={"inSp500": False})) == ["A", "B"]


# ── string filters ─────────────────────────────────────────────────────────

def test_string_one_of_keeps_matches():
    rows = [row("A", sector="Tech"), row("B", sector="Energy"), row("C", sector="Tech")]
    out = apply_scan_filters(rows, _f(stringOneOf={"sector": ["Tech"]}))
    assert out == ["A", "C"]


def test_string_contains_is_case_insensitive():
    rows = [row("A", note="Strong setup"), row("B", note="weak")]
    out = apply_scan_filters(rows, _f(stringContains={"note": "STRONG"}))
    assert out == ["A"]


def test_string_equals_is_strict():
    rows = [row("A", sector="Tech"), row("B", sector="tech")]
    out = apply_scan_filters(rows, _f(stringEquals={"sector": "Tech"}))
    assert out == ["A"]


# ── workflow filters (note metadata merged into row_data as __note_*) ──────

def _row_with_note(symbol, **note_kwargs):
    rd = {f"__note_{k}": v for k, v in note_kwargs.items()}
    return {"symbol": symbol, "row_data": rd}


def test_status_filter_active_only():
    rows = [_row_with_note("A", status="active"), _row_with_note("B", status="dismissed")]
    assert apply_scan_filters(rows, _f(status="active")) == ["A"]


def test_has_row_note_yes():
    rows = [_row_with_note("A", hasRowNote=True), _row_with_note("B", hasRowNote=False)]
    assert apply_scan_filters(rows, _f(hasRowNote="yes")) == ["A"]


def test_highlighted_no():
    rows = [_row_with_note("A", highlighted=True), _row_with_note("B", highlighted=False)]
    assert apply_scan_filters(rows, _f(noteHighlighted="no")) == ["B"]


def test_stage_explicit_none_marker():
    rows = [_row_with_note("A", stage="entry"), _row_with_note("B", stage=None)]
    assert apply_scan_filters(rows, _f(noteStage="__none__")) == ["B"]


def test_stage_specific_value():
    rows = [_row_with_note("A", stage="entry"), _row_with_note("B", stage="exit")]
    assert apply_scan_filters(rows, _f(noteStage="entry")) == ["A"]


def test_note_priority_eq():
    rows = [_row_with_note("A", priority=3), _row_with_note("B", priority=5)]
    assert apply_scan_filters(rows, _f(notePriorityEq="3")) == ["A"]


def test_note_priority_min_max_inclusive():
    rows = [_row_with_note("A", priority=1), _row_with_note("B", priority=3), _row_with_note("C", priority=5)]
    out = apply_scan_filters(rows, _f(notePriorityMin="2", notePriorityMax="4"))
    assert out == ["B"]


def test_note_tags_any_match():
    rows = [
        _row_with_note("A", tags=["alpha", "beta"]),
        _row_with_note("B", tags=["gamma"]),
        _row_with_note("C", tags=[]),
    ]
    out = apply_scan_filters(rows, _f(noteTagsAny=["alpha", "gamma"]))
    assert set(out) == {"A", "B"}


def test_combined_workflow_and_row_filters():
    rows = [
        {"symbol": "A", "row_data": {"rs": 90, "__note_status": "active", "__note_highlighted": True}},
        {"symbol": "B", "row_data": {"rs": 95, "__note_status": "active", "__note_highlighted": False}},
        {"symbol": "C", "row_data": {"rs": 85, "__note_status": "dismissed", "__note_highlighted": True}},
    ]
    out = apply_scan_filters(rows, _f(
        status="active",
        noteHighlighted="yes",
        numMin={"rs": "80"},
    ))
    assert out == ["A"]
