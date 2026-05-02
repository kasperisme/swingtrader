import type { ScreeningsFilters } from "./screenings-filters-model";
import { stringifyRowDataValueForFilter } from "./screenings-row-data";

export type FilterableRow = {
  symbol: string;
  rowData: Record<string, unknown>;
};

/**
 * Applies all portions of ScreeningsFilters to an array of rows.
 * Workflow-note fields (status, hasRowNote, etc.) are checked against
 * `__note_*` keys in rowData when present (set by the agent scan-row loader).
 * If these keys are absent, workflow filters are silently skipped.
 */
export function applyRowDataFilters(
  rows: FilterableRow[],
  filters: ScreeningsFilters
): FilterableRow[] {
  return rows.filter((r) => {
    // Symbol contains
    if (
      filters.symbolContains?.trim() &&
      !r.symbol.toLowerCase().includes(filters.symbolContains.trim().toLowerCase())
    ) {
      return false;
    }

    // Workflow: status
    if (filters.status !== "all" && filters.status !== undefined) {
      const s = r.rowData.__note_status;
      if (s !== filters.status) return false;
    }

    // Workflow: has row note
    if (filters.hasRowNote === "yes") {
      if (!r.rowData.__note_hasRowNote) return false;
    } else if (filters.hasRowNote === "no") {
      if (r.rowData.__note_hasRowNote) return false;
    }

    // Workflow: highlighted
    if (filters.noteHighlighted === "yes") {
      if (!r.rowData.__note_highlighted) return false;
    } else if (filters.noteHighlighted === "no") {
      if (r.rowData.__note_highlighted) return false;
    }

    // Workflow: active position
    if (filters.activePosition === "yes") {
      if (!r.rowData.__note_activePosition) return false;
    } else if (filters.activePosition === "no") {
      if (r.rowData.__note_activePosition) return false;
    }

    // Workflow: comment
    if (filters.noteComment === "with") {
      if (!r.rowData.__note_comment) return false;
    } else if (filters.noteComment === "without") {
      if (r.rowData.__note_comment) return false;
    }

    // Workflow: stage
    if (filters.noteStage === "__none__") {
      if (r.rowData.__note_stage) return false;
    } else if (filters.noteStage) {
      if (r.rowData.__note_stage !== filters.noteStage) return false;
    }

    // Workflow: priority
    const pq = (s: string) => s.trim();
    if (pq(filters.notePriorityEq)) {
      const target = parseFloat(pq(filters.notePriorityEq));
      const v = r.rowData.__note_priority;
      const n = typeof v === "number" ? v : parseFloat(String(v));
      if (n !== target) return false;
    } else {
      if (pq(filters.notePriorityGt)) {
        const b = parseFloat(pq(filters.notePriorityGt));
        const v = r.rowData.__note_priority;
        const n = typeof v === "number" ? v : parseFloat(String(v));
        if (!Number.isFinite(n) || n <= b) return false;
      }
      if (pq(filters.notePriorityLt)) {
        const b = parseFloat(pq(filters.notePriorityLt));
        const v = r.rowData.__note_priority;
        const n = typeof v === "number" ? v : parseFloat(String(v));
        if (!Number.isFinite(n) || n >= b) return false;
      }
      if (pq(filters.notePriorityMin)) {
        const b = parseFloat(pq(filters.notePriorityMin));
        const v = r.rowData.__note_priority;
        const n = typeof v === "number" ? v : parseFloat(String(v));
        if (!Number.isFinite(n) || n < b) return false;
      }
      if (pq(filters.notePriorityMax)) {
        const b = parseFloat(pq(filters.notePriorityMax));
        const v = r.rowData.__note_priority;
        const n = typeof v === "number" ? v : parseFloat(String(v));
        if (!Number.isFinite(n) || n > b) return false;
      }
    }

    // Workflow: tags
    if (filters.noteTagsAny.length > 0) {
      const tags = r.rowData.__note_tags;
      const arr = Array.isArray(tags) ? tags : [];
      if (!filters.noteTagsAny.some((t) => arr.includes(t))) return false;
    }

    // Boolean require / reject
    for (const [key, on] of Object.entries(filters.boolRequire)) {
      if (!on) continue;
      const v = r.rowData[key];
      if (!v) return false;
    }
    for (const [key, on] of Object.entries(filters.boolReject)) {
      if (!on) continue;
      const v = r.rowData[key];
      if (v) return false;
    }

    // Numeric bounds
    for (const [key, bound] of Object.entries(filters.numMin)) {
      if (!bound?.trim()) continue;
      const b = parseFloat(bound);
      if (!Number.isFinite(b)) continue;
      const raw = r.rowData[key];
      const v = typeof raw === "number" ? raw : parseFloat(String(raw));
      if (!Number.isFinite(v) || v < b) return false;
    }
    for (const [key, bound] of Object.entries(filters.numMax)) {
      if (!bound?.trim()) continue;
      const b = parseFloat(bound);
      if (!Number.isFinite(b)) continue;
      const raw = r.rowData[key];
      const v = typeof raw === "number" ? raw : parseFloat(String(raw));
      if (!Number.isFinite(v) || v > b) return false;
    }
    for (const [key, bound] of Object.entries(filters.numGt)) {
      if (!bound?.trim()) continue;
      const b = parseFloat(bound);
      if (!Number.isFinite(b)) continue;
      const raw = r.rowData[key];
      const v = typeof raw === "number" ? raw : parseFloat(String(raw));
      if (!Number.isFinite(v) || v <= b) return false;
    }
    for (const [key, bound] of Object.entries(filters.numLt)) {
      if (!bound?.trim()) continue;
      const b = parseFloat(bound);
      if (!Number.isFinite(b)) continue;
      const raw = r.rowData[key];
      const v = typeof raw === "number" ? raw : parseFloat(String(raw));
      if (!Number.isFinite(v) || v >= b) return false;
    }

    // String one-of
    for (const [key, allowed] of Object.entries(filters.stringOneOf)) {
      if (!allowed?.length) continue;
      const s = stringifyRowDataValueForFilter(r.rowData[key]);
      if (!allowed.includes(s)) return false;
    }

    // String contains
    for (const [key, needle] of Object.entries(filters.stringContains)) {
      if (!needle?.trim()) continue;
      const s = stringifyRowDataValueForFilter(r.rowData[key]).toLowerCase();
      if (!s.includes(needle.trim().toLowerCase())) return false;
    }

    // String equals
    for (const [key, expected] of Object.entries(filters.stringEquals)) {
      if (!expected?.trim()) continue;
      const s = stringifyRowDataValueForFilter(r.rowData[key]);
      if (s !== expected.trim()) return false;
    }

    return true;
  });
}
