/**
 * Helpers for dynamic Results tab: discover columns / filterable keys from user_scan_rows.row_data.
 */

export function normalizeRowData(raw: unknown): Record<string, unknown> {
  if (raw && typeof raw === "object" && !Array.isArray(raw)) {
    return { ...(raw as Record<string, unknown>) };
  }
  if (typeof raw === "string") {
    try {
      const p = JSON.parse(raw) as unknown;
      if (p && typeof p === "object" && !Array.isArray(p)) {
        return { ...(p as Record<string, unknown>) };
      }
    } catch {
      /* ignore */
    }
  }
  return {};
}

/** Shown in Symbol column — omit from dynamic data columns to avoid duplication */
export const ROW_DATA_SYMBOL_KEYS = new Set(["symbol", "ticker", "Symbol"]);

/** Preferred column order (first keys that exist in the run appear in this order; rest alphabetical) */
export const ROW_DATA_COLUMN_PRIORITY: string[] = [
  "sector",
  "industry",
  "subSector",
  "RS_Rank",
  "Passed",
  "PASSED_FUNDAMENTALS",
  "PriceOverSMA150And200",
  "SMA150AboveSMA200",
  "SMA50AboveSMA150And200",
  "SMA200Slope",
  "PriceAbove25Percent52WeekLow",
  "PriceWithin25Percent52WeekHigh",
  "RSOver70",
  "beat_estimate",
  "increasing_eps",
  "eps_growth_yoy",
  "rev_growth_yoy",
  "roe",
  "eps_accelerating",
  "passes_oneil_fundamentals",
  "rs_line_new_high",
  "within_buy_range",
  "sector_is_leader",
  "inst_shares_increasing",
  "adr_pct",
  "accumulation",
  "vol_ratio_today",
  "up_down_vol_ratio",
  "inst_pct_accumulating",
  "sector_rank",
  "total_sectors",
];

export function collectAllRowDataKeys(rows: { rowData: Record<string, unknown> }[]): Set<string> {
  const set = new Set<string>();
  for (const r of rows) {
    for (const k of Object.keys(r.rowData)) {
      if (!ROW_DATA_SYMBOL_KEYS.has(k)) set.add(k);
    }
  }
  return set;
}

export function orderedDataColumnKeys(allKeys: Set<string>): string[] {
  const out: string[] = [];
  const seen = new Set<string>();
  for (const k of ROW_DATA_COLUMN_PRIORITY) {
    if (allKeys.has(k) && !seen.has(k)) {
      out.push(k);
      seen.add(k);
    }
  }
  const rest = [...allKeys].filter((k) => !seen.has(k)).sort((a, b) => a.localeCompare(b));
  return [...out, ...rest];
}

function isEmptyish(v: unknown): boolean {
  return v === null || v === undefined;
}

/** Every non-empty value is boolean → treat column as boolean (for alignment / hints). */
export function isBooleanColumn(rows: { rowData: Record<string, unknown> }[], key: string): boolean {
  let any = false;
  for (const r of rows) {
    const v = r.rowData[key];
    if (isEmptyish(v)) continue;
    any = true;
    if (typeof v !== "boolean") return false;
  }
  return any;
}

/** Every non-empty value is finite number */
export function isNumericColumn(rows: { rowData: Record<string, unknown> }[], key: string): boolean {
  let any = false;
  for (const r of rows) {
    const v = r.rowData[key];
    if (isEmptyish(v)) continue;
    any = true;
    const n = typeof v === "number" ? v : parseFloat(String(v));
    if (!Number.isFinite(n)) return false;
  }
  return any;
}

/** Keys in `allKeys` whose non-empty values are all booleans — used for “require true” filters. */
export function inferBooleanFilterKeys(
  rows: { rowData: Record<string, unknown> }[],
  allKeys: string[],
): string[] {
  return allKeys.filter((k) => isBooleanColumn(rows, k));
}

/** Keys in `allKeys` whose non-empty values are all finite numbers — used for min/max filters. */
export function inferNumericFilterKeys(
  rows: { rowData: Record<string, unknown> }[],
  allKeys: string[],
): string[] {
  return allKeys.filter((k) => isNumericColumn(rows, k));
}

/** Stable string form for matching categorical / text filters to row_data values. */
export function stringifyRowDataValueForFilter(v: unknown): string {
  if (v === null || v === undefined) return "";
  if (typeof v === "string") return v.trim();
  if (typeof v === "number" && Number.isFinite(v)) {
    return Number.isInteger(v) ? String(v) : String(v);
  }
  if (typeof v === "boolean") return v ? "true" : "false";
  try {
    return JSON.stringify(v);
  } catch {
    return String(v);
  }
}

/** Distinct non-empty string forms for a column (for low-cardinality pickers). */
export function uniqueStringValuesForKey(
  rows: { rowData: Record<string, unknown> }[],
  key: string,
): string[] {
  const set = new Set<string>();
  for (const r of rows) {
    const s = stringifyRowDataValueForFilter(r.rowData[key]);
    if (s) set.add(s);
  }
  return [...set].sort((a, b) => a.localeCompare(b, undefined, { sensitivity: "base", numeric: true }));
}

/** At most this many distinct values → show checkboxes; otherwise a “contains” text field. */
export const MAX_CATEGORICAL_STRING_OPTIONS = 24;

/** Coerce for sorting: strings, numbers, booleans; nulls last */
export function compareRowDataValues(a: unknown, b: unknown): number {
  if (a === b) return 0;
  const ae = isEmptyish(a);
  const be = isEmptyish(b);
  if (ae && be) return 0;
  if (ae) return 1;
  if (be) return -1;
  if (typeof a === "number" && typeof b === "number") return a - b;
  if (typeof a === "boolean" && typeof b === "boolean") return Number(a) - Number(b);
  const sa = String(a);
  const sb = String(b);
  const na = parseFloat(sa);
  const nb = parseFloat(sb);
  if (Number.isFinite(na) && Number.isFinite(nb) && sa.trim() !== "" && sb.trim() !== "") {
    return na - nb;
  }
  return sa.localeCompare(sb, undefined, { sensitivity: "base", numeric: true });
}

export function getRowDataValue(row: { rowData: Record<string, unknown> }, key: string): unknown {
  return row.rowData[key];
}
