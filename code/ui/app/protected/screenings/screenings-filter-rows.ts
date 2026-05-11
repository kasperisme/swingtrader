import {
  compareRowDataValues,
  getRowDataValue,
  stringifyRowDataValueForFilter,
} from "./screenings-row-data";
import type { ScreeningsFilters } from "./screenings-filters-model";
import type { ScreeningRow, ScanRowNote } from "./screenings-types";

/**
 * Apply screenings filters, optional text search, then sort.
 * Mirrors the Results table pipeline in `ScreeningsUI`.
 */
export function filterAndSortScreeningRows(
  rows: ScreeningRow[],
  rowNotes: Map<number, ScanRowNote>,
  filters: ScreeningsFilters,
  search: string,
  sortKey: string,
  sortDir: "asc" | "desc",
  activePositionSymbols: Set<string>,
): ScreeningRow[] {
  let result = rows.filter((r) => {
    if (filters.symbolContains?.trim()) {
      const q = filters.symbolContains.trim().toUpperCase();
      if (!r.symbol?.toUpperCase().includes(q)) return false;
    }

    const note = rowNotes.get(r.scan_row_id);
    const hasSavedNote = note !== undefined;
    if (filters.hasRowNote === "yes" && !hasSavedNote) return false;
    if (filters.hasRowNote === "no" && hasSavedNote) return false;

    const status = note?.status ?? "active";
    if (
      filters.statusIn.length > 0 &&
      !filters.statusIn.includes(status as never)
    ) {
      return false;
    }
    if (
      filters.statusNotIn.length > 0 &&
      filters.statusNotIn.includes(status as never)
    ) {
      return false;
    }

    const highlighted = note?.highlighted ?? false;
    if (filters.noteHighlighted === "yes" && !highlighted) return false;
    if (filters.noteHighlighted === "no" && highlighted) return false;

    const hasPosition = activePositionSymbols.has(r.symbol ?? "");
    if (filters.activePosition === "yes" && !hasPosition) return false;
    if (filters.activePosition === "no" && hasPosition) return false;

    const commentTrim = note?.comment?.trim() ?? "";
    if (filters.noteComment === "with" && !commentTrim) return false;
    if (filters.noteComment === "without" && commentTrim) return false;

    const stageStr = note?.stage?.trim() ?? "";
    if (filters.noteStageEmpty === "yes" && stageStr) return false;
    if (filters.noteStageEmpty === "no" && !stageStr) return false;
    if (filters.noteStageIn.length > 0) {
      if (!stageStr || !filters.noteStageIn.includes(stageStr)) return false;
    }
    if (filters.noteStageNotIn.length > 0) {
      if (stageStr && filters.noteStageNotIn.includes(stageStr)) return false;
    }

    const pminStr = filters.notePriorityMin.trim();
    if (pminStr) {
      const pmin = parseFloat(pminStr);
      if (Number.isFinite(pmin)) {
        const p = note?.priority;
        if (p == null || !Number.isFinite(p) || p < pmin) return false;
      }
    }
    const pmaxStr = filters.notePriorityMax.trim();
    if (pmaxStr) {
      const pmax = parseFloat(pmaxStr);
      if (Number.isFinite(pmax)) {
        const p = note?.priority;
        if (p == null || !Number.isFinite(p) || p > pmax) return false;
      }
    }
    const pgtNote = filters.notePriorityGt.trim();
    if (pgtNote) {
      const bound = parseFloat(pgtNote);
      if (Number.isFinite(bound)) {
        const p = note?.priority;
        if (p == null || !Number.isFinite(p) || p <= bound) return false;
      }
    }
    const pltNote = filters.notePriorityLt.trim();
    if (pltNote) {
      const bound = parseFloat(pltNote);
      if (Number.isFinite(bound)) {
        const p = note?.priority;
        if (p == null || !Number.isFinite(p) || p >= bound) return false;
      }
    }
    const pneqNote = (filters.notePriorityNeq ?? "").trim();
    if (pneqNote) {
      const bound = parseFloat(pneqNote);
      if (Number.isFinite(bound)) {
        const p = note?.priority;
        if (p != null && Number.isFinite(p) && p === bound) return false;
      }
    }

    if (filters.noteTagsAny.length > 0 || filters.noteTagsNone.length > 0) {
      const rowTags = new Set(
        (note?.tags ?? []).map((t) => String(t).trim()).filter(Boolean),
      );
      if (
        filters.noteTagsAny.length > 0 &&
        !filters.noteTagsAny.some((t) => rowTags.has(t))
      ) {
        return false;
      }
      if (
        filters.noteTagsNone.length > 0 &&
        filters.noteTagsNone.some((t) => rowTags.has(t))
      ) {
        return false;
      }
    }

    for (const [k, on] of Object.entries(filters.boolRequire)) {
      if (on && !getRowDataValue(r, k)) return false;
    }
    for (const [k, on] of Object.entries(filters.boolReject)) {
      if (on && getRowDataValue(r, k)) return false;
    }

    for (const [k, minStr] of Object.entries(filters.numMin)) {
      const t = minStr?.trim();
      if (!t) continue;
      const min = parseFloat(t);
      if (!Number.isFinite(min)) continue;
      const v = getRowDataValue(r, k);
      const n = typeof v === "number" ? v : parseFloat(String(v));
      if (!Number.isFinite(n) || n < min) return false;
    }
    for (const [k, maxStr] of Object.entries(filters.numMax)) {
      const t = maxStr?.trim();
      if (!t) continue;
      const max = parseFloat(t);
      if (!Number.isFinite(max)) continue;
      const v = getRowDataValue(r, k);
      const n = typeof v === "number" ? v : parseFloat(String(v));
      if (!Number.isFinite(n) || n > max) return false;
    }
    for (const [k, gtStr] of Object.entries(filters.numGt)) {
      const t = gtStr?.trim();
      if (!t) continue;
      const gt = parseFloat(t);
      if (!Number.isFinite(gt)) continue;
      const v = getRowDataValue(r, k);
      const n = typeof v === "number" ? v : parseFloat(String(v));
      if (!Number.isFinite(n) || n <= gt) return false;
    }
    for (const [k, ltStr] of Object.entries(filters.numLt)) {
      const t = ltStr?.trim();
      if (!t) continue;
      const lt = parseFloat(t);
      if (!Number.isFinite(lt)) continue;
      const v = getRowDataValue(r, k);
      const n = typeof v === "number" ? v : parseFloat(String(v));
      if (!Number.isFinite(n) || n >= lt) return false;
    }
    for (const [k, neqStr] of Object.entries(filters.numNeq ?? {})) {
      const t = neqStr?.trim();
      if (!t) continue;
      const neq = parseFloat(t);
      if (!Number.isFinite(neq)) continue;
      const v = getRowDataValue(r, k);
      const n = typeof v === "number" ? v : parseFloat(String(v));
      // Reject only when the row has a comparable number that matches.
      // Missing/non-numeric values pass (otherwise neq would silently
      // exclude all unparseable rows, which surprises the user).
      if (Number.isFinite(n) && n === neq) return false;
    }

    for (const [k, allowed] of Object.entries(filters.stringOneOf)) {
      if (!allowed.length) continue;
      const s = stringifyRowDataValueForFilter(getRowDataValue(r, k));
      if (!allowed.includes(s)) return false;
    }
    for (const [k, denied] of Object.entries(filters.stringNoneOf ?? {})) {
      if (!denied.length) continue;
      const s = stringifyRowDataValueForFilter(getRowDataValue(r, k));
      if (denied.includes(s)) return false;
    }
    for (const [k, sub] of Object.entries(filters.stringContains)) {
      const needle = sub.trim().toLowerCase();
      if (!needle) continue;
      const hay = stringifyRowDataValueForFilter(
        getRowDataValue(r, k),
      ).toLowerCase();
      if (!hay.includes(needle)) return false;
    }
    for (const [k, exact] of Object.entries(filters.stringEquals)) {
      const want = exact.trim();
      if (!want) continue;
      const s = stringifyRowDataValueForFilter(getRowDataValue(r, k));
      if (s !== want) return false;
    }
    for (const [k, exact] of Object.entries(filters.stringNotEquals ?? {})) {
      const want = exact.trim();
      if (!want) continue;
      const s = stringifyRowDataValueForFilter(getRowDataValue(r, k));
      if (s === want) return false;
    }

    return true;
  });

  if (search.trim()) {
    const q = search.trim().toLowerCase();
    result = result.filter((r) => {
      if (r.symbol?.toLowerCase().includes(q)) return true;
      for (const v of Object.values(r.rowData)) {
        if (v == null) continue;
        if (typeof v === "object") {
          try {
            if (JSON.stringify(v).toLowerCase().includes(q)) return true;
          } catch {
            /* ignore */
          }
        } else if (String(v).toLowerCase().includes(q)) return true;
      }
      return false;
    });
  }

  result = [...result].sort((a, b) => {
    let cmp = 0;
    if (sortKey === "symbol")
      cmp = (a.symbol ?? "").localeCompare(b.symbol ?? "");
    else
      cmp = compareRowDataValues(
        getRowDataValue(a, sortKey),
        getRowDataValue(b, sortKey),
      );
    return sortDir === "asc" ? cmp : -cmp;
  });

  return result;
}
