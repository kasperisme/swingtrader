"""
Scan row filtering and ticker resolution.

Extracted from services/agent/engine.py (_apply_scan_filters,
_get_filtered_tickers_from_scan). Previously unreachable by other services
because it lived inside the agent orchestrator.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from shared.db import get_supabase_client, _as_json

log = logging.getLogger(__name__)


def _stringify_value(v: Any) -> str:
    """Mirror stringifyRowDataValueForFilter from screenings-row-data.ts."""
    if v is None:
        return ""
    if isinstance(v, str):
        return v.strip()
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    try:
        return json.dumps(v)
    except Exception:
        return str(v)


def apply_scan_filters(rows: list[dict], filters: dict) -> list[str]:
    """Apply ScreeningsFilters to scan rows. Returns ordered, deduplicated symbols.

    Handles both row-data filters (numMin/Max, boolRequire, stringOneOf, etc.)
    and workflow-note filters (__note_* keys merged into row_data by caller).
    """
    symbol_contains = (filters.get("symbolContains") or "").strip().lower()
    bool_require: dict[str, bool] = filters.get("boolRequire") or {}
    bool_reject: dict[str, bool] = filters.get("boolReject") or {}
    num_min: dict[str, str] = filters.get("numMin") or {}
    num_max: dict[str, str] = filters.get("numMax") or {}
    num_gt: dict[str, str] = filters.get("numGt") or {}
    num_lt: dict[str, str] = filters.get("numLt") or {}
    num_neq: dict[str, str] = filters.get("numNeq") or {}
    str_one_of: dict[str, list[str]] = filters.get("stringOneOf") or {}
    str_none_of: dict[str, list[str]] = filters.get("stringNoneOf") or {}
    str_contains: dict[str, str] = filters.get("stringContains") or {}
    str_equals: dict[str, str] = filters.get("stringEquals") or {}
    str_not_equals: dict[str, str] = filters.get("stringNotEquals") or {}

    wf_status = filters.get("status") or "all"
    wf_has_row_note = filters.get("hasRowNote") or "any"
    wf_highlighted = filters.get("noteHighlighted") or "any"
    wf_active_position = filters.get("activePosition") or "any"
    wf_comment = filters.get("noteComment") or "any"
    wf_stage = filters.get("noteStage") or ""
    wf_priority_eq = (filters.get("notePriorityEq") or "").strip()
    wf_priority_neq = (filters.get("notePriorityNeq") or "").strip()
    wf_priority_gt = (filters.get("notePriorityGt") or "").strip()
    wf_priority_lt = (filters.get("notePriorityLt") or "").strip()
    wf_priority_min = (filters.get("notePriorityMin") or "").strip()
    wf_priority_max = (filters.get("notePriorityMax") or "").strip()
    wf_tags_any: list[str] = filters.get("noteTagsAny") or []

    seen: set[str] = set()
    out: list[str] = []

    def _num(v: Any) -> float | None:
        if v is None:
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    for row in rows:
        symbol = str(row.get("symbol") or "")
        rd: dict[str, Any] = row.get("row_data") or {}

        if symbol_contains and symbol_contains not in symbol.lower():
            continue

        # ── Workflow filters ──────────────────────────────────────────────────
        if wf_status != "all":
            if str(rd.get("__note_status")) != wf_status:
                continue
        if wf_has_row_note == "yes" and not rd.get("__note_hasRowNote"):
            continue
        elif wf_has_row_note == "no" and rd.get("__note_hasRowNote"):
            continue
        if wf_highlighted == "yes" and not rd.get("__note_highlighted"):
            continue
        elif wf_highlighted == "no" and rd.get("__note_highlighted"):
            continue
        if wf_active_position == "yes" and not rd.get("__note_activePosition"):
            continue
        elif wf_active_position == "no" and rd.get("__note_activePosition"):
            continue
        if wf_comment == "with" and not rd.get("__note_comment"):
            continue
        elif wf_comment == "without" and rd.get("__note_comment"):
            continue
        if wf_stage == "__none__":
            if rd.get("__note_stage"):
                continue
        elif wf_stage:
            if str(rd.get("__note_stage") or "") != wf_stage:
                continue

        if wf_priority_eq:
            pv = _num(rd.get("__note_priority"))
            if pv is None or pv != float(wf_priority_eq):
                continue
        else:
            if wf_priority_gt:
                pv = _num(rd.get("__note_priority"))
                if pv is None or not (pv > float(wf_priority_gt)):
                    continue
            if wf_priority_lt:
                pv = _num(rd.get("__note_priority"))
                if pv is None or not (pv < float(wf_priority_lt)):
                    continue
            if wf_priority_min:
                pv = _num(rd.get("__note_priority"))
                if pv is None or pv < float(wf_priority_min):
                    continue
            if wf_priority_max:
                pv = _num(rd.get("__note_priority"))
                if pv is None or pv > float(wf_priority_max):
                    continue
            if wf_priority_neq:
                pv = _num(rd.get("__note_priority"))
                # Reject only when the row has a comparable priority that
                # matches; missing priorities pass (mirrors the UI evaluator).
                if pv is not None and pv == float(wf_priority_neq):
                    continue

        if wf_tags_any:
            note_tags: list[str] = rd.get("__note_tags") or []
            if not any(t in note_tags for t in wf_tags_any):
                continue

        # ── Row-data filters ─────────────────────────────────────────────────
        skip = False

        for key, on in bool_require.items():
            if on and not rd.get(key):
                skip = True; break
        if skip:
            continue

        for key, on in bool_reject.items():
            if on and rd.get(key):
                skip = True; break
        if skip:
            continue

        for key, bound_s in num_min.items():
            if not (bound_s or "").strip():
                continue
            try:
                if not (float(_stringify_value(rd.get(key))) >= float(bound_s)):
                    skip = True; break
            except (TypeError, ValueError):
                skip = True; break
        if skip:
            continue

        for key, bound_s in num_max.items():
            if not (bound_s or "").strip():
                continue
            try:
                if not (float(_stringify_value(rd.get(key))) <= float(bound_s)):
                    skip = True; break
            except (TypeError, ValueError):
                skip = True; break
        if skip:
            continue

        for key, bound_s in num_gt.items():
            if not (bound_s or "").strip():
                continue
            try:
                if not (float(_stringify_value(rd.get(key))) > float(bound_s)):
                    skip = True; break
            except (TypeError, ValueError):
                skip = True; break
        if skip:
            continue

        for key, bound_s in num_lt.items():
            if not (bound_s or "").strip():
                continue
            try:
                if not (float(_stringify_value(rd.get(key))) < float(bound_s)):
                    skip = True; break
            except (TypeError, ValueError):
                skip = True; break
        if skip:
            continue

        for key, bound_s in num_neq.items():
            if not (bound_s or "").strip():
                continue
            try:
                # Reject only when the value parses AND equals the bound.
                # Unparseable / missing values pass (mirrors the UI).
                if float(_stringify_value(rd.get(key))) == float(bound_s):
                    skip = True; break
            except (TypeError, ValueError):
                pass
        if skip:
            continue

        for key, allowed in str_one_of.items():
            if allowed and _stringify_value(rd.get(key)) not in allowed:
                skip = True; break
        if skip:
            continue

        for key, denied in str_none_of.items():
            if denied and _stringify_value(rd.get(key)) in denied:
                skip = True; break
        if skip:
            continue

        for key, needle in str_contains.items():
            if (needle or "").strip() and needle.strip().lower() not in _stringify_value(rd.get(key)).lower():
                skip = True; break
        if skip:
            continue

        for key, expected in str_equals.items():
            if (expected or "").strip() and _stringify_value(rd.get(key)) != expected.strip():
                skip = True; break
        if skip:
            continue

        for key, banned in str_not_equals.items():
            if (banned or "").strip() and _stringify_value(rd.get(key)) == banned.strip():
                skip = True; break
        if skip:
            continue

        if symbol and symbol not in seen:
            seen.add(symbol)
            out.append(symbol)

    return out


def get_filtered_tickers_from_scan(
    user_id: str | None,
    scan_run_ids: list[int],
    scan_filters: dict,
) -> list[str]:
    """Fetch scan rows + notes for run IDs, merge notes as __note_* keys,
    apply filters, and return the ordered list of matching ticker symbols.
    """
    if not user_id or not scan_run_ids:
        return []

    client = get_supabase_client()
    schema = "swingtrader"

    rows = (
        client.schema(schema)
        .table("user_scan_rows")
        .select("id, symbol, row_data")
        .in_("run_id", scan_run_ids)
        .eq("user_id", user_id)
        .execute()
    ).data or []

    notes_by_row_id: dict[int, dict] = {}
    for n in (
        client.schema(schema)
        .table("user_scan_row_notes")
        .select("scan_row_id, status, highlighted, comment, stage, priority, tags, metadata_json")
        .in_("run_id", scan_run_ids)
        .eq("user_id", user_id)
        .execute()
    ).data or []:
        notes_by_row_id[n["scan_row_id"]] = n

    for row in rows:
        rd: dict[str, Any] = row.get("row_data") or {}
        note = notes_by_row_id.get(row.get("id"))
        if note:
            meta = _as_json(note.get("metadata_json"), default={})
            rd.update({
                "__note_status": note.get("status"),
                "__note_highlighted": bool(note.get("highlighted")),
                "__note_hasRowNote": True,
                "__note_comment": note.get("comment"),
                "__note_stage": note.get("stage"),
                "__note_priority": note.get("priority"),
                "__note_tags": note.get("tags") or [],
                "__note_activePosition": bool(meta.get("activePosition")),
            })
        else:
            rd.update({
                "__note_status": None, "__note_highlighted": False,
                "__note_hasRowNote": False, "__note_comment": None,
                "__note_stage": None, "__note_priority": None,
                "__note_tags": [], "__note_activePosition": False,
            })
        row["row_data"] = rd

    return apply_scan_filters(rows, scan_filters)
