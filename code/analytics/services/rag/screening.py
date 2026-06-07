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

    # Multi-select status: new shape uses statusIn/statusNotIn arrays.
    # Legacy fallback: single `status` string ("all" = no filter).
    status_in: list[str] = list(filters.get("statusIn") or [])
    status_not_in: list[str] = list(filters.get("statusNotIn") or [])
    if not status_in:
        legacy_status = filters.get("status") or "all"
        if legacy_status and legacy_status != "all":
            status_in = [str(legacy_status)]

    wf_has_row_note = filters.get("hasRowNote") or "any"
    wf_highlighted = filters.get("noteHighlighted") or "any"
    wf_active_position = filters.get("activePosition") or "any"
    wf_comment = filters.get("noteComment") or "any"

    # Multi-select stage: new shape uses noteStageIn/noteStageNotIn arrays +
    # noteStageEmpty ("any" / "yes" / "no"). Legacy: single `noteStage` field
    # with "__none__" sentinel meaning "stage is empty".
    stage_in: list[str] = list(filters.get("noteStageIn") or [])
    stage_not_in: list[str] = list(filters.get("noteStageNotIn") or [])
    stage_empty: str = filters.get("noteStageEmpty") or "any"
    legacy_stage = (filters.get("noteStage") or "").strip()
    if not stage_in and legacy_stage and legacy_stage != "__none__":
        stage_in = [legacy_stage]
    if stage_empty == "any" and legacy_stage == "__none__":
        stage_empty = "yes"

    wf_priority_eq = (filters.get("notePriorityEq") or "").strip()
    wf_priority_neq = (filters.get("notePriorityNeq") or "").strip()
    wf_priority_gt = (filters.get("notePriorityGt") or "").strip()
    wf_priority_lt = (filters.get("notePriorityLt") or "").strip()
    wf_priority_min = (filters.get("notePriorityMin") or "").strip()
    wf_priority_max = (filters.get("notePriorityMax") or "").strip()
    wf_tags_any: list[str] = filters.get("noteTagsAny") or []
    wf_tags_none: list[str] = filters.get("noteTagsNone") or []

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
        if status_in:
            if str(rd.get("__note_status") or "") not in status_in:
                continue
        if status_not_in:
            if str(rd.get("__note_status") or "") in status_not_in:
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
        stage_val = str(rd.get("__note_stage") or "").strip()
        if stage_empty == "yes" and stage_val:
            continue
        if stage_empty == "no" and not stage_val:
            continue
        if stage_in:
            if not stage_val or stage_val not in stage_in:
                continue
        if stage_not_in:
            if stage_val and stage_val in stage_not_in:
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

        if wf_tags_any or wf_tags_none:
            note_tags: list[str] = rd.get("__note_tags") or []
            if wf_tags_any and not any(t in note_tags for t in wf_tags_any):
                continue
            if wf_tags_none and any(t in note_tags for t in wf_tags_none):
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


def resolve_latest_run_ids_for_sources(
    user_id: str | None,
    sources: list[str],
) -> list[int]:
    """Resolve each followed `source` to the newest active user_scan_runs.id.

    Returns one run ID per source (the most recent active run for that user +
    source), in the order sources first appear newest. Empty user_id/sources
    yields []. Used by the agent engine so a "followed source" auto-switches to
    the latest run as fresh runs land periodically.
    """
    if not user_id or not sources:
        return []

    client = get_supabase_client()
    schema = "swingtrader"

    rows = (
        client.schema(schema)
        .table("user_scan_runs")
        .select("id, scan_date, source")
        .eq("user_id", user_id)
        .eq("status", "active")
        .in_("source", sources)
        .order("scan_date", desc=True)
        .execute()
    ).data or []

    # rows are scan_date desc; first row seen per source is the newest.
    latest_by_source: dict[str, int] = {}
    for r in rows:
        src = r.get("source")
        if src and src not in latest_by_source and r.get("id") is not None:
            latest_by_source[src] = int(r["id"])

    return list(latest_by_source.values())
